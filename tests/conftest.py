from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

# Configure the environment before any application module is imported.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:////tmp/socialai_test_{uuid.uuid4().hex}.db"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ.pop("NVIDIA_API_KEY", None)

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402

from packages.shared_core.config import get_settings  # noqa: E402
from packages.shared_core.db import models  # noqa: E402,F401
from packages.shared_core.db.base import Base, get_engine  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema():
    get_settings.cache_clear()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A rolled-back session, so tests never leak rows into each other."""
    from packages.shared_core.db.base import get_sessionmaker

    async with get_sessionmaker()() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from services.identity_service.main import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register(client: httpx.AsyncClient, email: str | None = None) -> dict:
    """Create a user and return tokens plus their default workspace id."""
    email = email or f"u-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SuperSecret123", "full_name": "Test User"},
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return {
        "email": email,
        "headers": headers,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "workspace_id": me.json()["workspaces"][0]["id"],
        "user_id": me.json()["user"]["id"],
    }
