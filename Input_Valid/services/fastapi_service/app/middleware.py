"""
Step 2 at the HTTP layer: refuse bodies larger than MAX_BODY_BYTES *before*
FastAPI reads them into memory and parses the JSON.

Two cases:
    - Content-Length header present: compared up front, and a 413 is sent
      without reading the body at all.
    - Chunked upload (no Content-Length): bytes are counted as they arrive, and
      reading stops with a 413 as soon as the limit is passed.

In production, set the same limit at the edge too (nginx client_max_body_size,
an API gateway or a load balancer rule). This middleware is the backstop.
"""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from input_security.pipeline import reject_malformed_body, reject_oversized_body

METHODS_WITH_BODY = {"POST", "PUT", "PATCH"}


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int, expose_step_details: bool = False):
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.expose_step_details = expose_step_details

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in METHODS_WITH_BODY:
            await self.app(scope, receive, send)
            return

        header = dict(scope["headers"]).get(b"content-length")
        if header is not None:
            try:
                declared = int(header)
            except ValueError:
                result = reject_malformed_body("Content-Length header is not a number.")
                await self._respond(result, 400, scope, receive, send)
                return
            if declared > self.max_body_bytes:
                result = reject_oversized_body(declared, self.max_body_bytes)
                await self._respond(result, 413, scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    # FastAPI re-raises HTTPException while reading the body; the
                    # handler in main.py turns it into the standard REJECT response.
                    raise HTTPException(status_code=413, detail={"size": received, "limit": self.max_body_bytes})
            return message

        await self.app(scope, limited_receive, send)

    async def _respond(self, result, status_code: int, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(result.public_dict(self.expose_step_details), status_code=status_code)
        await response(scope, receive, send)
