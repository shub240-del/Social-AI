"""Rate limiter enforcement.

The API E2E runs with the limits relaxed so it can exercise the product, which
means it never proves the limiter fires. These tests pin the actual behaviour.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.shared_core.config import get_settings
from packages.shared_core.middleware.core import RateLimitMiddleware


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """A minimal app carrying only the limiter, with tight limits."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "3")
    monkeypatch.setenv("RATE_LIMIT_CHAT_PER_MINUTE", "3")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MINUTE", "3")
    get_settings.cache_clear()

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    @app.get("/api/v1/auth/me")
    async def me():
        return {"ok": True}

    @app.post("/api/v1/workspaces/{ws}/chat")
    async def chat(ws: str):
        return {"ok": True}

    @app.get("/api/v1/workspaces")
    async def workspaces():
        return {"ok": True}

    with TestClient(app) as c:
        yield c

    get_settings.cache_clear()


def test_credential_endpoint_returns_429_after_limit(client: TestClient):
    codes = [client.post("/api/v1/auth/login").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3:] == [429, 429], codes


def test_429_body_uses_the_standard_error_envelope(client: TestClient):
    for _ in range(3):
        client.post("/api/v1/auth/login")
    res = client.post("/api/v1/auth/login")
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "rate_limited"
    assert int(res.headers["Retry-After"]) >= 1


def test_successful_responses_expose_remaining_budget(client: TestClient):
    res = client.get("/api/v1/workspaces")
    assert res.headers["X-RateLimit-Limit"] == "3"
    assert res.headers["X-RateLimit-Remaining"] == "2"


def test_health_endpoints_are_never_limited(client: TestClient):
    # Probes run far more often than any user; throttling them would take the
    # service out of its load balancer.
    assert all(client.get("/healthz").status_code == 200 for _ in range(20))


def test_auth_me_is_not_on_the_credential_bucket(client: TestClient):
    """Regression: /auth/me is called on every page load."""
    for _ in range(3):
        assert client.post("/api/v1/auth/login").status_code == 200
    assert client.post("/api/v1/auth/login").status_code == 429
    # The credential bucket is exhausted; ordinary authenticated calls survive.
    assert client.get("/api/v1/auth/me").status_code == 200


def test_buckets_do_not_share_a_counter_when_limits_are_equal(client: TestClient):
    """Regression: keying the bucket on the limit value merged the buckets."""
    for _ in range(3):
        assert client.post("/api/v1/auth/login").status_code == 200
    assert client.post("/api/v1/auth/login").status_code == 429

    # chat and default are configured to the same number but must be separate.
    assert client.post("/api/v1/workspaces/w1/chat").status_code == 200
    assert client.get("/api/v1/workspaces").status_code == 200


def test_chat_bucket_exhausts_independently(client: TestClient):
    for _ in range(3):
        assert client.post("/api/v1/workspaces/w1/chat").status_code == 200
    assert client.post("/api/v1/workspaces/w1/chat").status_code == 429
    # A different workspace shares the chat bucket (per client, not per resource).
    assert client.post("/api/v1/workspaces/w2/chat").status_code == 429
    # But the default bucket is untouched.
    assert client.get("/api/v1/workspaces").status_code == 200


def test_distinct_clients_get_distinct_budgets(client: TestClient):
    for _ in range(3):
        client.post("/api/v1/auth/login", headers={"X-Forwarded-For": "1.1.1.1"})
    assert (
        client.post("/api/v1/auth/login", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429
    )
    assert (
        client.post("/api/v1/auth/login", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200
    )


def test_limiter_can_be_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "1")
    get_settings.cache_clear()

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    with TestClient(app) as c:
        assert all(c.post("/api/v1/auth/login").status_code == 200 for _ in range(10))
    get_settings.cache_clear()
