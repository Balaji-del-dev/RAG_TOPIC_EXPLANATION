"""
STEP 1 - Request schema / empty query validation                 Tool: Pydantic
==============================================================================

What it protects against
    Requests with the wrong shape: a missing "query", a number instead of text,
    extra fields a caller tries to slip in ({"query": "...", "role": "admin"}),
    or a query that is empty or only spaces.

How it works
    1. The client sends JSON, for example
           {"query": "How many annual leave days do employees get?"}
    2. Pydantic validates it against `ChatRequest`:
         - strict=True        "query" must really be a string: 123, null, [] are refused
         - extra="forbid"     unknown fields are refused
         - QueryText          length and size limits (see size_limits.py)
         - reject_blank_query a query of only spaces / newlines is refused
    3. Any failure raises ValidationError. `explain_errors()` turns it into a
       short list (field, error type, message, step number) for the response.
       The raw input is never echoed back, because it may be huge or hostile.

Where it runs
    FastAPI: the endpoint declares `body: ChatRequest`, so FastAPI validates it.
    Django : the view calls `pipeline.validate_payload(json_dict)`.
    Both use this same class, so the rules are identical.

Examples
    {"query": "   "}                       -> REJECT  (query_blank)
    {"query": 42}                          -> REJECT  (string_type)
    {"query": "hi", "role": "admin"}       -> REJECT  (extra_forbidden)
    {"query": "What is the leave policy?"} -> passes to step 3
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from input_security.validation.size_limits import SIZE_ERROR_TYPES, QueryText


class ChatRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={"examples": [{"query": "How many annual leave days do employees get?"}]},
    )

    query: QueryText = Field(description="The user's question for the RAG assistant.")
    session_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Optional conversation id (letters, digits, '_' and '-').",
    )

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("query_blank", "Query cannot be empty or only whitespace.")
        return value


def explain_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make Pydantic errors safe and readable, and tag each with its step (1 or 2)."""
    explained = []
    for error in errors:
        location = [str(part) for part in error.get("loc", ()) if part != "body"]
        explained.append(
            {
                "step": 2 if error.get("type") in SIZE_ERROR_TYPES else 1,
                "field": ".".join(location) or "body",
                "type": error.get("type", "invalid"),
                "message": error.get("msg", "Invalid request."),
            }
        )
    return explained
