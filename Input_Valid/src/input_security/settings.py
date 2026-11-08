"""
Settings for every step of the input validation & security layer.

Values come from environment variables or the project's `.env` file
(pydantic-settings reads both). Every name below can be overridden, for example:

    MAX_QUERY_CHARS=2000
    ALLOWED_LANGUAGES=["en","ta"]
    PURVIEW_ENABLED=true

List values must be written as JSON, as in ALLOWED_LANGUAGES above.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parents[2]  # src/input_security/settings.py -> project root
GUARDRAILS_DIR = Path(__file__).resolve().parent / "guardrails"

LLAMA_GUARD_3_CATEGORIES = [f"S{i}" for i in range(1, 15)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Steps 1-2: request schema and size (Pydantic) -------------------
    max_query_chars: int = Field(4000, gt=0, description="Characters the user may type.")
    # 3 bytes x 4000: any script (Tamil, Hindi, Chinese are 3 bytes per character) can use
    # the full character limit, but a flood of 4-byte emoji or symbols cannot.
    max_query_bytes: int = Field(12_000, gt=0, description="UTF-8 bytes of the query.")
    max_body_bytes: int = Field(32_768, gt=0, description="Raw HTTP body, checked before JSON parsing.")

    # ---- Step 4: language detection (fastText) ---------------------------
    language_check_enabled: bool = True
    fasttext_model_path: Path = PROJECT_DIR / "models" / "lid.176.ftz"
    language_min_letters: int = Field(
        12, description="Below this many letters the text is too short to detect reliably."
    )

    @field_validator("fasttext_model_path", "fastembed_cache_dir")
    @classmethod
    def _relative_to_project(cls, path: Path) -> Path:
        # Services start from their own folders, so a relative path means "from the project root".
        return path if path.is_absolute() else PROJECT_DIR / path

    # ---- Step 5: unsupported language policy (NeMo Guardrails) ----------
    allowed_languages: list[str] = ["en"]
    language_min_confidence: float = Field(0.65, ge=0, le=1)

    # ---- Step 6: PII detection / redaction (Microsoft Presidio) ----------
    pii_enabled: bool = True
    presidio_spacy_model: str = "en_core_web_lg"
    pii_score_threshold: float = Field(0.4, ge=0, le=1)
    pii_entities: list[str] = [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "IBAN_CODE",
        "IP_ADDRESS",
        "US_SSN",
        "IN_PAN",
        "IN_AADHAAR",
        "EMPLOYEE_ID",
    ]
    employee_id_regex: str = r"\bEMP[-_]?\d{4,8}\b"

    # ---- Step 7: enterprise DLP (Microsoft Purview) -----------------------
    purview_enabled: bool = False
    purview_tenant_id: str = ""
    purview_client_id: str = ""
    purview_client_secret: SecretStr = SecretStr("")
    purview_app_name: str = "HR Policy Assistant"
    purview_app_version: str = "1.0"
    purview_timeout_seconds: float = 5.0

    # ---- Step 8: prompt injection (LLM Guard) -----------------------------
    prompt_injection_enabled: bool = True
    prompt_injection_threshold: float = Field(0.92, ge=0, le=1)
    # "chunks" scans the whole query in 256-character windows, so a long query
    # cannot hide an instruction past the model's 512-token limit.
    prompt_injection_match_type: Literal[
        "full", "sentence", "chunks", "truncate_head_tail", "truncate_token_head_tail"
    ] = "chunks"

    # ---- Step 9: jailbreak (LLM Guard) ------------------------------------
    jailbreak_enabled: bool = True
    # Optional zero-shot classifier (LLM Guard BanTopics, ~500 MB of RAM).
    jailbreak_classifier_enabled: bool = False
    jailbreak_classifier_threshold: float = Field(0.75, ge=0, le=1)

    # ---- Step 10: harmful content (Llama Guard) ---------------------------
    harmful_content_enabled: bool = True
    # "http": any OpenAI-compatible server (Ollama for development, vLLM in production)
    # "transformers": load the model inside this process (needs a GPU for 8B)
    llama_guard_backend: Literal["http", "transformers"] = "http"
    llama_guard_base_url: str = "http://localhost:11434/v1"
    llama_guard_model: str = "llama-guard3:1b"
    llama_guard_api_key: SecretStr = SecretStr("")
    llama_guard_timeout_seconds: float = 30.0
    llama_guard_blocked_categories: list[str] = LLAMA_GUARD_3_CATEGORIES

    # ---- Step 11: allowed topic / scope (NeMo Guardrails) -----------------
    topic_scope_enabled: bool = True
    topic_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    fastembed_cache_dir: Path = PROJECT_DIR / "models" / "fastembed"
    # Measured on the sample questions: off-topic <= 0.21, HR questions >= 0.43.
    topic_min_similarity: float = Field(0.35, ge=0, le=1)

    # ---- Pipeline behaviour ----------------------------------------------
    nemo_timeout_seconds: float = 15.0
    # Return the per-step trace to the caller. Keep False in production: the trace
    # tells an attacker which scanner caught them. It is always written to the log.
    expose_step_details: bool = False
    warmup_on_startup: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
