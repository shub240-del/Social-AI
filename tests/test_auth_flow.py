"""The complete authentication journey, plus the ways it must fail."""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import auth_headers, register

PASSWORD = "SuperSecret123"


async def test_register_login_refresh_logout_login_again(client):
    """The full production journey the release checklist requires."""
    email, password, tokens = await register(client)
    assert tokens["access_token"] and tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"
    assert tokens["user"]["email"] == email

    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200
    assert len(me.json()["workspaces"]) == 1, "registration must create a starter workspace"

    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"], "token must rotate"

    out = await client.post(
        "/api/v1/auth/logout",
        headers=auth_headers(new_tokens),
        json={"refresh_token": new_tokens["refresh_token"]},
    )
    assert out.status_code == 200

    dead = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert dead.status_code == 401, "a logged-out session must not refresh"

    again = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert again.status_code == 200


async def test_refresh_token_replay_revokes_the_family(client):
    """The critical one: a stolen token must not outlive its detection."""
    _, _, tokens = await register(client)
    original = tokens["refresh_token"]

    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert first.status_code == 200
    descendant = first.json()["refresh_token"]

    # The attacker replays the token the victim already spent.
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401

    # ...which must also kill the legitimate descendant.
    victim = await client.post("/api/v1/auth/refresh", json={"refresh_token": descendant})
    assert victim.status_code == 401, "replay detection did not revoke the whole family"


async def test_duplicate_registration_is_rejected(client):
    email, _, _ = await register(client)
    again = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Impostor"},
    )
    assert again.status_code == 409


async def test_email_is_normalised(client):
    email = f"MiXeD-{uuid.uuid4().hex[:8]}@Example.COM"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Case Test"},
    )
    assert r.status_code == 201
    login = await client.post(
        "/api/v1/auth/login", json={"email": email.lower(), "password": PASSWORD}
    )
    assert login.status_code == 200


@pytest.mark.parametrize("password", ["short", "       ", "a" * 200])
async def test_weak_passwords_are_refused(client, password):
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"weak-{uuid.uuid4().hex[:8]}@example.com",
            "password": password,
            "full_name": "Weak",
        },
    )
    assert r.status_code == 422


async def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    email, _, _ = await register(client)
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "NotThePassword1"}
    )
    ghost = await client.post(
        "/api/v1/auth/login",
        json={"email": f"ghost-{uuid.uuid4().hex[:8]}@example.com", "password": "NotThePassword1"},
    )
    assert wrong.status_code == ghost.status_code == 401
    assert wrong.json() == ghost.json(), "login responses leak whether an account exists"


async def test_password_change_revokes_sessions(client):
    _, password, tokens = await register(client)
    r = await client.post(
        "/api/v1/auth/password/change",
        headers=auth_headers(tokens),
        json={"current_password": password, "new_password": "BrandNewSecret456"},
    )
    assert r.status_code == 200
    dead = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert dead.status_code == 401


async def test_password_change_requires_the_current_password(client):
    _, _, tokens = await register(client)
    r = await client.post(
        "/api/v1/auth/password/change",
        headers=auth_headers(tokens),
        json={"current_password": "WrongCurrent1", "new_password": "BrandNewSecret456"},
    )
    assert r.status_code == 401


async def test_me_requires_authentication(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Bearer not-a-token", "Bearer a.b.c", "Basic dXNlcjpwYXNz"],
)
async def test_malformed_authorization_headers_are_rejected(client, header):
    r = await client.get("/api/v1/auth/me", headers={"Authorization": header})
    assert r.status_code == 401


async def test_the_none_algorithm_is_rejected(client):
    """A token signed with alg=none must never be trusted."""
    import base64
    import json

    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    forged = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'someone', 'email': 'x@y.z'})}."
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_sessions_are_listed(client):
    _, _, tokens = await register(client)
    r = await client.get("/api/v1/auth/sessions", headers=auth_headers(tokens))
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_logout_everywhere_kills_every_session(client):
    email, password, first = await register(client)
    second = (
        await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    ).json()

    out = await client.post(
        "/api/v1/auth/logout", headers=auth_headers(second), json={"all_sessions": True}
    )
    assert out.status_code == 200

    for tokens in (first, second):
        dead = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert dead.status_code == 401
