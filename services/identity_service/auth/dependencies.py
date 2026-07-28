"""Authentication and authorisation dependencies.

``CurrentUser`` proves who is calling. ``WorkspaceContext`` additionally proves
they belong to the workspace named in the path and attaches the permissions
their role grants there.

Ordering matters: membership is checked *before* the resource is looked up, so
a caller who is not a member gets the same answer whether or not the workspace
exists. Doing it the other way round turns 404-vs-403 into a workspace-id
oracle.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared_core.db.base import get_session
from packages.shared_core.db.models import Membership, User, Workspace
from packages.shared_core.exceptions import (
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
)
from packages.shared_core.security.rbac import Permission, UserContext, parse_role, permissions_for
from services.identity_service.auth.tokens import decode_access_token

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# auto_error=False so a missing header raises our own 401 envelope rather than
# FastAPI's default {"detail": ...} shape.
_bearer = HTTPBearer(auto_error=False, description="RS256 access token")


async def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> UserContext:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("An access token is required.")

    claims = decode_access_token(credentials.credentials)
    user_id = claims.get("sub")
    if not user_id:
        raise AuthenticationError("This token identifies no user.")

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        # A token outliving its user (deleted or deactivated) must stop working
        # immediately, so identity is re-checked against the database.
        raise AuthenticationError("This account is no longer active.")

    context = UserContext(
        user_id=user.id,
        email=user.email,
        is_superuser=user.is_superuser,
    )
    request.state.user_id = user.id
    return context


CurrentUser = Annotated[UserContext, Depends(get_current_user)]


async def get_workspace_context(
    user: CurrentUser,
    session: SessionDep,
    workspace_id: Annotated[str, Path(description="Workspace the request targets")],
) -> UserContext:
    result = await session.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user.user_id,
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        if user.is_superuser:
            exists = await session.get(Workspace, workspace_id)
            if exists is None:
                raise NotFoundError("That workspace does not exist.")
            from packages.shared_core.security.rbac import Role

            return UserContext(
                user_id=user.user_id,
                email=user.email,
                is_superuser=True,
                workspace_id=workspace_id,
                role=Role.OWNER,
                permissions=permissions_for(Role.OWNER),
            )
        # Deliberately 404, not 403: confirming that a workspace exists to a
        # non-member is itself a leak.
        raise NotFoundError("That workspace does not exist.")

    role = parse_role(membership.role)
    return UserContext(
        user_id=user.user_id,
        email=user.email,
        is_superuser=user.is_superuser,
        workspace_id=workspace_id,
        role=role,
        permissions=permissions_for(role),
    )


WorkspaceContext = Annotated[UserContext, Depends(get_workspace_context)]


def requires(permission: Permission):
    """Dependency factory enforcing one permission in the path's workspace."""

    async def _check(context: WorkspaceContext) -> UserContext:
        context.require(permission)
        return context

    return _check


async def require_superuser(user: CurrentUser) -> UserContext:
    if not user.is_superuser:
        raise PermissionDeniedError("This endpoint is restricted to administrators.")
    return user


SuperUser = Annotated[UserContext, Depends(require_superuser)]

__all__ = [
    "CurrentUser",
    "SessionDep",
    "SuperUser",
    "WorkspaceContext",
    "get_current_user",
    "get_workspace_context",
    "require_superuser",
    "requires",
]
