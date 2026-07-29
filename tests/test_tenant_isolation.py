"""Multi-tenant isolation and privilege escalation.

The single most important assertion in a multi-tenant SaaS: a member of
workspace A can never reach workspace B's data, and no one can grant
themselves a role above their own.
"""

from __future__ import annotations

import pytest

from packages.shared_core.security.rbac import (
    assert_can_assign_role,
    assert_member,
    has_permission,
)
from packages.shared_core.security.roles import Permission, Role, permissions_for
from packages.shared_core.security.user_context import UserContext
from tests.conftest import register

# ---- unit: RBAC deny branches ---------------------------------------


def test_non_member_has_no_permissions():
    ctx = UserContext(user_id="u1", email="a@b.c", memberships={})
    for perm in Permission:
        assert not has_permission(ctx, "ws-1", perm)


def test_unknown_role_grants_nothing():
    """A corrupt role string in the DB must fail closed, not open."""
    assert permissions_for("not-a-real-role") == frozenset()
    ctx = UserContext(user_id="u1", email="a@b.c", memberships={"ws": "sudo"})
    assert not has_permission(ctx, "ws", Permission.WORKSPACE_READ)


def test_viewer_cannot_write():
    ctx = UserContext(user_id="u1", email="a@b.c", memberships={"ws": Role.VIEWER})
    assert has_permission(ctx, "ws", Permission.BRAND_READ)
    assert not has_permission(ctx, "ws", Permission.BRAND_WRITE)
    assert not has_permission(ctx, "ws", Permission.CHAT_WRITE)
    assert not has_permission(ctx, "ws", Permission.MEMBER_INVITE)


def test_member_cannot_administer():
    ctx = UserContext(user_id="u1", email="a@b.c", memberships={"ws": Role.MEMBER})
    assert has_permission(ctx, "ws", Permission.CHAT_WRITE)
    assert not has_permission(ctx, "ws", Permission.MEMBER_INVITE)
    assert not has_permission(ctx, "ws", Permission.WORKSPACE_DELETE)


def test_admin_cannot_delete_workspace():
    ctx = UserContext(user_id="u1", email="a@b.c", memberships={"ws": Role.ADMIN})
    assert has_permission(ctx, "ws", Permission.MEMBER_INVITE)
    assert not has_permission(ctx, "ws", Permission.WORKSPACE_DELETE)


def test_assert_member_raises_not_found_not_forbidden():
    """404, not 403: existence of another tenant's workspace must not leak."""
    from packages.shared_core.exceptions import NotFoundError

    ctx = UserContext(user_id="u1", email="a@b.c", memberships={})
    with pytest.raises(NotFoundError):
        assert_member(ctx, "someone-elses-workspace")


def test_admin_cannot_create_owner():
    from packages.shared_core.exceptions import AuthorizationError

    ctx = UserContext(user_id="u1", email="a@b.c", memberships={"ws": Role.ADMIN})
    with pytest.raises(AuthorizationError):
        assert_can_assign_role(ctx, "ws", Role.OWNER)


def test_admin_cannot_clone_own_rank():
    from packages.shared_core.exceptions import AuthorizationError

    ctx = UserContext(user_id="u1", email="a@b.c", memberships={"ws": Role.ADMIN})
    with pytest.raises(AuthorizationError):
        assert_can_assign_role(ctx, "ws", Role.ADMIN)


def test_admin_may_assign_lower_roles():
    ctx = UserContext(user_id="u1", email="a@b.c", memberships={"ws": Role.ADMIN})
    assert_can_assign_role(ctx, "ws", Role.MEMBER)
    assert_can_assign_role(ctx, "ws", Role.VIEWER)


def test_member_cannot_assign_any_role():
    from packages.shared_core.exceptions import AuthorizationError

    ctx = UserContext(user_id="u1", email="a@b.c", memberships={"ws": Role.MEMBER})
    with pytest.raises(AuthorizationError):
        assert_can_assign_role(ctx, "ws", Role.VIEWER)


# ---- HTTP: cross-tenant access --------------------------------------


async def test_intruder_cannot_touch_any_resource(client):
    victim = await register(client)
    intruder = await register(client)
    ws = victim["workspace_id"]
    vh, ih = victim["headers"], intruder["headers"]

    brand = (
        await client.post(
            f"/api/v1/workspaces/{ws}/brands", headers=vh, json={"name": "Secret Brand"}
        )
    ).json()["id"]
    campaign = (
        await client.post(
            f"/api/v1/workspaces/{ws}/campaigns", headers=vh, json={"name": "Secret Campaign"}
        )
    ).json()["id"]
    conv = (
        await client.post(
            f"/api/v1/workspaces/{ws}/chat", headers=vh, json={"prompt": "confidential"}
        )
    ).json()["conversation_id"]

    forbidden = [
        ("GET", f"/api/v1/workspaces/{ws}"),
        ("PATCH", f"/api/v1/workspaces/{ws}"),
        ("DELETE", f"/api/v1/workspaces/{ws}"),
        ("GET", f"/api/v1/workspaces/{ws}/members"),
        ("POST", f"/api/v1/workspaces/{ws}/members"),
        ("GET", f"/api/v1/workspaces/{ws}/brands"),
        ("POST", f"/api/v1/workspaces/{ws}/brands"),
        ("GET", f"/api/v1/workspaces/{ws}/brands/{brand}"),
        ("PATCH", f"/api/v1/workspaces/{ws}/brands/{brand}"),
        ("DELETE", f"/api/v1/workspaces/{ws}/brands/{brand}"),
        ("GET", f"/api/v1/workspaces/{ws}/campaigns"),
        ("GET", f"/api/v1/workspaces/{ws}/campaigns/{campaign}"),
        ("DELETE", f"/api/v1/workspaces/{ws}/campaigns/{campaign}"),
        ("POST", f"/api/v1/workspaces/{ws}/chat"),
        ("GET", f"/api/v1/workspaces/{ws}/chat/conversations"),
        ("GET", f"/api/v1/workspaces/{ws}/chat/conversations/{conv}"),
        ("DELETE", f"/api/v1/workspaces/{ws}/chat/conversations/{conv}"),
    ]
    for method, url in forbidden:
        r = await client.request(
            method, url, headers=ih, json={"name": "x", "prompt": "x", "email": "a@b.co"}
        )
        assert r.status_code == 404, f"{method} {url} leaked with {r.status_code}"


async def test_intruder_workspace_list_is_empty_of_victim_data(client):
    victim = await register(client)
    intruder = await register(client)
    r = await client.get("/api/v1/workspaces", headers=intruder["headers"])
    ids = {w["id"] for w in r.json()}
    assert victim["workspace_id"] not in ids


async def test_viewer_cannot_write_over_http(client):
    """End-to-end proof that a downgraded role is enforced by the API."""
    owner = await register(client)
    viewer = await register(client)
    ws = owner["workspace_id"]

    add = await client.post(
        f"/api/v1/workspaces/{ws}/members",
        headers=owner["headers"],
        json={"email": viewer["email"], "role": "viewer"},
    )
    assert add.status_code == 201, add.text

    read = await client.get(f"/api/v1/workspaces/{ws}/brands", headers=viewer["headers"])
    assert read.status_code == 200

    write = await client.post(
        f"/api/v1/workspaces/{ws}/brands", headers=viewer["headers"], json={"name": "nope"}
    )
    assert write.status_code == 403
    assert write.json()["error"]["code"] == "forbidden"

    chat = await client.post(
        f"/api/v1/workspaces/{ws}/chat", headers=viewer["headers"], json={"prompt": "hi"}
    )
    assert chat.status_code == 403


async def test_member_cannot_escalate_self_over_http(client):
    owner = await register(client)
    member = await register(client)
    ws = owner["workspace_id"]
    await client.post(
        f"/api/v1/workspaces/{ws}/members",
        headers=owner["headers"],
        json={"email": member["email"], "role": "member"},
    )
    r = await client.patch(
        f"/api/v1/workspaces/{ws}/members/{member['user_id']}",
        headers=member["headers"],
        json={"role": "owner"},
    )
    assert r.status_code == 403


async def test_owner_role_cannot_be_downgraded(client):
    owner = await register(client)
    ws = owner["workspace_id"]
    r = await client.patch(
        f"/api/v1/workspaces/{ws}/members/{owner['user_id']}",
        headers=owner["headers"],
        json={"role": "admin"},
    )
    assert r.status_code == 422


async def test_owner_cannot_be_removed(client):
    owner = await register(client)
    ws = owner["workspace_id"]
    r = await client.delete(
        f"/api/v1/workspaces/{ws}/members/{owner['user_id']}", headers=owner["headers"]
    )
    assert r.status_code == 422
