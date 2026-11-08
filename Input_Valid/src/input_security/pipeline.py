"""
The input validation & security pipeline: runs the 11 checks in order.

    payload --> [1-2 Pydantic schema & size] --> [3 encoding] --> [4 language] --> [5 language policy]
            --> [6 PII] --> [7 Purview DLP] --> [8 injection] --> [9 jailbreak] --> [10 harmful]
            --> [11 topic scope] --> SECURITY DECISION --> stage 4: authentication & authorization

How it works
    - Each check is an object with `run(ctx) -> StepResult` (see models.py).
    - A shared ScanContext carries the query between checks. Step 3 replaces it
      with the normalised text and step 6 with the redacted text. Local
      detectors (steps 7, 8, 9, 11) read the normalised text from before
      redaction. Llama Guard (step 10) and stage 4 receive the redacted text.
    - The first REJECT / BLOCK / REDIRECT / ERROR stops the pipeline. Later
      checks do not run, so no time is spent calling Llama Guard for a request
      that is already blocked.
    - A check that raises an exception becomes ERROR (HTTP 503). A broken
      scanner never lets a request through unchecked (fail closed).
    - A check switched off in settings is reported as skipped, so the trace
      always shows what was and was not checked.
    - One log line per request with the decision and every step's outcome.
      User text is never logged, only decisions, scores and entity types.

Used by
    services/fastapi_service  (FastAPI)  and  services/django_service  (Django):
    both call `build_pipeline()` once and then `validate(...)` per request.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional, Sequence

from pydantic import ValidationError

from input_security.decision import NEXT_STAGE, final_decision, is_allowed, message_for
from input_security.models import (
    STOP_DECISIONS,
    Decision,
    ScanContext,
    SecurityResult,
    SecurityStep,
    StepReport,
    StepResult,
)
from input_security.settings import Settings, get_settings
from input_security.validation.request_schema import ChatRequest, explain_errors

logger = logging.getLogger("input_security")

SCHEMA_STEPS = [
    (1, "Request Schema / Empty Query Validation", "Pydantic"),
    (2, "Query Length / Size Validation", "Pydantic"),
]


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def reject_invalid_request(errors: list[dict[str, Any]], latency_ms: float = 0.0) -> SecurityResult:
    """REJECT for a request that failed steps 1-2. `errors` come from explain_errors()."""
    failed_steps = {error["step"] for error in errors} or {1}
    first_step = min(failed_steps)
    reports = [
        StepReport(
            step=number,
            name=name,
            tool=tool,
            decision=Decision.REJECT if number in failed_steps else Decision.CONTINUE,
            reason="; ".join(e["message"] for e in errors if e["step"] == number),
        )
        for number, name, tool in SCHEMA_STEPS
        if number <= max(failed_steps)
    ]
    message = next(e["message"] for e in errors if e["step"] == first_step) if errors else "Invalid request."
    result = SecurityResult(
        request_id=str(uuid.uuid4()),
        decision=Decision.REJECT,
        allowed=False,
        message=message,
        errors=errors,
        steps=reports,
        total_latency_ms=latency_ms,
    )
    _log(result)
    return result


def reject_oversized_body(size: int, limit: int) -> SecurityResult:
    """Step 2 at the HTTP layer: the raw body is bigger than MAX_BODY_BYTES."""
    return reject_invalid_request(
        [
            {
                "step": 2,
                "field": "body",
                "type": "body_too_large",
                "message": f"Request body is {size} bytes; the limit is {limit} bytes.",
            }
        ]
    )


def reject_malformed_body(message: str = "Request body must be valid UTF-8 JSON.") -> SecurityResult:
    """Step 1 at the HTTP layer: the body is not JSON (or not UTF-8)."""
    return reject_invalid_request([{"step": 1, "field": "body", "type": "json_invalid", "message": message}])


def _log(result: SecurityResult) -> None:
    trace = " ".join(
        f"{report.step}:{'SKIP' if report.skipped else report.decision.value}" for report in result.steps
    )
    level = logging.INFO if result.allowed or result.decision == Decision.REDIRECT else logging.WARNING
    logger.log(
        level,
        "input_security request_id=%s decision=%s latency_ms=%.1f steps=[%s]",
        result.request_id,
        result.decision.value,
        result.total_latency_ms,
        trace,
    )
    for report in result.steps:
        if report.decision in STOP_DECISIONS:
            logger.log(level, "input_security request_id=%s step=%s tool=%s reason=%r details=%s",
                       result.request_id, report.step, report.tool, report.reason, report.details)


class SecurityPipeline:
    def __init__(self, steps: Sequence[SecurityStep], *, expose_step_details: bool = False):
        self.steps = list(steps)
        self.expose_step_details = expose_step_details

    def warmup(self) -> None:
        """Load every enabled model now instead of on the first request."""
        for step in self.steps:
            if step.enabled:
                started = time.perf_counter()
                step.warmup()
                logger.info("input_security warmup step=%s tool=%s ms=%.0f", step.number, step.tool, _ms(started))

    # ---- entry points ----------------------------------------------------
    def validate_payload(self, payload: Any, *, user_id: Optional[str] = None, client_ip: Optional[str] = None) -> SecurityResult:
        """Run steps 1-11 on a parsed JSON payload (used by Django)."""
        started = time.perf_counter()
        try:
            request = ChatRequest.model_validate(payload)
        except ValidationError as exc:
            return reject_invalid_request(explain_errors(exc.errors()), _ms(started))
        return self.validate(request, user_id=user_id, client_ip=client_ip, started=started)

    def validate(
        self,
        request: ChatRequest,
        *,
        user_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        started: Optional[float] = None,
    ) -> SecurityResult:
        """Run steps 3-11 on an already validated request (FastAPI validates 1-2 itself)."""
        started = started or time.perf_counter()
        ctx = ScanContext(
            raw_query=request.query,
            query=request.query,
            user_id=user_id,
            client_ip=client_ip,
            session_id=request.session_id,
        )
        reports = [
            StepReport(step=number, name=name, tool=tool, decision=Decision.CONTINUE, reason="Passed.")
            for number, name, tool in SCHEMA_STEPS
        ]
        deciding: Optional[StepResult] = None

        for step in self.steps:
            if not step.enabled:
                reports.append(
                    StepReport(step=step.number, name=step.name, tool=step.tool, decision=Decision.CONTINUE,
                               skipped=True, reason="Disabled in settings.")
                )
                continue

            step_started = time.perf_counter()
            try:
                result = step.run(ctx)
            except Exception as exc:  # fail closed
                logger.exception("input_security request_id=%s step=%s tool=%s failed", ctx.request_id, step.number, step.tool)
                result = StepResult(Decision.ERROR, f"{step.tool} failed: {type(exc).__name__}")

            if result.text is not None:
                ctx.query = result.text
            reports.append(
                StepReport(step=step.number, name=step.name, tool=step.tool, decision=result.decision,
                           reason=result.reason, details=result.details, latency_ms=_ms(step_started))
            )
            if result.decision in STOP_DECISIONS:
                deciding = result
                break
            if result.decision == Decision.MASK:
                deciding = result

        decision = final_decision(reports)
        allowed = is_allowed(decision)
        result = SecurityResult(
            request_id=ctx.request_id,
            decision=decision,
            allowed=allowed,
            message=message_for(decision, deciding),
            sanitized_query=ctx.query if allowed else None,
            next_stage=NEXT_STAGE if allowed else None,
            steps=reports,
            total_latency_ms=_ms(started),
        )
        _log(result)
        return result


def build_pipeline(settings: Optional[Settings] = None) -> SecurityPipeline:
    """Create every check from settings. Models load lazily (or in warmup())."""
    from input_security.language.detection import FastTextLanguageDetector
    from input_security.language.policy import NemoLanguagePolicy
    from input_security.privacy.pii_redaction import PresidioPiiRedactor
    from input_security.privacy.purview_dlp import PurviewDlpCheck
    from input_security.scope.topic_scope import NemoTopicScope
    from input_security.threats.harmful_content import LlamaGuardClassifier
    from input_security.threats.jailbreak import LLMGuardJailbreakDetector
    from input_security.threats.prompt_injection import LLMGuardPromptInjection
    from input_security.validation.encoding import EncodingValidator

    s = settings or get_settings()
    steps: list[SecurityStep] = [
        EncodingValidator(max_chars=s.max_query_chars),
        FastTextLanguageDetector(s.fasttext_model_path, s.language_min_letters, enabled=s.language_check_enabled),
        NemoLanguagePolicy(s.allowed_languages, s.language_min_confidence,
                           enabled=s.language_check_enabled, timeout=s.nemo_timeout_seconds),
        PresidioPiiRedactor(s.presidio_spacy_model, s.pii_entities, s.pii_score_threshold,
                            s.employee_id_regex, enabled=s.pii_enabled),
        PurviewDlpCheck(
            tenant_id=s.purview_tenant_id,
            client_id=s.purview_client_id,
            client_secret=s.purview_client_secret.get_secret_value(),
            app_name=s.purview_app_name,
            app_version=s.purview_app_version,
            timeout=s.purview_timeout_seconds,
            enabled=s.purview_enabled,
        ),
        LLMGuardPromptInjection(s.prompt_injection_threshold, s.prompt_injection_match_type,
                                enabled=s.prompt_injection_enabled),
        LLMGuardJailbreakDetector(enabled=s.jailbreak_enabled, classifier_enabled=s.jailbreak_classifier_enabled,
                                  classifier_threshold=s.jailbreak_classifier_threshold),
        LlamaGuardClassifier(
            backend=s.llama_guard_backend,
            base_url=s.llama_guard_base_url,
            model=s.llama_guard_model,
            api_key=s.llama_guard_api_key.get_secret_value(),
            timeout=s.llama_guard_timeout_seconds,
            blocked_categories=s.llama_guard_blocked_categories,
            enabled=s.harmful_content_enabled,
        ),
        NemoTopicScope(s.topic_embedding_model, s.topic_min_similarity, enabled=s.topic_scope_enabled,
                       timeout=s.nemo_timeout_seconds, cache_dir=str(s.fastembed_cache_dir)),
    ]
    return SecurityPipeline(steps, expose_step_details=s.expose_step_details)
