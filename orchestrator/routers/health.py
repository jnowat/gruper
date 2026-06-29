import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str   # "ok" | "degraded"
    version: str
    db: str       # "ok" | "error"


@router.get("/health", response_model=HealthResponse, summary="Liveness and readiness check")
async def health(request: Request) -> HealthResponse:
    pool = request.app.state.pool
    try:
        await pool.fetchval("SELECT 1")
        db_status = "ok"
    except Exception:
        logger.exception("Database health check failed")
        db_status = "error"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        version=settings.orchestrator_version,
        db=db_status,
    )
