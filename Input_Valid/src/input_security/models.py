"""
Shared data types that every step uses.

    ScanContext   - the query as it moves through the steps (each step can read or change it)
    StepResult    - what one step returns: its decision, a reason, details, maybe new text
    StepReport    - StepResult plus the step number, tool name and time taken (for the trace)
    SecurityResult- the final answer of the whole layer
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field


class Decision(str, Enum):
    CONTINUE = "CONTINUE"  # safe input, go on to authentication
    MASK = "MASK"  # PII was redacted, go on with the redacted query
    REDIRECT = "REDIRECT"  # outside the allowed topics, answer with a redirect message
    REJECT = "REJECT"  # invalid request (schema, size, encoding, language)
    BLOCK = "BLOCK"  # attack, harmful content or DLP policy
    ERROR = "ERROR"  # a required scanner failed, so the request fails closed


# A step returning one of these stops the pipeline.
STOP_DECISIONS = {Decision.REJECT, Decision.BLOCK, Decision.REDIRECT, Decision.ERROR}


@dataclass
class ScanContext:
    """Everything the steps share about one request."""

    raw_query: str
    query: str  # current text: steps 3 (normalise) and 6 (redact) replace it
    normalized_query: str = ""  # after step 3, before PII redaction
    user_id: Optional[str] = None  # Entra object id, needed only by Purview
    client_ip: Optional[str] = None
    session_id: Optional[str] = None
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    language: Any = None  # LanguageResult from step 4, read by step 5

    @property
    def unredacted_query(self) -> str:
        """Normalised text before PII redaction, for checks that run inside this process.

        Steps 7, 8, 9 and 11 read this. Presidio's placeholders look like template
        injection to the step 8 model: "My email is <EMAIL_ADDRESS>, can HR update
        my bank details?" scored 1.0. An injection hidden inside a value Presidio
        would redact (an email address, say) is also only visible here. Anything
        that may leave the process (Llama Guard over HTTP) and stage 4 get `query`,
        the redacted text.
        """
        return self.normalized_query or self.query


@dataclass
class StepResult:
    decision: Decision
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    text: Optional[str] = None  # set when the step changed the query
    user_message: Optional[str] = None  # message for the end user (e.g. a NeMo refusal)


class SecurityStep(Protocol):
    """Interface every step class follows."""

    number: int
    name: str
    tool: str
    enabled: bool

    def run(self, ctx: ScanContext) -> StepResult: ...

    def warmup(self) -> None: ...


class StepReport(BaseModel):
    step: int
    name: str
    tool: str
    decision: Decision
    skipped: bool = False
    reason: str = ""
    latency_ms: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


class SecurityResult(BaseModel):
    request_id: str
    decision: Decision
    allowed: bool
    message: str
    sanitized_query: Optional[str] = None
    next_stage: Optional[str] = None
    total_latency_ms: float = 0.0
    errors: Optional[list[dict[str, Any]]] = None
    steps: list[StepReport] = Field(default_factory=list)

    @property
    def http_status(self) -> int:
        from input_security.decision import HTTP_STATUS

        return HTTP_STATUS[self.decision]

    def public_dict(self, expose_steps: bool) -> dict[str, Any]:
        """What the API returns. The step trace is included only when allowed."""
        data = self.model_dump(mode="json", exclude_none=True)
        if not expose_steps:
            data.pop("steps", None)
        return data
