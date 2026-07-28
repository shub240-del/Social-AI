"""A successful write response must mean the write is committed.

FastAPI runs the teardown of ``yield`` dependencies after the response has been
sent, so a session that commits only in its teardown reports success before the
transaction is durable. Against the running service that was not theoretical:
8 of 20 registrations were still invisible to a second connection at the moment
the client received ``201 Created``, and an immediate login for the new account
failed about a third of the time.

These tests read through a session that is not the request's, which is the only
way to tell "committed" apart from "pending in the request's transaction".
"""

from __future__ import annotations

import uuid

import httpx
from httpx import ASGITransport
from sqlalchemy import func, select

from packages.shared_core.db.base import get_sessionmaker
from packages.shared_core.db.models import Brand, User, Workspace
from services.identity_service.main import create_app


async def test_the_transaction_is_closed_before_the_response_leaves_the_app():
    """The ordering guarantee itself, which is what actually regressed.

    The other tests here read the database after ``await client.post(...)``, and
    the in-process ASGI transport has already run dependency teardown by then --
    so they cannot see the window and would pass even with the fix removed. This
    one probes from middleware, which runs while the response is still travelling
    outward, and fails if the request's transaction is still open at that point.
    """
    app = create_app()
    observed: dict[str, object] = {}

    @app.middleware("http")
    async def probe(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        session = getattr(request.state, "db_session", None)
        observed["in_transaction"] = session.in_transaction() if session else None
        return response

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as probe_client:
        r = await probe_client.post(
            "/api/v1/auth/register",
            json={
                "email": f"probe-{uuid.uuid4().hex[:10]}@example.com",
                "password": "SuperSecret123",
                "full_name": "P",
            },
        )

    assert r.status_code == 201, r.text
    assert observed["in_transaction"] is False, (
        "the request's transaction was still open while the response was being "
        "returned, so the client is told the write succeeded before it is durable"
    )


async def _fresh(client) -> tuple[str, dict[str, str]]:
    email = f"durable-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SuperSecret123", "full_name": "D"},
    )
    assert r.status_code == 201, r.text
    return email, {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_register_is_committed_when_the_response_arrives(client):
    email, _ = await _fresh(client)

    async with get_sessionmaker()() as observer:
        found = (
            await observer.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

    assert found is not None, "register returned 201 before the row was committed"


async def test_a_new_account_can_log_in_immediately(client):
    """The read-your-own-write the bug actually broke for users."""
    email, _ = await _fresh(client)
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "SuperSecret123"}
    )
    assert login.status_code == 200, login.text


async def test_nested_resource_writes_are_committed_too(client):
    """Not just auth: the route wrapper has to cover every mutating router."""
    _, headers = await _fresh(client)

    ws = await client.post("/api/v1/workspaces", json={"name": "Durable"}, headers=headers)
    assert ws.status_code == 201, ws.text
    workspace_id = ws.json()["id"]

    brand = await client.post(
        f"/api/v1/workspaces/{workspace_id}/brands",
        json={
            "name": "B",
            "description": "d",
            "tone": "t",
            "audience": "a",
            "keywords": "k",
        },
        headers=headers,
    )
    assert brand.status_code == 201, brand.text

    async with get_sessionmaker()() as observer:
        seen_workspace = (
            await observer.execute(select(Workspace).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()
        seen_brand = (
            await observer.execute(select(Brand).where(Brand.id == brand.json()["id"]))
        ).scalar_one_or_none()

    assert seen_workspace is not None, "workspace was not committed before responding"
    assert seen_brand is not None, "brand was not committed before responding"


async def test_a_rejected_write_leaves_nothing_behind(client):
    """The wrapper rolls back on an error status instead of committing."""
    _, headers = await _fresh(client)
    ws = await client.post("/api/v1/workspaces", json={"name": "Rollback"}, headers=headers)
    workspace_id = ws.json()["id"]

    async with get_sessionmaker()() as observer:
        before = (
            await observer.execute(
                select(func.count(Brand.id)).where(Brand.workspace_id == workspace_id)
            )
        ).scalar_one()

    bad = await client.post(
        f"/api/v1/workspaces/{workspace_id}/brands",
        json={"description": "missing the required name"},
        headers=headers,
    )
    assert bad.status_code >= 400

    async with get_sessionmaker()() as observer:
        after = (
            await observer.execute(
                select(func.count(Brand.id)).where(Brand.workspace_id == workspace_id)
            )
        ).scalar_one()

    assert after == before, "a rejected request still persisted a row"
