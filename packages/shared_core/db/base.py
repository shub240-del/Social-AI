"""Async engine, session factory and the declarative base.

The engine is created lazily so that importing a model never opens a socket —
that matters for Alembic, for tests, and for `--help` on a management command.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.requests import Request

from packages.shared_core.config import get_settings

# Explicit naming so Alembic autogenerate produces stable, reversible names for
# constraints instead of database-specific defaults.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKey:
    """String UUIDs keep one schema working on both SQLite and Postgres."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs(url: str) -> dict[str, Any]:
    settings = get_settings()
    if url.startswith("sqlite"):
        # SQLite has no server-side pool to size, and NullPool avoids
        # cross-event-loop reuse of a connection in tests.
        from sqlalchemy.pool import StaticPool

        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        return kwargs
    return {
        "pool_size": settings.postgres_pool_size,
        "max_overflow": settings.postgres_max_overflow,
        "pool_pre_ping": True,   # a pooler can drop an idle connection silently
        "pool_recycle": 1800,
    }


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        _engine = create_async_engine(url, echo=settings.db_echo, future=True, **_engine_kwargs(url))
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,  # attributes stay readable after commit
            autoflush=False,
        )
    return _sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one transaction per request.

    The session is published on ``request.state`` so that
    :class:`~services.identity_service.routing.CommitRoute` can commit it while
    the request is still in flight. Since FastAPI 0.106 the teardown below runs
    *after* the response has been sent, so committing only here meant the API
    answered ``201 Created`` before the row was durable -- a caller that
    immediately read its own write could miss it, and a commit that failed left
    the client holding a success it never got.

    The commit below is kept as a safety net for anything the route wrapper did
    not already flush; committing an already-committed session is a no-op.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        request.state.db_session = session
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def reset_engine_for_tests() -> None:
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


__all__ = [
    "Base",
    "Timestamps",
    "UUIDPrimaryKey",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "new_uuid",
    "reset_engine_for_tests",
    "utcnow",
]
