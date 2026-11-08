"""
POST /api/v1/validate-query - run stage 3 (input validation & security) on one query.

Steps 1-2 happen before this function runs: FastAPI validates the body against
the Pydantic `ChatRequest` model. Failures go to the RequestValidationError
handler in main.py and come back in the same response shape, with decision
REJECT and HTTP 422.

The endpoint is a plain `def`, not `async def`, on purpose: the scanners are
CPU-bound (PyTorch, spaCy), so FastAPI runs it in its worker thread pool
instead of blocking the event loop.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.dependencies import Caller, get_caller, get_pipeline
from input_security import ChatRequest, SecurityPipeline, SecurityResult

router = APIRouter(tags=["input-validation"])

EXAMPLE_RESPONSES = {
    200: {"description": "CONTINUE, MASK (PII redacted) or REDIRECT (off-topic, allowed=false)"},
    403: {"description": "BLOCK: prompt injection, jailbreak, harmful content or DLP policy"},
    413: {"description": "REJECT: request body larger than MAX_BODY_BYTES"},
    422: {"description": "REJECT: invalid schema, size, encoding or unsupported language"},
    503: {"description": "ERROR: a required scanner is unavailable (fail closed)"},
}


@router.post(
    "/validate-query",
    response_model=SecurityResult,
    response_model_exclude_none=True,
    responses=EXAMPLE_RESPONSES,
    summary="Validate and secure a user query before authentication and RAG retrieval",
)
def validate_query(
    body: ChatRequest,
    pipeline: SecurityPipeline = Depends(get_pipeline),
    caller: Caller = Depends(get_caller),
) -> JSONResponse:
    result = pipeline.validate(body, user_id=caller.user_id, client_ip=caller.client_ip)
    return JSONResponse(result.public_dict(pipeline.expose_step_details), status_code=result.http_status)
