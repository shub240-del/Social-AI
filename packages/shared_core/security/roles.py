"""Roles and the permissions each role grants."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Permission(StrEnum):
    # workspace
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"
    # members
    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_REMOVE = "member:remove"
    MEMBER_ROLE_UPDATE = "member:role_update"
    # content
    BRAND_READ = "brand:read"
    BRAND_WRITE = "brand:write"
    CAMPAIGN_READ = "campaign:read"
    CAMPAIGN_WRITE = "campaign:write"
    # ai
    CHAT_READ = "chat:read"
    CHAT_WRITE = "chat:write"


_VIEWER: frozenset[Permission] = frozenset(
    {
        Permission.WORKSPACE_READ,
        Permission.MEMBER_READ,
        Permission.BRAND_READ,
        Permission.CAMPAIGN_READ,
        Permission.CHAT_READ,
    }
)

_MEMBER: frozenset[Permission] = _VIEWER | {
    Permission.BRAND_WRITE,
    Permission.CAMPAIGN_WRITE,
    Permission.CHAT_WRITE,
}

_ADMIN: frozenset[Permission] = _MEMBER | {
    Permission.WORKSPACE_UPDATE,
    Permission.MEMBER_INVITE,
    Permission.MEMBER_REMOVE,
    Permission.MEMBER_ROLE_UPDATE,
}

_OWNER: frozenset[Permission] = _ADMIN | {Permission.WORKSPACE_DELETE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.MEMBER: _MEMBER,
    Role.ADMIN: _ADMIN,
    Role.OWNER: _OWNER,
}

# Ordering used for privilege comparisons. A principal may never grant a role
# at or above their own level; see rbac.assert_can_assign_role.
ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.MEMBER: 1,
    Role.ADMIN: 2,
    Role.OWNER: 3,
}


def permissions_for(role: Role | str) -> frozenset[Permission]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        # Unknown role string in the database grants nothing. Fail closed.
        return frozenset()
