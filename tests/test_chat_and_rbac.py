"""Chat persistence, conversation history and role enforcement."""

from __future__ import annotations

import pytest

from packages.shared_core.ai import ChatMessage, MockLLMClient
from packages.shared_core.security.rbac import (
    Permission,
    Role,
    has_permission,
    outranks,
    parse_role,
)
from tests.conftest import auth_headers, first_workspace, register

# ---- chat ---------------------------------------------------------------


async def test_chat_creates_a_conversation_and_persists_both_turns(client):
    _, _, tokens = await register(client)
    ws = await first_workspace(client, tokens)

    r = await client.post(
        f"/api/v1/workspaces/{ws}/chat",
        headers=auth_headers(tokens),
        json={"prompt": "Write a launch tweet for a coffee brand."},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"]

    detail = await client.get(
        f"/api/v1/workspaces/{ws}/chat/conversations/{body['conversation_id']}",
        headers=auth_headers(tokens),
    )
    assert detail.status_code == 200
    messages = detail.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["sequence"] < messages[1]["sequence"]


async def test_history_accumulates_in_order_across_turns(client):
    _, _, tokens = await register(client)
    ws = await first_workspace(client, tokens)

    first = await client.post(
        f"/api/v1/workspaces/{ws}/chat", headers=auth_headers(tokens), json={"prompt": "One"}
    )
    conversation_id = first.json()["conversation_id"]

    for prompt in ("Two", "Three"):
        follow = await client.post(
            f"/api/v1/workspaces/{ws}/chat",
            headers=auth_headers(tokens),
            json={"prompt": prompt, "conversation_id": conversation_id},
        )
        assert follow.status_code == 201
        assert follow.json()["conversation_id"] == conversation_id

    detail = await client.get(
        f"/api/v1/workspaces/{ws}/chat/conversations/{conversation_id}",
        headers=auth_headers(tokens),
    )
    messages = detail.json()["messages"]
    assert len(messages) == 6
    assert [m["content"] for m in messages if m["role"] == "user"] == ["One", "Two", "Three"]
    assert [m["sequence"] for m in messages] == sorted(m["sequence"] for m in messages)


async def test_conversation_survives_a_new_login(client):
    """Persistence across sessions - the journey's final step."""
    email, password, tokens = await register(client)
    ws = await first_workspace(client, tokens)
    created = await client.post(
        f"/api/v1/workspaces/{ws}/chat",
        headers=auth_headers(tokens),
        json={"prompt": "Remember me"},
    )
    conversation_id = created.json()["conversation_id"]

    fresh = (
        await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    ).json()

    listed = await client.get(
        f"/api/v1/workspaces/{ws}/chat/conversations", headers=auth_headers(fresh)
    )
    assert listed.status_code == 200
    assert any(c["id"] == conversation_id for c in listed.json())


async def test_conversation_list_reports_message_counts(client):
    _, _, tokens = await register(client)
    ws = await first_workspace(client, tokens)
    await client.post(
        f"/api/v1/workspaces/{ws}/chat", headers=auth_headers(tokens), json={"prompt": "Hello"}
    )
    listed = await client.get(
        f"/api/v1/workspaces/{ws}/chat/conversations", headers=auth_headers(tokens)
    )
    assert listed.json()[0]["message_count"] == 2


async def test_conversation_can_be_deleted(client):
    _, _, tokens = await register(client)
    ws = await first_workspace(client, tokens)
    created = await client.post(
        f"/api/v1/workspaces/{ws}/chat", headers=auth_headers(tokens), json={"prompt": "Delete me"}
    )
    conversation_id = created.json()["conversation_id"]

    removed = await client.delete(
        f"/api/v1/workspaces/{ws}/chat/conversations/{conversation_id}",
        headers=auth_headers(tokens),
    )
    assert removed.status_code == 200
    gone = await client.get(
        f"/api/v1/workspaces/{ws}/chat/conversations/{conversation_id}",
        headers=auth_headers(tokens),
    )
    assert gone.status_code == 404


async def test_chat_uses_brand_context_without_failing(client):
    _, _, tokens = await register(client)
    ws = await first_workspace(client, tokens)
    brands = await client.get(f"/api/v1/workspaces/{ws}/brands", headers=auth_headers(tokens))
    brand_id = brands.json()[0]["id"]

    r = await client.post(
        f"/api/v1/workspaces/{ws}/chat",
        headers=auth_headers(tokens),
        json={"prompt": "Announce our new roast.", "brand_id": brand_id},
    )
    assert r.status_code == 201


async def test_the_mock_provider_is_clearly_labelled(client):
    """Production asserts the opposite; the label is what makes that possible."""
    _, _, tokens = await register(client)
    ws = await first_workspace(client, tokens)
    r = await client.post(
        f"/api/v1/workspaces/{ws}/chat", headers=auth_headers(tokens), json={"prompt": "Hi"}
    )
    assert r.json()["provider"] == "mock"
    assert "mock" in r.json()["message"]["content"].lower()


async def test_mock_client_is_awaitable_and_streams():
    client_ = MockLLMClient()
    completion = await client_.complete([ChatMessage(role="user", content="hello")])
    assert completion.content
    assert completion.total_tokens > 0

    chunks = [chunk async for chunk in client_.stream([ChatMessage(role="user", content="hi")])]
    assert "".join(chunks).strip()


# ---- rbac ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (Role.VIEWER, Permission.CHAT_READ, True),
        (Role.VIEWER, Permission.CHAT_WRITE, False),
        (Role.VIEWER, Permission.BRAND_WRITE, False),
        (Role.MEMBER, Permission.CHAT_WRITE, True),
        (Role.MEMBER, Permission.BRAND_WRITE, False),
        (Role.EDITOR, Permission.BRAND_WRITE, True),
        (Role.EDITOR, Permission.MEMBER_INVITE, False),
        (Role.ADMIN, Permission.MEMBER_INVITE, True),
        (Role.ADMIN, Permission.WORKSPACE_DELETE, False),
        (Role.OWNER, Permission.WORKSPACE_DELETE, True),
    ],
)
def test_role_permission_matrix(role, permission, allowed):
    assert has_permission(role, permission) is allowed


def test_an_unknown_role_fails_closed():
    assert parse_role("superadmin") is Role.VIEWER
    assert not has_permission("superadmin", Permission.WORKSPACE_DELETE)


def test_role_ranking():
    assert outranks(Role.OWNER, Role.ADMIN)
    assert not outranks(Role.ADMIN, Role.OWNER)
    assert not outranks(Role.MEMBER, Role.MEMBER)


async def test_a_viewer_cannot_write_but_can_read(client):
    _, _, owner = await register(client)
    viewer_email, viewer_password, viewer = await register(client)
    ws = await first_workspace(client, owner)

    invited = await client.post(
        f"/api/v1/workspaces/{ws}/members",
        headers=auth_headers(owner),
        json={"email": viewer_email, "role": "viewer"},
    )
    assert invited.status_code == 201

    readable = await client.get(f"/api/v1/workspaces/{ws}/brands", headers=auth_headers(viewer))
    assert readable.status_code == 200

    blocked = await client.post(
        f"/api/v1/workspaces/{ws}/brands", headers=auth_headers(viewer), json={"name": "Nope"}
    )
    assert blocked.status_code == 403

    no_chat = await client.post(
        f"/api/v1/workspaces/{ws}/chat", headers=auth_headers(viewer), json={"prompt": "hi"}
    )
    assert no_chat.status_code == 403


async def test_a_member_cannot_invite_others(client):
    _, _, owner = await register(client)
    member_email, _, member = await register(client)
    ws = await first_workspace(client, owner)
    await client.post(
        f"/api/v1/workspaces/{ws}/members",
        headers=auth_headers(owner),
        json={"email": member_email, "role": "member"},
    )
    r = await client.post(
        f"/api/v1/workspaces/{ws}/members",
        headers=auth_headers(member),
        json={"email": "someone@example.com", "role": "member"},
    )
    assert r.status_code == 403


async def test_the_owner_cannot_be_removed(client):
    _, _, owner = await register(client)
    ws = await first_workspace(client, owner)
    me = (await client.get("/api/v1/auth/me", headers=auth_headers(owner))).json()
    r = await client.delete(
        f"/api/v1/workspaces/{ws}/members/{me['id']}", headers=auth_headers(owner)
    )
    assert r.status_code == 422


async def test_you_cannot_delete_your_only_workspace(client):
    _, _, tokens = await register(client)
    ws = await first_workspace(client, tokens)
    r = await client.delete(f"/api/v1/workspaces/{ws}", headers=auth_headers(tokens))
    assert r.status_code == 422


async def test_a_second_workspace_can_be_created_and_deleted(client):
    _, _, tokens = await register(client)
    created = await client.post(
        "/api/v1/workspaces", headers=auth_headers(tokens), json={"name": "Second"}
    )
    assert created.status_code == 201
    removed = await client.delete(
        f"/api/v1/workspaces/{created.json()['id']}", headers=auth_headers(tokens)
    )
    assert removed.status_code == 200
