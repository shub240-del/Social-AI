"""Liveness and readiness probes.

/healthz answers as long as the process is up. /readyz actually checks the
dependencies, so a platform health check cannot route traffic to an instance
whose database is unreachable.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from packages.shared_core.ai.nvidia_client import get_ai_client
from packages.shared_core.config import get_settings
from packages.shared_core.db.base import get_sessionmaker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_STARTED_AT = time.time()


@router.get("/healthz")
async def healthz() -> dict:
    return {
        "status": "ok",
        "service": get_settings().service_name,
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }


@router.get("/readyz")
async def readyz(response: Response) -> dict:
    settings = get_settings()
    checks: dict[str, dict] = {}
    ready = True

    started = time.perf_counter()
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "ok",
            # The dialect name only ("postgresql", "sqlite") — never the URL,
            # which carries credentials. This is what lets a post-deploy check
            # catch the worst silent misconfiguration: a container-local SQLite
            # file that works perfectly until the next redeploy wipes it.
            "dialect": session.bind.dialect.name if session.bind else "unknown",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:
        ready = False
        logger.error("readiness: database check failed: %s", exc)
        checks["database"] = {"status": "error", "detail": str(exc)[:200]}

    # The AI provider is a soft dependency: with no key the deterministic
    # provider serves requests, so the instance is still ready.
    ai = get_ai_client().health()
    checks["ai"] = {"status": "ok" if ai["configured"] else "degraded", **ai}

    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "environment": settings.environment,
        "checks": checks,
    }
