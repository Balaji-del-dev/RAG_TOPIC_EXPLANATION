"""
STEP 10 - Harmful content classification                       Tool: Llama Guard
==============================================================================

What it does
    Asks Meta's Llama Guard 3, a safety-tuned LLM, whether the user's message
    falls into one of its 14 hazard categories (violent crimes, self-harm, hate,
    sexual content, weapons, ...). Steps 8-9 look at *how* the user writes
    (attacks on the assistant). This step looks at *what* they ask for.

How it works
    1. Send the (PII-redacted) query as a one-turn conversation to Llama Guard.
       The model's chat template wraps it in Llama Guard's safety prompt, which
       lists the categories S1-S14.
    2. Llama Guard answers in a fixed format:
           safe
       or
           unsafe
           S1,S10
    3. `parse_llama_guard_output` reads that answer:
         - "safe"                               -> CONTINUE
         - "unsafe" + a category in
           LLAMA_GUARD_BLOCKED_CATEGORIES       -> BLOCK (HTTP 403)
         - "unsafe" + only categories you
           chose not to block                   -> CONTINUE, flagged in the trace
         - anything else                        -> ERROR (fail closed)

Two ways to run the model (LLAMA_GUARD_BACKEND)
    "http" (default): any OpenAI-compatible /v1/chat/completions server.
        Development: Ollama   ->  ollama pull llama-guard3:1b-q4_K_M   (955 MB)
                                  LLAMA_GUARD_BASE_URL=http://localhost:11434/v1
        Production : vLLM     ->  vllm serve meta-llama/Llama-Guard-3-8B
                                  LLAMA_GUARD_BASE_URL=http://guard:8000/v1
        The model runs in its own service with its own GPU and scaling, and
        this app only makes an HTTP call.
    "transformers": loads the Hugging Face model inside this process
        (meta-llama/Llama-Guard-3-1B or -8B, a gated model: accept the licence
        on Hugging Face and log in first). 8B needs about 16 GB of GPU memory.

Self-harm (S11)
    The person may need help, not just a refusal, so S11 gets a supportive
    message that points to the Employee Assistance Programme and emergency
    services instead of the generic block text.

Measured with llama-guard3:1b-q4_K_M (2026-11-08)
    10/10 sensitive HR questions judged safe (harassment, bereavement,
    depression, threats, weapons policy, transition leave, miscarriage).
    5/5 harmful requests blocked with the right category (S1, S2, S9, S11).

Example
    "How do I make a pipe bomb?"                  -> BLOCK  [S9 Indiscriminate Weapons]
    "How many annual leave days do employees get?" -> CONTINUE
"""

from __future__ import annotations

import re
import threading
from typing import Optional

import httpx

from input_security.models import Decision, ScanContext, StepResult

SELF_HARM_MESSAGE = (
    "It sounds like you may be going through a difficult time. You don't have to handle it alone: "
    "please contact the Employee Assistance Programme (EAP) or someone you trust, and if you are in "
    "danger right now, call your local emergency number."
)

LLAMA_GUARD_3_CATEGORY_NAMES = {
    "S1": "Violent Crimes",
    "S2": "Non-Violent Crimes",
    "S3": "Sex-Related Crimes",
    "S4": "Child Sexual Exploitation",
    "S5": "Defamation",
    "S6": "Specialized Advice",
    "S7": "Privacy",
    "S8": "Intellectual Property",
    "S9": "Indiscriminate Weapons",
    "S10": "Hate",
    "S11": "Suicide & Self-Harm",
    "S12": "Sexual Content",
    "S13": "Elections",
    "S14": "Code Interpreter Abuse",
}


def parse_llama_guard_output(text: str) -> tuple[bool, list[str]]:
    """Return (is_safe, categories). Raises ValueError on an unexpected answer."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("Llama Guard returned an empty answer.")
    verdict = lines[0].lower()
    if verdict == "safe":
        return True, []
    if verdict == "unsafe":
        categories = re.findall(r"S\d{1,2}", " ".join(lines[1:]).upper())
        return False, categories
    raise ValueError(f"Unexpected Llama Guard answer: {lines[0][:40]!r}")


class LlamaGuardClassifier:
    number = 10
    name = "Harmful Content Classification"
    tool = "Llama Guard"

    def __init__(
        self,
        *,
        backend: str = "http",
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama-guard3:1b",
        api_key: str = "",
        timeout: float = 30.0,
        blocked_categories: Optional[list[str]] = None,
        enabled: bool = True,
        http_client: Optional[httpx.Client] = None,
    ):
        self.backend = backend
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.blocked_categories = set(blocked_categories or LLAMA_GUARD_3_CATEGORY_NAMES)
        self.enabled = enabled
        self._http = http_client or httpx.Client(timeout=timeout)
        self._hf = None
        self._lock = threading.Lock()

    # ---- backend: OpenAI-compatible HTTP (Ollama / vLLM) -----------------
    def _classify_http(self, text: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = self._http.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": text}],
                "temperature": 0,
                "max_tokens": 20,
            },
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    # ---- backend: in-process Hugging Face transformers -------------------
    def _load_transformers(self):
        if self._hf is None:
            with self._lock:
                if self._hf is None:
                    import torch
                    from transformers import AutoModelForCausalLM, AutoTokenizer

                    tokenizer = AutoTokenizer.from_pretrained(self.model)
                    model = AutoModelForCausalLM.from_pretrained(
                        self.model,
                        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                        device_map="auto",
                    )
                    self._hf = (tokenizer, model)
        return self._hf

    def _classify_transformers(self, text: str) -> str:
        import torch

        tokenizer, model = self._load_transformers()
        # The model cards differ: Llama-Guard-3-1B's chat template expects a list of
        # content parts, Llama-Guard-3-8B's expects a plain string.
        content = [{"type": "text", "text": text}] if "1b" in self.model.lower() else text
        conversation = [{"role": "user", "content": content}]
        input_ids = tokenizer.apply_chat_template(conversation, return_tensors="pt").to(model.device)
        with torch.no_grad():
            output = model.generate(input_ids, max_new_tokens=20, do_sample=False, pad_token_id=0)
        return tokenizer.decode(output[0][input_ids.shape[-1]:], skip_special_tokens=True)

    def classify(self, text: str) -> tuple[bool, list[str]]:
        raw = self._classify_transformers(text) if self.backend == "transformers" else self._classify_http(text)
        return parse_llama_guard_output(raw)

    def warmup(self) -> None:
        if self.backend == "transformers":
            self._load_transformers()
        else:
            self.classify("Hello")

    def run(self, ctx: ScanContext) -> StepResult:
        # Redacted text: with the http backend the query leaves this process.
        is_safe, categories = self.classify(ctx.query)
        if is_safe:
            return StepResult(Decision.CONTINUE, "Llama Guard: safe.")

        names = [f"{code} {LLAMA_GUARD_3_CATEGORY_NAMES.get(code, 'Unknown')}" for code in categories]
        details = {"categories": names}
        blocking = [code for code in categories if code in self.blocked_categories]
        if blocking or not categories:  # "unsafe" without a category: fail closed
            message = SELF_HARM_MESSAGE if "S11" in categories else None
            return StepResult(Decision.BLOCK, "Harmful content detected.", details, user_message=message)
        return StepResult(Decision.CONTINUE, "Llama Guard flagged categories that are not blocked.", details)
