"""
FastAPI service for stage 3 of the RAG request flow: input validation & security.

Run (from services/fastapi_service):
    uvicorn app.main:app --host 127.0.0.1 --port 8020

    POST http://127.0.0.1:8020/api/v1/validate-query   {"query": "How many leave days do I get?"}
    GET  http://127.0.0.1:8020/docs                     Swagger UI

Request flow
    BodySizeLimitMiddleware  step 2: raw body size, before the JSON is parsed
    ChatRequest (Pydantic)   steps 1-2: schema, empty query, length, bytes
    SecurityPipeline         steps 3-11, then the SECURITY DECISION
    -> 200 / 403 / 413 / 422 / 503 with one JSON shape (input_security.SecurityResult)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import health
from app.api.v1 import query_validation
from app.middleware import BodySizeLimitMiddleware
from input_security import build_pipeline, get_settings
from input_security.pipeline import reject_invalid_request, reject_malformed_body, reject_oversized_body
from input_security.validation.request_schema import explain_errors

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.pipeline = build_pipeline(settings)
    if settings.warmup_on_startup:
        logger.info("Loading all enabled models before accepting traffic ...")
        await run_in_threadpool(app.state.pipeline.warmup)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    expose = settings.expose_step_details

    app = FastAPI(
        title="RAG Input Validation & Security",
        version="1.0.0",
        description="Stage 3 of the RAG request flow. Every query passes here before "
        "authentication, authorization and document retrieval.\n\n"
        "How every framework works and fits into RAG: "
        "[http://127.0.0.1:8021/how-it-works](http://127.0.0.1:8021/how-it-works)",
        lifespan=lifespan,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_body_bytes, expose_step_details=expose)
    app.include_router(health.router)
    app.include_router(query_validation.router, prefix="/api/v1")

    @app.exception_handler(RequestValidationError)
    async def on_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Steps 1-2 failed: answer in the same shape as every other decision."""
        result = reject_invalid_request(explain_errors(exc.errors()))
        return JSONResponse(result.public_dict(expose), status_code=result.http_status)

    @app.exception_handler(StarletteHTTPException)
    async def on_http_exception(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 413 and isinstance(exc.detail, dict):  # streamed body over the limit
            result = reject_oversized_body(exc.detail["size"], exc.detail["limit"])
            return JSONResponse(result.public_dict(expose), status_code=413)
        if exc.status_code == 400 and exc.detail == "There was an error parsing the body":  # e.g. not UTF-8
            result = reject_malformed_body()
            return JSONResponse(result.public_dict(expose), status_code=result.http_status)
        return await http_exception_handler(request, exc)

    return app


app = create_app()
