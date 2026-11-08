"""
STEP 5 - Unsupported language policy                       Tool: NeMo Guardrails
==============================================================================

What it does
    Decides whether the language found in step 4 is allowed. If it is not, the
    request is rejected with a polite message in the language the assistant does
    support.

Who does what
    - fastText (step 4)   detects the language
    - Python action here  applies the rule (`decide_language`)
    - NeMo Guardrails     runs the input rail and owns the policy flow and the
                          refusal text (guardrails/language_policy/rails.co)

    Keeping the refusal in Colang means policy owners can change wording or flow
    without touching Python, and the same rails config can later grow more
    checks, for example an LLM self-check.

How it works
    1. Step 4's result is sent to NeMo as context variables:
           detected_language, language_confidence, language_candidates, ...
    2. NeMo runs the input rail "check language policy" (rails.co):
           $language_allowed = execute check_language_policy
           if not $language_allowed
             bot refuse unsupported language
             stop
    3. The action `check_language_policy` calls `decide_language`:
         - too short to detect               -> allowed (default language assumed)
         - allowed language, confident       -> allowed
         - not confident, but an allowed
           language is in the top 3          -> allowed (mixed or short text)
         - anything else                     -> not allowed
    4. NeMo returns status "blocked" and the refusal text -> REJECT (HTTP 422).

Example
    "Combien de jours de congé ai-je ?" (fr, 0.99), allowed ["en"]
      -> REJECT "Sorry, I can only answer questions written in English. ..."
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from input_security.settings import GUARDRAILS_DIR
from input_security.guardrails.runtime import check_input_rails, load_rails
from input_security.models import Decision, ScanContext, StepResult
from input_security.language.detection import LanguageResult

CONFIG_DIR = GUARDRAILS_DIR / "language_policy"

LANGUAGE_NAMES = {
    "en": "English", "ta": "Tamil", "hi": "Hindi", "te": "Telugu", "kn": "Kannada",
    "ml": "Malayalam", "fr": "French", "de": "German", "es": "Spanish", "ar": "Arabic",
    "zh": "Chinese", "ja": "Japanese",
}


def language_names(codes: list[str]) -> str:
    return ", ".join(LANGUAGE_NAMES.get(code, code) for code in codes)


def decide_language(result: LanguageResult, allowed: set[str], min_confidence: float) -> tuple[bool, str]:
    """The language rule itself. Pure function, so it is easy to test."""
    if not result.reliable:
        return True, "Text too short to detect a language; the default language is assumed."
    if result.language in allowed and result.confidence >= min_confidence:
        return True, f"Language '{result.language}' is allowed."
    if result.confidence < min_confidence and any(code in allowed for code, _ in result.candidates):
        return True, "Detection was uncertain, but an allowed language is among the top candidates."
    return False, (
        f"Detected language '{result.language}' (confidence {result.confidence:.2f}) is not in "
        f"the allowed list {sorted(allowed)}."
    )


class NemoLanguagePolicy:
    number = 5
    name = "Unsupported Language Policy"
    tool = "NeMo Guardrails"

    def __init__(self, allowed_languages: list[str], min_confidence: float, enabled: bool = True, timeout: float = 15):
        self.allowed = set(allowed_languages)
        self.allowed_ordered = list(allowed_languages)
        self.min_confidence = min_confidence
        self.enabled = enabled
        self.timeout = timeout
        self._rails = None
        self._lock = threading.Lock()

    # ---- NeMo action: called from the Colang flow ----------------------
    async def check_language_policy(self, context: Optional[dict[str, Any]] = None) -> bool:
        context = context or {}
        result = LanguageResult(
            language=context.get("detected_language", "und"),
            confidence=float(context.get("language_confidence", 0.0)),
            candidates=[tuple(item) for item in context.get("language_candidates", [])],
            reliable=bool(context.get("language_reliable", False)),
        )
        allowed, _ = decide_language(result, self.allowed, self.min_confidence)
        return allowed

    def _load(self):
        if self._rails is None:
            with self._lock:
                if self._rails is None:
                    self._rails = load_rails(
                        CONFIG_DIR, {"check_language_policy": self.check_language_policy}, self.timeout
                    )
        return self._rails

    def warmup(self) -> None:
        self._load()

    def run(self, ctx: ScanContext) -> StepResult:
        language: Optional[LanguageResult] = ctx.language
        if language is None:  # step 4 disabled: nothing to enforce
            return StepResult(Decision.CONTINUE, "No language detected (step 4 is off).")

        context = {
            "detected_language": language.language,
            "language_confidence": language.confidence,
            "language_candidates": [list(item) for item in language.candidates],
            "language_reliable": language.reliable,
            "allowed_language_names": language_names(self.allowed_ordered),
        }
        rails_result = check_input_rails(self._load(), ctx.query, context, self.timeout)
        _, reason = decide_language(language, self.allowed, self.min_confidence)
        details = {"rail_status": rails_result.status.value, "allowed_languages": self.allowed_ordered}

        if rails_result.status.value == "blocked":
            details["rail"] = rails_result.rail
            return StepResult(Decision.REJECT, reason, details, user_message=rails_result.content)
        return StepResult(Decision.CONTINUE, reason, details)
