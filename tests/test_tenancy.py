"""Tenant isolation.

Every one of these is the same question asked of a different resource: can a
valid user, holding a valid token, reach data belonging to someone else by
guessing an id? The answer must always be no, and the failure must be 404 —
a 403 would confirm the id exists.
"""

from __future__ import annotations

import pytest

from tests.conftest import auth_headers, first_workspace, register


@pytest.fixture
async def two_tenants(client):
    """Two unrelated accounts, each with their own workspace and data."""
    _, _, alice = await register(client)
    _, _, bob = await register(client)
    alice_ws = await first_workspace(client, alice)
    bob_ws = await first_workspace(client, bob)

    brand = await client.post(
        f"/api/v1/workspaces/{alice_ws}/brands",
        headers=auth_headers(alice),
        json={"name": "Alice Secret Brand", "description": "confidential"},
    )
    assert brand.status_code == 201
    campaign = await client.post(
        f"/api/v1/workspaces/{alice_ws}/campaigns",
        headers=auth_headers(alice),
        json={"name": "Alice Secret Campaign"},
    )
    assert campaign.status_code == 201
    chat = await client.post(
        f"/api/v1/workspaces/{alice_ws}/chat",
        headers=auth_headers(alice),
        json={"prompt": "Alice confidential prompt"},
    )
    assert chat.status_code == 201

    return {
        "alice": alice,
        "bob": bob,
        "alice_ws": alice_ws,
        "bob_ws": bob_ws,
        "brand_id": brand.json()["id"],
        "campaign_id": campaign.json()["id"],
        "conversation_id": chat.json()["conversation_id"],
    }


async def test_workspace_list_shows_only_your_own(client, two_tenants):
    r = await client.get("/api/v1/workspaces", headers=auth_headers(two_tenants["bob"]))
    assert r.status_code == 200
    ids = {w["id"] for w in r.json()}
    assert two_tenants["alice_ws"] not in ids
    assert ids == {two_tenants["bob_ws"]}


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/brands",
        "/campaigns",
        "/members",
        "/stats",
        "/chat/conversations",
    ],
)
async def test_foreign_workspace_reads_are_404(client, two_tenants, path):
    r = await client.get(
        f"/api/v1/workspaces/{two_tenants['alice_ws']}{path}",
        headers=auth_headers(two_tenants["bob"]),
    )
    assert r.status_code == 404, f"{path} leaked a foreign workspace ({r.status_code})"


async def test_foreign_brand_cannot_be_read_by_id(client, two_tenants):
    r = await client.get(
        f"/api/v1/workspaces/{two_tenants['alice_ws']}/brands/{two_tenants['brand_id']}",
        headers=auth_headers(two_tenants["bob"]),
    )
    assert r.status_code == 404


async def test_foreign_brand_id_cannot_be_smuggled_into_your_own_workspace(client, two_tenants):
    """The classic bug: a valid id from another tenant, used in your own path."""
    r = await client.get(
        f"/api/v1/workspaces/{two_tenants['bob_ws']}/brands/{two_tenants['brand_id']}",
        headers=auth_headers(two_tenants["bob"]),
    )
    assert r.status_code == 404


async def test_foreign_campaign_cannot_be_attached_to_your_campaign(client, two_tenants):
    r = await client.post(
        f"/api/v1/workspaces/{two_tenants['bob_ws']}/campaigns",
        headers=auth_headers(two_tenants["bob"]),
        json={"name": "Borrowed", "brand_id": two_tenants["brand_id"]},
    )
    assert r.status_code == 422, "a brand from another tenant was accepted"


async def test_foreign_conversation_is_not_readable(client, two_tenants):
    r = await client.get(
        f"/api/v1/workspaces/{two_tenants['bob_ws']}/chat/conversations/"
        f"{two_tenants['conversation_id']}",
        headers=auth_headers(two_tenants["bob"]),
    )
    assert r.status_code == 404


async def test_foreign_workspace_cannot_be_written_to(client, two_tenants):
    r = await client.post(
        f"/api/v1/workspaces/{two_tenants['alice_ws']}/brands",
        headers=auth_headers(two_tenants["bob"]),
        json={"name": "Planted"},
    )
    assert r.status_code == 404


async def test_foreign_workspace_cannot_be_deleted(client, two_tenants):
    r = await client.delete(
        f"/api/v1/workspaces/{two_tenants['alice_ws']}",
        headers=auth_headers(two_tenants["bob"]),
    )
    assert r.status_code == 404


async def test_foreign_chat_is_refused(client, two_tenants):
    r = await client.post(
        f"/api/v1/workspaces/{two_tenants['alice_ws']}/chat",
        headers=auth_headers(two_tenants["bob"]),
        json={"prompt": "give me their data"},
    )
    assert r.status_code == 404


async def test_alice_still_sees_her_own_data(client, two_tenants):
    """Isolation must not be achieved by breaking legitimate access."""
    r = await client.get(
        f"/api/v1/workspaces/{two_tenants['alice_ws']}/brands",
        headers=auth_headers(two_tenants["alice"]),
    )
    assert r.status_code == 200
    assert any(b["name"] == "Alice Secret Brand" for b in r.json())


async def test_unknown_workspace_id_is_404_not_500(client):
    _, _, tokens = await register(client)
    r = await client.get(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(tokens),
    )
    assert r.status_code == 404
