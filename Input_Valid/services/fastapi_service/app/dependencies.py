"""
FastAPI dependencies: the shared pipeline and the caller's identity.
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from input_security import SecurityPipeline


def get_pipeline(request: Request) -> SecurityPipeline:
    """The pipeline is built once in the app lifespan (main.py) and shared by all requests."""
    return request.app.state.pipeline


@dataclass(frozen=True)
class Caller:
    user_id: Optional[str]
    client_ip: Optional[str]


def get_caller(request: Request) -> Caller:
    """
    Who is calling. Only Microsoft Purview (step 7) needs the user id.

    DEMO ONLY: the user id is read from the X-User-Object-Id header, which any
    client can set. In production the API gateway validates the user's JWT
    (stage 4) and forwards the verified `oid` claim; read it from there instead.
    """
    return Caller(
        user_id=request.headers.get("x-user-object-id"),
        client_ip=request.client.host if request.client else None,
    )
