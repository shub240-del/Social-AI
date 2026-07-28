"""RS256 token issuance and verification.

Asymmetric signing is used so verification never needs the private key. In
development a keypair is generated on first boot; production must supply
JWT_PRIVATE_KEY / JWT_PUBLIC_KEY.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from packages.shared_core.config import Settings, get_settings
from packages.shared_core.exceptions import InvalidTokenError, TokenExpiredError

logger = logging.getLogger(__name__)

_keys: tuple[str, str] | None = None


def _generate_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public


def _dev_key_path() -> Path:
    """Where the shared development keypair lives."""
    return Path(tempfile.gettempdir()) / "socialai-dev-jwt.pem"


def _load_or_create_dev_keys() -> tuple[str, str]:
    """Share one generated keypair across every worker process.

    A per-process keypair looks fine with a single worker and then fails
    roughly half of all requests under `--workers 2`, because a token signed
    by one worker cannot be verified by another. Caching to disk keeps the
    convenience of zero-config development without that trap.
    """
    path = _dev_key_path()
    if path.exists():
        try:
            private = path.read_text()
            public = (
                serialization.load_pem_private_key(private.encode(), password=None)
                .public_key()
                .public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                .decode()
            )
            return private, public
        except Exception:  # noqa: BLE001 - a corrupt cache must not be fatal
            logger.warning("development JWT cache at %s is unreadable; regenerating", path)

    private, public = _generate_keypair()
    try:
        # O_EXCL so that concurrently starting workers agree on one winner.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return _load_or_create_dev_keys()  # another worker won the race
    except OSError:
        logger.warning("could not cache the development JWT key; workers may disagree")
        return private, public
    with os.fdopen(fd, "w") as handle:
        handle.write(private)
    return private, public


def get_keys(settings: Settings | None = None) -> tuple[str, str]:
    global _keys
    settings = settings or get_settings()
    if settings.jwt_private_key and settings.jwt_public_key:
        return (
            settings.jwt_private_key.replace("\\n", "\n"),
            settings.jwt_public_key.replace("\\n", "\n"),
        )
    if _keys is None:
        if settings.is_production:
            # Unreachable: Settings rejects this in production. Defence in depth.
            raise RuntimeError("JWT keys must be configured in production.")
        logger.warning(
            "No JWT keypair configured; using the shared development key at %s. "
            "Development only - set JWT_PRIVATE_KEY/JWT_PUBLIC_KEY for anything real.",
            _dev_key_path(),
        )
        _keys = _load_or_create_dev_keys()
    return _keys


def reset_keys_for_tests() -> None:
    global _keys
    _keys = None
    _dev_key_path().unlink(missing_ok=True)


def create_access_token(
    *, user_id: str, email: str, extra: dict[str, Any] | None = None
) -> str:
    settings = get_settings()
    private, _ = get_keys(settings)
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, private, algorithm="RS256")


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    _, public = get_keys(settings)
    try:
        claims = jwt.decode(
            token,
            public,
            algorithms=["RS256"],          # never trust the token's own alg header
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.InvalidTokenError as exc:
        # Covers bad signature, wrong aud/iss, malformed, and alg=none.
        raise InvalidTokenError(f"Token rejected: {exc}") from exc

    if claims.get("typ") != "access":
        raise InvalidTokenError("Expected an access token.")
    return claims


# ---- refresh tokens --------------------------------------------------
# Opaque random strings. Only their SHA-256 hash is persisted, so a database
# disclosure does not yield usable refresh tokens.


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
