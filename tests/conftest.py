"""Shared test fixtures.

The environment is configured *before* any application module is imported,
because ``get_settings`` is cached and the database engine is built from it.

Each test gets a real HTTP client speaking to the real app over ASGI — no
mocked routers — against a throwaway SQLite file. The only stubbed dependency
is the LLM, which must never make a paid network call from a test.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

# ---- environment (must precede application imports) --------------------
_DB_FILE = Path(tempfile.gettempdir()) / f"socialai-test-{uuid.uuid4().hex}.db"

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_DB_FILE}",
        "ALLOW_MOCK_LLM": "true",
        "EMAIL_BACKEND": "memory",
        "RATE_LIMIT_ENABLED": "false",   # suites issue hundreds of requests
        "REQUIRE_EMAIL_VERIFICATION": "false",
        "LOG_LEVEL": "WARNING",
        "FRONTEND_BASE_URL": "http://127.0.0.1:3000",
    }
)
os.environ.pop("NVIDIA_API_KEY", None)

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402

from packages.shared_core.config import get_settings  # noqa: E402
from packages.shared_core.db.base import Base, get_engine, reset_engine_for_tests  # noqa: E402
from packages.shared_core.email import sender as sender_mod  # noqa: E402
from services.identity_service.main import create_app  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture(autouse=True)
async def _database():
    """A clean schema per test, so ordering can never make one pass."""
    reset_engine_for_tests()
    get_settings.cache_clear()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_email():
    sender_mod.reset_email_sender()
    yield
    sender_mod.reset_email_sender()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", timeout=30
    ) as c:
        yield c


@pytest.fixture
async def db_session():
    """A session for tests that call service functions directly.

    Rolled back on teardown; the autouse ``_database`` fixture rebuilds the
    schema anyway, so this only keeps a failing test from leaving a half
    written transaction behind.
    """
    from packages.shared_core.db.base import get_sessionmaker

    async with get_sessionmaker()() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture
def mailbox() -> sender_mod.MemoryEmailSender:
    sender = sender_mod.get_email_sender()
    assert isinstance(sender, sender_mod.MemoryEmailSender)
    return sender


# ---- helpers -----------------------------------------------------------


async def register(client, *, email: str | None = None, password: str = "SuperSecret123"):
    """Register and return (email, password, tokens-dict)."""
    email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )
    assert response.status_code == 201, response.text
    return email, password, response.json()


def auth_headers(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def first_workspace(client, tokens: dict) -> str:
    response = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert response.status_code == 200, response.text
    return response.json()["workspaces"][0]["id"]


@pytest.fixture
def helpers():
    class Helpers:
        register = staticmethod(register)
        auth_headers = staticmethod(auth_headers)
        first_workspace = staticmethod(first_workspace)

    return Helpers
