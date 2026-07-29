"""FastAPI authentication dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared_core.db.base import get_session
from packages.shared_core.db.models import Membership, User
from packages.shared_core.exceptions import AuthenticationError
from packages.shared_core.security.user_context import UserContext
from services.identity_service.auth.tokens import decode_access_token

# auto_error=False so a missing header raises our own typed error with a
# consistent JSON body instead of FastAPI's default shape.
bearer_scheme = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_context(
    request: Request,
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> UserContext:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing Authorization header.")
    if credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authorization scheme must be Bearer.")

    claims = decode_access_token(credentials.credentials)
    user_id = claims["sub"]

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        # Token is cryptographically valid but the account is gone/disabled.
        raise AuthenticationError("Account is inactive or no longer exists.")

    rows = await session.execute(
        select(Membership.workspace_id, Membership.role).where(Membership.user_id == user_id)
    )
    ctx = UserContext(
        user_id=user.id,
        email=user.email,
        is_superuser=user.is_superuser,
        memberships=dict(rows.all()),
    )
    request.state.user_context = ctx
    return ctx


CurrentUser = Annotated[UserContext, Depends(get_current_context)]
