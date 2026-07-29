"""Token verification deny paths.

These are the branches the original codebase never executed
(jwt_validator.py:46-61 and the auth middleware rejection blocks).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from packages.shared_core.config import get_settings
from services.identity_service.auth.tokens import (
    create_access_token,
    decode_access_token,
    get_keys,
)
from tests.conftest import register

ME = "/api/v1/auth/me"


def _claims(**overrides) -> dict:
    s = get_settings()
    now = datetime.now(UTC)
    base = {
        "sub": str(uuid.uuid4()),
        "email": "x@example.com",
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "typ": "access",
    }
    base.update(overrides)
    return base


def _sign(claims: dict) -> str:
    private, _ = get_keys()
    return jwt.encode(claims, private, algorithm="RS256")


# ---- unit level ------------------------------------------------------


def test_expired_token_rejected():
    from packages.shared_core.exceptions import TokenExpiredError

    past = datetime.now(UTC) - timedelta(hours=1)
    token = _sign(
        _claims(
            exp=int(past.timestamp()),
            iat=int((past - timedelta(minutes=5)).timestamp()),
        )
    )
    with pytest.raises(TokenExpiredError):
        decode_access_token(token)


def test_wrong_audience_rejected():
    from packages.shared_core.exceptions import InvalidTokenError

    with pytest.raises(InvalidTokenError):
        decode_access_token(_sign(_claims(aud="https://evil.example.com")))


def test_wrong_issuer_rejected():
    from packages.shared_core.exceptions import InvalidTokenError

    with pytest.raises(InvalidTokenError):
        decode_access_token(_sign(_claims(iss="https://evil.example.com")))


def test_alg_none_rejected():
    """The classic JWT bypass: unsigned token declaring alg=none."""
    from packages.shared_core.exceptions import InvalidTokenError

    token = jwt.encode(_claims(), key="", algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_token_signed_by_foreign_key_rejected():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from packages.shared_core.exceptions import InvalidTokenError

    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = attacker.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    token = jwt.encode(_claims(), pem, algorithm="RS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_tampered_payload_rejected():
    from packages.shared_core.exceptions import InvalidTokenError

    token = create_access_token(user_id="abc", email="a@b.com")
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload[:-4]}AAAA.{sig}"
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_refresh_token_not_accepted_as_access_token():
    from packages.shared_core.exceptions import InvalidTokenError

    with pytest.raises(InvalidTokenError):
        decode_access_token(_sign(_claims(typ="refresh")))


def test_missing_required_claim_rejected():
    from packages.shared_core.exceptions import InvalidTokenError

    claims = _claims()
    del claims["sub"]
    with pytest.raises(InvalidTokenError):
        decode_access_token(_sign(claims))


# ---- HTTP level ------------------------------------------------------


async def test_missing_authorization_header(client):
    r = await client.get(ME)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


async def test_malformed_authorization_header(client):
    for value in ("", "Bearer", "Basic abc123", "Bearer   ", "NotBearer xyz"):
        r = await client.get(ME, headers={"Authorization": value})
        assert r.status_code == 401, f"{value!r} -> {r.status_code}"


async def test_garbage_token(client):
    r = await client.get(ME, headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_token"


async def test_token_for_deleted_user_rejected(client):
    """A cryptographically valid token for a nonexistent user must fail."""
    token = create_access_token(user_id=str(uuid.uuid4()), email="ghost@example.com")
    r = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_error_envelope_shape(client):
    r = await client.get(ME)
    body = r.json()
    assert set(body.keys()) == {"error"}
    assert {"code", "message"} <= set(body["error"].keys())


async def test_password_is_never_returned(client):
    user = await register(client)
    r = await client.get(ME, headers=user["headers"])
    assert "password" not in r.text.lower()
    assert "hashed" not in r.text.lower()


async def test_login_does_not_reveal_whether_email_exists(client):
    user = await register(client)
    wrong_pw = await client.post(
        "/api/v1/auth/login", json={"email": user["email"], "password": "WrongPassword1"}
    )
    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody-here@example.com", "password": "WrongPassword1"},
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


async def test_weak_password_rejected(client):
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": f"w-{uuid.uuid4().hex[:8]}@example.com", "password": "short"},
    )
    assert r.status_code == 422


async def test_refresh_rotation_invalidates_old_token(client):
    user = await register(client)
    first = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]}
    )
    assert first.status_code == 200
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]}
    )
    assert replay.status_code == 401


async def test_logout_revokes_refresh_token(client):
    user = await register(client)
    out = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": user["refresh_token"]}
    )
    assert out.status_code == 204
    after = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]}
    )
    assert after.status_code == 401


# ---- refresh token replay detection (OAuth 2.0 Security BCP) ---------
#
# Regression: rotation consumed the presented token but there was no family
# link, so a stolen token could be rotated once and the thief's descendant
# stayed valid indefinitely while the victim noticed nothing.


async def test_rotation_chain_works_repeatedly(client):
    user = await register(client)
    token = user["refresh_token"]
    for _ in range(3):
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert r.status_code == 200, r.text
        token = r.json()["refresh_token"]


async def test_replay_revokes_the_entire_family(client):
    user = await register(client)
    stolen = user["refresh_token"]

    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    assert first.status_code == 200
    descendant = first.json()["refresh_token"]

    # The victim (or the thief) presents the already-consumed token.
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    assert replay.status_code == 401

    # The descendant must now be dead too, or the stolen session survives.
    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": descendant})
    assert after.status_code == 401, "descendant token survived a detected replay"


async def test_family_revocation_does_not_affect_other_sessions(client):
    """Revoking one compromised family must not log the user out everywhere else."""
    user = await register(client)

    second = await client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": "SuperSecret123"},
    )
    assert second.status_code == 200
    other_session = second.json()["refresh_token"]

    stolen = user["refresh_token"]
    await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})  # replay

    still_good = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": other_session}
    )
    assert still_good.status_code == 200, "unrelated session was revoked"


async def test_dev_keypair_is_shared_between_worker_processes():
    """A per-process key fails ~half of all requests under --workers 2.

    Regression guard: the journey suite caught this as random
    "Signature verification failed" errors once gunicorn ran two workers.
    """
    from services.identity_service.auth import tokens as tok

    tok.reset_keys_for_tests()
    first = tok.get_keys()

    # Simulate a second worker: fresh process-local cache, same machine.
    tok._keys = None
    second = tok.get_keys()

    assert first[0] == second[0], "each worker generated its own signing key"
    assert first[1] == second[1]

    tok.reset_keys_for_tests()


async def test_configured_keys_take_priority_over_the_dev_cache(monkeypatch):
    from packages.shared_core.config import get_settings
    from services.identity_service.auth import tokens as tok

    private, public = tok._generate_keypair()
    monkeypatch.setenv("JWT_PRIVATE_KEY", private)
    monkeypatch.setenv("JWT_PUBLIC_KEY", public)
    get_settings.cache_clear()
    tok.reset_keys_for_tests()
    try:
        assert tok.get_keys()[0] == private
        assert not tok._dev_key_path().exists(), "wrote a dev cache despite configured keys"
    finally:
        get_settings.cache_clear()
        tok.reset_keys_for_tests()
