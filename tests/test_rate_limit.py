"""Rate limiter enforcement.

The live journey runs with the limiter disabled so it can exercise the product,
which means it never proves the limiter fires. These tests pin the behaviour on
a minimal app carrying only the middleware.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.shared_core.config import get_settings
from packages.shared_core.middleware.core import RateLimitMiddleware


def _app() -> FastAPI:
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

    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """Every bucket set to the same tight limit.

    Equal limits are deliberate: it is the configuration that exposed the
    bucket-key collision described in the regression test below.
    """
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AUTH_RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    get_settings.cache_clear()

    with TestClient(_app()) as c:
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
    # service out of its load balancer exactly when it is busiest.
    assert all(client.get("/healthz").status_code == 200 for _ in range(20))


def test_auth_me_is_not_on_the_credential_bucket(client: TestClient):
    """/auth/me is called on every page load and must not be starved."""
    for _ in range(3):
        assert client.post("/api/v1/auth/login").status_code == 200
    assert client.post("/api/v1/auth/login").status_code == 429
    # The credential bucket is exhausted; ordinary authenticated calls survive.
    assert client.get("/api/v1/auth/me").status_code == 200


def test_buckets_do_not_share_a_counter_when_limits_are_equal(client: TestClient):
    """Regression: keying the bucket on the limit value merged the buckets.

    All three limits are 3 here, so a key of "<ip>:3" made one exhausted
    bucket lock every other route out.
    """
    for _ in range(3):
        assert client.post("/api/v1/auth/login").status_code == 200
    assert client.post("/api/v1/auth/login").status_code == 429

    assert client.post("/api/v1/workspaces/w1/chat").status_code == 200
    assert client.get("/api/v1/workspaces").status_code == 200


def test_chat_bucket_exhausts_independently(client: TestClient):
    for _ in range(3):
        assert client.post("/api/v1/workspaces/w1/chat").status_code == 200
    assert client.post("/api/v1/workspaces/w1/chat").status_code == 429
    # The bucket is per client, not per workspace: spending is the client's.
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


def test_preflight_is_never_limited(client: TestClient):
    """A blocked OPTIONS turns a rate limit into an opaque CORS failure."""
    for _ in range(3):
        client.post("/api/v1/auth/login")
    assert client.post("/api/v1/auth/login").status_code == 429
    assert client.options("/api/v1/auth/login").status_code != 429


def test_limiter_can_be_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("AUTH_RATE_LIMIT_PER_MINUTE", "1")
    get_settings.cache_clear()

    with TestClient(_app()) as c:
        assert all(c.post("/api/v1/auth/login").status_code == 200 for _ in range(10))
    get_settings.cache_clear()
