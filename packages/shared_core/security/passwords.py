"""Password hashing.

bcrypt with a per-password salt. ``verify_password`` never raises on a
malformed stored hash: a corrupt row must read as "wrong password", not as a
500 that tells an attacker the account is special.
"""

from __future__ import annotations

import logging

import bcrypt

logger = logging.getLogger(__name__)

# bcrypt truncates silently at 72 bytes; refusing longer input is clearer than
# accepting a password of which only the first 72 bytes matter.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8
DEFAULT_ROUNDS = 12


def hash_password(password: str, *, rounds: int = DEFAULT_ROUNDS) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:MAX_PASSWORD_BYTES], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        logger.warning("stored password hash is unreadable; treating as a failed login")
        return False


def needs_rehash(hashed: str, *, rounds: int = DEFAULT_ROUNDS) -> bool:
    """True when a stored hash uses a weaker cost than we now require."""
    try:
        cost = int(hashed.split("$")[2])
    except (IndexError, ValueError):
        return True
    return cost < rounds


__all__ = ["MIN_PASSWORD_LENGTH", "hash_password", "needs_rehash", "verify_password"]
