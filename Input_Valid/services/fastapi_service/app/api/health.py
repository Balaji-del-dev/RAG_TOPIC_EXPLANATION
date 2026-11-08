"""
Health probes for Kubernetes / load balancers.

    GET /health/live   the process is up
    GET /health/ready  the pipeline is built; lists which checks are on or off
"""

from fastapi import APIRouter, Depends

from app.dependencies import get_pipeline
from input_security import SecurityPipeline

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready(pipeline: SecurityPipeline = Depends(get_pipeline)) -> dict:
    return {
        "status": "ready",
        "checks": [
            {"step": step.number, "name": step.name, "tool": step.tool, "enabled": step.enabled}
            for step in pipeline.steps
        ],
    }
