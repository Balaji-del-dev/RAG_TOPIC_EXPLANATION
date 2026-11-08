"""
input_security - stage 3 of the RAG request flow: input validation & security.

Public API:

    from input_security import build_pipeline, ChatRequest

    pipeline = build_pipeline()                    # once, at startup
    result = pipeline.validate_payload({"query": "How many leave days do I get?"})
    result.decision        # CONTINUE | MASK | REDIRECT | REJECT | BLOCK | ERROR
    result.sanitized_query # what stage 4 (authentication & authorization) receives

Package layout (one module per responsibility):

    validation/request_schema.py   1  Request Schema / Empty Query Validation    Pydantic
    validation/size_limits.py      2  Query Length / Size Validation             Pydantic
    validation/encoding.py         3  Character / Encoding Validation            Python
    language/detection.py          4  Language Detection                         fastText
    language/policy.py             5  Unsupported Language Policy                NeMo Guardrails
    privacy/pii_redaction.py       6  PII Detection / Redaction                  Microsoft Presidio
    privacy/purview_dlp.py         7  Enterprise Sensitive Data Protection       Microsoft Purview
    threats/prompt_injection.py    8  Prompt Injection Detection                 LLM Guard
    threats/jailbreak.py           9  Jailbreak Detection                        LLM Guard
    threats/harmful_content.py    10  Harmful Content Classification            Llama Guard
    scope/topic_scope.py          11  Allowed Topic / Scope Validation          NeMo Guardrails
    decision.py                       SECURITY DECISION
    pipeline.py                       runs 1-11 in order
"""

from input_security.models import Decision, SecurityResult
from input_security.pipeline import SecurityPipeline, build_pipeline
from input_security.settings import Settings, get_settings
from input_security.validation.request_schema import ChatRequest

__all__ = [
    "ChatRequest",
    "Decision",
    "SecurityPipeline",
    "SecurityResult",
    "Settings",
    "build_pipeline",
    "get_settings",
]
