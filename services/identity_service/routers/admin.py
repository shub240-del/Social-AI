"""Administrative and introspection endpoints.

Everything here is superuser-only. ``/admin/roles`` is deliberately readable by
any authenticated caller because the frontend renders role pickers from it and
the mapping is not a secret.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from packages.shared_core.config import get_settings
from packages.shared_core.db.models import Conversation, Message, User, Workspace
from packages.shared_core.security.rbac import ROLE_PERMISSIONS, Role
from services.identity_service.auth.dependencies import CurrentUser, SessionDep, SuperUser
from services.identity_service.routing import CommitRoute

router = APIRouter(prefix="/admin", tags=["admin"], route_class=CommitRoute)


@router.get("/roles")
async def roles(user: CurrentUser) -> dict[str, list[str]]:
    """The role-to-permission matrix the UI renders."""
    return {str(role): sorted(str(p) for p in perms) for role, perms in ROLE_PERMISSIONS.items()}


@router.get("/config")
async def config(user: SuperUser) -> dict[str, object]:
    """Effective configuration with every secret omitted, not masked.

    Masked values still confirm length and prefix; omitting the key entirely
    reveals nothing.
    """
    settings = get_settings()
    return {
        "environment": settings.environment,
        "version": settings.release_version,
        "llm": {
            "configured": settings.llm_enabled,
            "provider": "sakana" if settings.llm_enabled else "mock",
            "model": settings.default_llm_model,
            "mock_allowed": settings.allow_mock_llm,
        },
        "email_backend": settings.email_backend,
        "require_email_verification": settings.require_email_verification,
        "cors_origins": settings.cors_origins,
        "rate_limit": {
            "enabled": settings.rate_limit_enabled,
            "per_minute": settings.rate_limit_per_minute,
            "auth_per_minute": settings.auth_rate_limit_per_minute,
        },
        "database": "postgres" if "postgres" in settings.database_url else "sqlite",
        "error_monitoring": bool(settings.sentry_dsn),
    }


@router.get("/stats")
async def stats(user: SuperUser, session: SessionDep) -> dict[str, int]:
    async def count(model: type[Any]) -> int:
        result = await session.execute(select(func.count(model.id)))
        return int(result.scalar_one() or 0)

    return {
        "users": await count(User),
        "workspaces": await count(Workspace),
        "conversations": await count(Conversation),
        "messages": await count(Message),
    }


@router.get("/roles/{role}")
async def role_detail(role: str, user: CurrentUser) -> dict[str, object]:
    try:
        parsed = Role(role)
    except ValueError:
        return {"role": role, "known": False, "permissions": []}
    return {
        "role": str(parsed),
        "known": True,
        "permissions": sorted(str(p) for p in ROLE_PERMISSIONS[parsed]),
    }


__all__ = ["router"]
