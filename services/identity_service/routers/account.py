"""Email verification and password reset.

Both flows follow the same rules:

* tokens are random, stored only as a SHA-256 hash, single-use and expiring;
* responses never reveal whether an address is registered;
* completing a password reset revokes every refresh token the user holds,
  because the most likely reason for a reset is that the account was
  compromised.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, status
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared_core.config import get_settings
from packages.shared_core.db.models import RefreshToken, User, VerificationToken
from packages.shared_core.email.sender import Email, get_email_sender
from packages.shared_core.exceptions import InvalidTokenError, ValidationError
from packages.shared_core.security.passwords import hash_password, verify_password
from services.identity_service.auth.dependencies import CurrentUser, SessionDep
from services.identity_service.routing import CommitRoute
from services.identity_service.schemas import (
    MessageResponse,
    PasswordChangeRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    VerifyConfirmRequest,
    VerifyRequestRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["account"], route_class=CommitRoute)

PURPOSE_VERIFY = "email_verify"
PURPOSE_RESET = "password_reset"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _issue_token(session: AsyncSession, user: User, purpose: str, ttl_seconds: int) -> str:
    """Invalidate any outstanding token for this purpose, then mint a new one."""
    await session.execute(
        update(VerificationToken)
        .where(
            VerificationToken.user_id == user.id,
            VerificationToken.purpose == purpose,
            VerificationToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
    )
    raw = secrets.token_urlsafe(32)
    session.add(
        VerificationToken(
            user_id=user.id,
            token_hash=_hash(raw),
            purpose=purpose,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
    )
    return raw


async def _consume_token(session: AsyncSession, raw: str, purpose: str) -> User:
    result = await session.execute(
        select(VerificationToken).where(
            VerificationToken.token_hash == _hash(raw),
            VerificationToken.purpose == purpose,
        )
    )
    token = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if token is None:
        raise InvalidTokenError("This link is invalid or has already been used.")

    # Expiry is judged from the read so that an expired link can be reported
    # distinctly from an already-used one, which is a materially different
    # thing to tell a user.
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        raise InvalidTokenError("This link has expired. Please request a new one.")

    # Claim the token with a conditional UPDATE rather than trusting the
    # used_at just read. Read-then-write let the same link be redeemed twice:
    # between the SELECT and the write, another request on another worker could
    # redeem it, and the second caller still saw used_at IS NULL. The database
    # evaluates this predicate at write time, so exactly one caller can flip
    # NULL -> now and the loser gets rowcount 0.
    claimed = cast(
        "CursorResult[Any]",
        await session.execute(
            update(VerificationToken)
            .where(
                VerificationToken.token_hash == _hash(raw),
                VerificationToken.purpose == purpose,
                VerificationToken.used_at.is_(None),
            )
            .values(used_at=now)
        ),
    )
    if claimed.rowcount != 1:
        raise InvalidTokenError("This link is invalid or has already been used.")

    # Commit the claim immediately. Without this the claim lives in an open
    # transaction, and any later failure in this request would roll it back and
    # silently hand the link back out for reuse.
    await session.commit()

    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("This link is invalid or has already been used.")

    return user


async def send_verification_email(session: AsyncSession, user: User) -> None:
    """Mint a fresh verification link and email it.

    Shared with registration so that signing up actually delivers a link;
    without that, enabling REQUIRE_EMAIL_VERIFICATION would create accounts
    that can never log in.
    """
    settings = get_settings()
    raw = await _issue_token(session, user, PURPOSE_VERIFY, settings.email_verify_ttl_seconds)
    link = f"{settings.frontend_base_url.rstrip('/')}/verify?token={raw}"
    get_email_sender().send(
        Email(
            to=user.email,
            subject="Confirm your Social AI account",
            text=(
                f"Hi {user.full_name},\n\n"
                f"Confirm your account by opening this link:\n{link}\n\n"
                f"The link expires in "
                f"{settings.email_verify_ttl_seconds // 3600} hours.\n\n"
                "If you did not create a Social AI account you can ignore this email."
            ),
        )
    )


# ---- email verification ---------------------------------------------


@router.post("/verify/request", response_model=MessageResponse)
async def request_verification(
    payload: VerifyRequestRequest, session: SessionDep
) -> MessageResponse:
    result = await session.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()

    # Always the same response: this endpoint must not confirm which addresses
    # have accounts.
    if user is not None and user.email_verified_at is None:
        await send_verification_email(session, user)
    return MessageResponse(message="If that address needs verifying, an email is on its way.")


@router.post("/verify/confirm", response_model=MessageResponse)
async def confirm_verification(
    payload: VerifyConfirmRequest, session: SessionDep
) -> MessageResponse:
    user = await _consume_token(session, payload.token, PURPOSE_VERIFY)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    logger.info("email verified", extra={"user_id": user.id})
    return MessageResponse(message="Your email address is confirmed.")


# ---- password reset --------------------------------------------------


@router.post("/password/forgot", response_model=MessageResponse)
async def forgot_password(
    payload: PasswordForgotRequest, session: SessionDep
) -> MessageResponse:
    settings = get_settings()
    result = await session.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()

    if user is not None and user.is_active and user.hashed_password:
        raw = await _issue_token(
            session, user, PURPOSE_RESET, settings.password_reset_ttl_seconds
        )
        link = f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={raw}"
        get_email_sender().send(
            Email(
                to=user.email,
                subject="Reset your Social AI password",
                text=(
                    f"Hi {user.full_name},\n\n"
                    f"Reset your password here:\n{link}\n\n"
                    f"The link expires in "
                    f"{settings.password_reset_ttl_seconds // 60} minutes and can "
                    "be used once.\n\n"
                    "If you did not request this, ignore this email - your password "
                    "has not changed."
                ),
            )
        )
    return MessageResponse(message="If that account exists, a reset email is on its way.")


@router.post("/password/reset", response_model=MessageResponse)
async def reset_password(payload: PasswordResetRequest, session: SessionDep) -> MessageResponse:
    user = await _consume_token(session, payload.token, PURPOSE_RESET)
    user.hashed_password = hash_password(payload.new_password)

    # A reset usually means the account may be compromised, so every existing
    # session dies. Leaving them alive would let an attacker who already has a
    # refresh token keep access after the victim "recovers" the account.
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    logger.info("password reset; all sessions revoked", extra={"user_id": user.id})
    return MessageResponse(message="Your password has been changed. Please log in again.")


@router.post("/password/change", response_model=MessageResponse)
async def change_password(
    payload: PasswordChangeRequest,
    user: CurrentUser,
    session: SessionDep,
) -> MessageResponse:
    """Authenticated change. Revokes every session, including this one."""
    db_user = await session.get(User, user.user_id)
    if db_user is None or not db_user.hashed_password:
        raise ValidationError("This account has no password set.")
    if not verify_password(payload.current_password, db_user.hashed_password):
        raise InvalidTokenError("Current password is incorrect.")

    db_user.hashed_password = hash_password(payload.new_password)
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == db_user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return MessageResponse(message="Password changed. Please log in again.")


__all__ = ["router", "send_verification_email", "status"]
