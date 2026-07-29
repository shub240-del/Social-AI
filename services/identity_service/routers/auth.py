"""Registration, login, refresh, logout."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import select, update

from packages.shared_core.config import get_settings
from packages.shared_core.db.models import Membership, RefreshToken, User, Workspace
from packages.shared_core.exceptions import (
    ConflictError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from packages.shared_core.security.passwords import hash_password, verify_password
from packages.shared_core.security.roles import Role
from services.identity_service.auth.dependencies import CurrentUser, SessionDep
from services.identity_service.auth.tokens import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from services.identity_service.routers.account import send_verification_email
from services.identity_service.schemas import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
    WorkspaceOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


async def _unique_slug(session, base: str) -> str:
    slug = base
    n = 1
    while (
        await session.execute(select(Workspace.id).where(Workspace.slug == slug))
    ).first() is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


async def _issue_tokens(session, user: User, family_id: str | None = None) -> TokenResponse:
    """Mint an access/refresh pair.

    ``family_id`` is carried over when rotating so replay of any ancestor can
    revoke every descendant. A fresh login starts a new family.
    """
    settings = get_settings()
    access = create_access_token(user_id=user.id, email=user.email)
    refresh = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            family_id=family_id or str(uuid.uuid4()),
            expires_at=datetime.now(UTC)
            + timedelta(seconds=settings.refresh_token_ttl_seconds),
        )
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: SessionDep) -> TokenResponse:
    email = payload.email.lower()
    existing = await session.execute(select(User.id).where(User.email == email))
    if existing.first() is not None:
        raise ConflictError("An account with that email already exists.")

    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
    )
    session.add(user)
    await session.flush()

    # Every user gets a workspace, so the product is usable immediately after
    # registration rather than dead-ending on an empty dashboard.
    ws_name = (payload.workspace_name or "").strip() or (
        f"{payload.full_name.strip().split(' ')[0]}'s Workspace"
        if payload.full_name.strip()
        else "My Workspace"
    )
    workspace = Workspace(
        name=ws_name,
        slug=await _unique_slug(session, _slugify(ws_name)),
        owner_id=user.id,
    )
    session.add(workspace)
    await session.flush()
    session.add(Membership(user_id=user.id, workspace_id=workspace.id, role=Role.OWNER.value))

    tokens = await _issue_tokens(session, user)
    await session.flush()

    # Send the confirmation link now. A failure here must not lose the account
    # the user just created - they can always request another link.
    try:
        await send_verification_email(session, user)
    except Exception:  # noqa: BLE001 - delivery is best-effort at signup
        logger.warning("could not send the verification email", extra={"user_id": user.id})

    return tokens


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: SessionDep) -> TokenResponse:
    result = await session.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()

    # Always run a verification so the response time does not reveal whether
    # the email exists.
    if not verify_password(payload.password, user.hashed_password if user else None):
        raise InvalidCredentialsError()
    if user is None or not user.is_active:
        raise InvalidCredentialsError()

    # Gated behind a flag: turning this on before an SMTP backend is wired up
    # would lock every existing user out of their account.
    if get_settings().require_email_verification and user.email_verified_at is None:
        raise EmailNotVerifiedError()

    user.last_login_at = datetime.now(UTC)
    tokens = await _issue_tokens(session, user)
    await session.flush()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, session: SessionDep) -> TokenResponse:
    token_hash = hash_refresh_token(payload.refresh_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if stored is None:
        raise InvalidTokenError("Refresh token is invalid or has been revoked.")

    if stored.revoked_at is not None:
        # Replay: someone else already spent this token. We cannot tell the
        # thief from the victim, so every live token in the family dies and
        # both parties must log in again.
        await session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == stored.family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        # Commit before raising. The session dependency rolls back on any
        # exception, which would silently discard this revocation and leave
        # the stolen session alive - the exact failure this code prevents.
        await session.commit()
        logger.warning(
            "refresh token replay detected; revoked family",
            extra={"user_id": stored.user_id, "family_id": stored.family_id},
        )
        raise InvalidTokenError("Refresh token is invalid or has been revoked.")
    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        raise InvalidTokenError("Refresh token has expired.")

    user = await session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("Account is inactive.")

    # Rotation: the presented token is consumed as the replacement is issued,
    # so a stolen refresh token is usable at most once.
    stored.revoked_at = now
    tokens = await _issue_tokens(session, user, family_id=stored.family_id)
    await session.flush()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(payload: RefreshRequest, session: SessionDep) -> None:
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(payload.refresh_token)
        )
    )
    stored = result.scalar_one_or_none()
    # Idempotent: logging out with an unknown token still succeeds.
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)


@router.get("/me", response_model=MeResponse)
async def me(ctx: CurrentUser, session: SessionDep) -> MeResponse:
    user = await session.get(User, ctx.user_id)
    assert user is not None  # guaranteed by get_current_context
    rows = await session.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == ctx.user_id)
        .order_by(Workspace.created_at)
    )
    workspaces = [
        WorkspaceOut(**WorkspaceOut.model_validate(ws).model_dump(exclude={"role"}), role=role)
        for ws, role in rows.all()
    ]
    return MeResponse(user=UserOut.model_validate(user), workspaces=workspaces)
