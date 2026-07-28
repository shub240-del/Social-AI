"""Liveness and readiness.

``/healthz`` must never touch a dependency: it answers "is this process
alive". If it checked the database, a brief database blip would make the
orchestrator kill and restart otherwise-healthy containers, turning a small
outage into a crash loop.

``/readyz`` does check the database, because a process that cannot reach its
database should be taken out of the load balancer.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from packages.shared_core.config import get_settings
from packages.shared_core.db.base import get_sessionmaker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_STARTED_AT = time.time()


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "identity_service",
        "version": settings.release_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }


@router.get("/livez", summary="Liveness probe (alias)")
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe")
async def readyz(response: Response) -> dict[str, object]:
    settings = get_settings()
    checks: dict[str, object] = {}

    started = time.perf_counter()
    try:
        factory = get_sessionmaker()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        database_ok = True
    except Exception as exc:  # noqa: BLE001 - readiness must report, not raise
        logger.error("readiness database check failed: %s", exc)
        checks["database"] = {"status": "error", "detail": type(exc).__name__}
        database_ok = False

    # Reported so a misconfigured production deploy is visible from outside.
    checks["llm"] = {
        "status": "ok" if settings.llm_enabled else "mock",
        "provider": "nvidia" if settings.llm_enabled else "mock",
    }
    checks["email"] = {"status": "ok", "backend": settings.email_backend}

    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if database_ok else "degraded",
        "version": settings.release_version,
        "environment": settings.environment,
        "checks": checks,
    }


__all__ = ["router"]
