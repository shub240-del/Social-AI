"""Password hashing.

bcrypt via passlib. bcrypt silently truncates input at 72 bytes, so longer
passwords are rejected explicitly rather than being quietly weakened.
"""

from __future__ import annotations

from passlib.context import CryptContext

from packages.shared_core.exceptions import ValidationError

_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            details={"field": "password"},
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValidationError(
            "Password must be at most 72 bytes.", details={"field": "password"}
        )


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return _ctx.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _ctx.verify(password, hashed)
    except ValueError:
        # Malformed/corrupt hash in the database must not 500 the login route.
        return False
