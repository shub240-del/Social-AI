"""Email verification and password reset.

The console email backend records what would have been sent, so the flows are
testable end to end without an SMTP provider.
"""

from __future__ import annotations

import re
import uuid

import pytest

from packages.shared_core.config import get_settings
from packages.shared_core.email import sender as sender_mod

PASSWORD = "SuperSecret123"
NEW_PASSWORD = "EvenBetterSecret456"


class Recorder(sender_mod.EmailSender):
    def __init__(self) -> None:
        self.sent: list[sender_mod.Email] = []

    def send(self, message: sender_mod.Email) -> None:
        self.sent.append(message)

    def link_for(self, to: str) -> str | None:
        for m in reversed(self.sent):
            if m.to == to:
                found = re.search(r"token=([A-Za-z0-9_\-]+)", m.text)
                return found.group(1) if found else None
        return None


@pytest.fixture
def mail(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()
    monkeypatch.setattr(sender_mod, "get_email_sender", lambda: rec)
    # The router imported the symbol directly.
    import services.identity_service.routers.account as account_mod

    monkeypatch.setattr(account_mod, "get_email_sender", lambda: rec)
    return rec


async def _register(client, email: str | None = None) -> str:
    email = email or f"acct-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Acct User"},
    )
    assert r.status_code == 201, r.text
    return email


# ---- email verification ---------------------------------------------


async def test_verification_email_contains_a_working_link(client, mail):
    email = await _register(client)
    r = await client.post("/api/v1/auth/verify/request", json={"email": email})
    assert r.status_code == 200
    token = mail.link_for(email)
    assert token, "no verification link was sent"

    confirm = await client.post("/api/v1/auth/verify/confirm", json={"token": token})
    assert confirm.status_code == 200, confirm.text


async def test_verification_token_is_single_use(client, mail):
    email = await _register(client)
    await client.post("/api/v1/auth/verify/request", json={"email": email})
    token = mail.link_for(email)
    first = await client.post("/api/v1/auth/verify/confirm", json={"token": token})
    assert first.status_code == 200
    again = await client.post("/api/v1/auth/verify/confirm", json={"token": token})
    assert again.status_code == 401


async def test_requesting_again_invalidates_the_previous_link(client, mail):
    email = await _register(client)
    await client.post("/api/v1/auth/verify/request", json={"email": email})
    first = mail.link_for(email)
    await client.post("/api/v1/auth/verify/request", json={"email": email})
    second = mail.link_for(email)
    assert first != second

    stale = await client.post("/api/v1/auth/verify/confirm", json={"token": first})
    assert stale.status_code == 401
    fresh = await client.post("/api/v1/auth/verify/confirm", json={"token": second})
    assert fresh.status_code == 200


async def test_verify_request_does_not_enumerate_users(client, mail):
    known = await _register(client)
    a = await client.post("/api/v1/auth/verify/request", json={"email": known})
    b = await client.post(
        "/api/v1/auth/verify/request",
        json={"email": f"ghost-{uuid.uuid4().hex[:8]}@example.com"},
    )
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert mail.link_for("ghost") is None


async def test_garbage_verification_token_rejected(client):
    r = await client.post("/api/v1/auth/verify/confirm", json={"token": "x" * 40})
    assert r.status_code == 401


# ---- login gating ----------------------------------------------------


async def test_login_blocked_when_verification_required(client, mail, monkeypatch):
    email = await _register(client)
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "true")
    get_settings.cache_clear()
    try:
        blocked = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert blocked.status_code == 401
        assert blocked.json()["error"]["code"] == "email_not_verified"

        await client.post("/api/v1/auth/verify/request", json={"email": email})
        await client.post(
            "/api/v1/auth/verify/confirm", json={"token": mail.link_for(email)}
        )

        ok = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert ok.status_code == 200, ok.text
    finally:
        monkeypatch.delenv("REQUIRE_EMAIL_VERIFICATION", raising=False)
        get_settings.cache_clear()


async def test_login_allowed_when_verification_not_required(client):
    email = await _register(client)
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200


# ---- password reset --------------------------------------------------


async def test_password_reset_end_to_end(client, mail):
    email = await _register(client)
    r = await client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert r.status_code == 200
    token = mail.link_for(email)
    assert token, "no reset link was sent"

    reset = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert reset.status_code == 200, reset.text

    old = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert old.status_code == 401, "the old password still works"

    new = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD}
    )
    assert new.status_code == 200, new.text


async def test_reset_revokes_every_existing_session(client, mail):
    """A reset usually means compromise; live sessions must not survive it."""
    email = await _register(client)
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    refresh_token = login.json()["refresh_token"]

    await client.post("/api/v1/auth/password/forgot", json={"email": email})
    await client.post(
        "/api/v1/auth/password/reset",
        json={"token": mail.link_for(email), "new_password": NEW_PASSWORD},
    )

    still = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert still.status_code == 401, "a pre-reset session survived the password reset"


async def test_reset_token_is_single_use(client, mail):
    email = await _register(client)
    await client.post("/api/v1/auth/password/forgot", json={"email": email})
    token = mail.link_for(email)
    first = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "ThirdPassword789"}
    )
    assert second.status_code == 401


async def test_forgot_password_does_not_enumerate_users(client, mail):
    known = await _register(client)
    a = await client.post("/api/v1/auth/password/forgot", json={"email": known})
    b = await client.post(
        "/api/v1/auth/password/forgot",
        json={"email": f"ghost-{uuid.uuid4().hex[:8]}@example.com"},
    )
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()


async def test_reset_rejects_a_weak_new_password(client, mail):
    email = await _register(client)
    await client.post("/api/v1/auth/password/forgot", json={"email": email})
    r = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": mail.link_for(email), "new_password": "short"},
    )
    assert r.status_code == 422


async def test_a_verify_token_cannot_be_used_to_reset_a_password(client, mail):
    """Purposes must not be interchangeable."""
    email = await _register(client)
    await client.post("/api/v1/auth/verify/request", json={"email": email})
    verify_token = mail.link_for(email)

    r = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": verify_token, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 401, "a verification token was accepted as a reset token"


async def test_registration_sends_the_verification_link_unprompted(client, mail):
    """Signing up must deliver a link; otherwise turning on
    REQUIRE_EMAIL_VERIFICATION creates accounts nobody can log into."""
    email = await _register(client)
    token = mail.link_for(email)
    assert token, "registering did not send a verification email"

    r = await client.post("/api/v1/auth/verify/confirm", json={"token": token})
    assert r.status_code == 200, r.text


async def test_registration_still_succeeds_if_email_delivery_fails(client, monkeypatch):
    """A dead SMTP provider must not cost us the signup."""
    import services.identity_service.routers.account as account_mod

    class Broken(sender_mod.EmailSender):
        def send(self, message: sender_mod.Email) -> None:
            raise RuntimeError("smtp is down")

    monkeypatch.setattr(account_mod, "get_email_sender", lambda: Broken())
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"resilient-{uuid.uuid4().hex[:8]}@example.com",
            "password": PASSWORD,
            "full_name": "Resilient User",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["access_token"]
