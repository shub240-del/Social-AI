"""Registration, login, refresh, logout and identity.

Refresh tokens rotate. Every token belongs to a *family* created at login;
using one mints a replacement in the same family and marks the old one spent.
Presenting an already-spent token means the value leaked, so the entire family
is revoked — the attacker and the victim are both logged out, which is the
correct outcome when you cannot tell which one is which.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select, update

from packages.shared_core.config import get_settings
from packages.shared_core.db.base import new_uuid
from packages.shared_core.db.models import Membership, RefreshToken, User
from packages.shared_core.exceptions import (
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from packages.shared_core.security.passwords import verify_password
from packages.shared_core.security.rbac import parse_role, permissions_for
from services.identity_service.auth.dependencies import CurrentUser, SessionDep
from services.identity_service.auth.tokens import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from services.identity_service.schemas import (
    LoginRequest,
    LogoutRequest,
    MeResponse,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserResponse,
    WorkspaceSummary,
)
from services.identity_service.services.user_provisioning import provision_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _issue_refresh_token(
    session, user: User, *, family_id: str | None = None, request: Request | None = None
) -> str:
    settings = get_settings()
    raw = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw),
            family_id=family_id or new_uuid(),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds),
            user_agent=(request.headers.get("user-agent", "")[:400] if request else None),
            ip_address=(request.client.host if request and request.client else None),
        )
    )
    return raw


def _token_response(user: User, refresh: str) -> TokenResponse:
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user_id=user.id, email=user.email),
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
    )


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, session: SessionDep, request: Request
) -> RegisterResponse:
    user, _workspace = await provision_user(
        session,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
    )

    # Delivery is best effort: a dead SMTP provider must not cost the signup.
    # Imported here so tests can monkeypatch the symbol on this module.
    try:
        from services.identity_service.routers.account import send_verification_email

        await send_verification_email(session, user)
    except Exception:  # noqa: BLE001
        logger.exception("could not send the verification email for %s", user.email)

    refresh = await _issue_refresh_token(session, user, request=request)
    tokens = _token_response(user, refresh)
    return RegisterResponse(
        **tokens.model_dump(), user=UserResponse.model_validate(user)
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: SessionDep, request: Request) -> TokenResponse:
    settings = get_settings()
    result = await session.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()

    # verify_password runs even when the user is missing so that a wrong
    # address and a wrong password take a similar amount of time.
    if user is None or not verify_password(payload.password, user.hashed_password):
        if user is None:
            verify_password(payload.password, None)
        raise InvalidCredentialsError()

    if not user.is_active:
        raise InvalidCredentialsError()

    if settings.require_email_verification and user.email_verified_at is None:
        raise EmailNotVerifiedError()

    user.last_login_at = datetime.now(UTC)
    refresh = await _issue_refresh_token(session, user, request=request)
    return _token_response(user, refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    payload: RefreshRequest, session: SessionDep, request: Request
) -> TokenResponse:
    token_hash = hash_refresh_token(payload.refresh_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if stored is None:
        raise InvalidTokenError("That refresh token is not valid.")

    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    # Replay: this token was already exchanged. Burn the whole family.
    if stored.rotated_to is not None:
        logger.warning(
            "refresh token replay detected; revoking family",
            extra={"user_id": stored.user_id, "family_id": stored.family_id},
        )
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == stored.family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        # Commit before raising. The request-scoped session rolls back on any
        # exception, which would undo the revocation we just performed and
        # leave the leaked family usable — the exact opposite of the intent.
        await session.commit()
        raise InvalidTokenError("This session has been revoked. Please log in again.")

    if stored.revoked_at is not None:
        raise InvalidTokenError("This session has been revoked. Please log in again.")
    if expires_at <= now:
        raise InvalidTokenError("This session has expired. Please log in again.")

    user = await session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("This account is no longer active.")

    replacement = await _issue_refresh_token(
        session, user, family_id=stored.family_id, request=request
    )
    stored.rotated_to = hash_refresh_token(replacement)
    stored.revoked_at = now
    return _token_response(user, replacement)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    payload: LogoutRequest, user: CurrentUser, session: SessionDep
) -> MessageResponse:
    now = datetime.now(UTC)
    if payload.all_sessions or not payload.refresh_token:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return MessageResponse(message="Signed out of every device.")

    # Revoke the family so the rotated descendants die with it.
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(payload.refresh_token),
            RefreshToken.user_id == user.user_id,
        )
    )
    stored = result.scalar_one_or_none()
    if stored is not None:
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == stored.family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
    return MessageResponse(message="Signed out.")


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, session: SessionDep) -> MeResponse:
    db_user = await session.get(User, user.user_id)
    if db_user is None:
        raise InvalidTokenError("This account no longer exists.")

    result = await session.execute(
        select(Membership).where(Membership.user_id == user.user_id)
    )
    memberships = list(result.scalars())

    workspaces = [
        WorkspaceSummary(
            id=m.workspace.id, name=m.workspace.name, slug=m.workspace.slug, role=m.role
        )
        for m in memberships
        if m.workspace is not None
    ]
    workspaces.sort(key=lambda w: w.name.lower())

    permissions: set[str] = set()
    for m in memberships:
        permissions.update(str(p) for p in permissions_for(parse_role(m.role)))

    return MeResponse(
        **UserResponse.model_validate(db_user).model_dump(),
        workspaces=workspaces,
        permissions=sorted(permissions),
    )


@router.get("/sessions", response_model=list[dict])
async def list_sessions(user: CurrentUser, session: SessionDep) -> list[dict]:
    """Active sessions, so a user can spot one they do not recognise."""
    result = await session.execute(
        select(RefreshToken)
        .where(RefreshToken.user_id == user.user_id, RefreshToken.revoked_at.is_(None))
        .order_by(RefreshToken.created_at.desc())
    )
    return [
        {
            "id": t.id,
            "created_at": t.created_at,
            "expires_at": t.expires_at,
            "user_agent": t.user_agent,
            "ip_address": t.ip_address,
        }
        for t in result.scalars()
    ]


__all__ = ["router", "Response"]
