"""Roles, permissions and the checks that enforce them.

Permissions are granted per role and evaluated against the caller's role *in
the workspace being touched* — never against a global role. A user can be an
owner of one workspace and have no access at all to another.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from packages.shared_core.exceptions import PermissionDeniedError


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    MEMBER = "member"
    VIEWER = "viewer"


class Permission(StrEnum):
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"
    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_REMOVE = "member:remove"
    MEMBER_ROLE_UPDATE = "member:role_update"
    BRAND_READ = "brand:read"
    BRAND_WRITE = "brand:write"
    BRAND_DELETE = "brand:delete"
    CAMPAIGN_READ = "campaign:read"
    CAMPAIGN_WRITE = "campaign:write"
    CAMPAIGN_DELETE = "campaign:delete"
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

# A member can use the product; an editor can additionally shape it.
_MEMBER: frozenset[Permission] = _VIEWER | {Permission.CHAT_WRITE}

_EDITOR: frozenset[Permission] = _MEMBER | {
    Permission.BRAND_WRITE,
    Permission.CAMPAIGN_WRITE,
}

_ADMIN: frozenset[Permission] = _EDITOR | {
    Permission.WORKSPACE_UPDATE,
    Permission.MEMBER_INVITE,
    Permission.MEMBER_REMOVE,
    Permission.MEMBER_ROLE_UPDATE,
    Permission.BRAND_DELETE,
    Permission.CAMPAIGN_DELETE,
}

# Only the owner may delete the workspace itself.
_OWNER: frozenset[Permission] = _ADMIN | {Permission.WORKSPACE_DELETE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.MEMBER: _MEMBER,
    Role.EDITOR: _EDITOR,
    Role.ADMIN: _ADMIN,
    Role.OWNER: _OWNER,
}

# Used to answer "can this role act on that role", e.g. an admin must not be
# able to demote an owner.
ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.MEMBER: 1,
    Role.EDITOR: 2,
    Role.ADMIN: 3,
    Role.OWNER: 4,
}


def parse_role(value: str) -> Role:
    try:
        return Role(value)
    except ValueError:
        # An unrecognised role in the database must fail closed.
        return Role.VIEWER


def permissions_for(role: Role | str) -> frozenset[Permission]:
    if isinstance(role, str):
        role = parse_role(role)
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: Role | str, permission: Permission) -> bool:
    return permission in permissions_for(role)


def require_permission(role: Role | str, permission: Permission) -> None:
    if not has_permission(role, permission):
        raise PermissionDeniedError(
            f"Your role ({role}) does not allow {permission}.",
            details={"required_permission": str(permission), "role": str(role)},
        )


def outranks(actor: Role | str, target: Role | str) -> bool:
    a = parse_role(actor) if isinstance(actor, str) else actor
    t = parse_role(target) if isinstance(target, str) else target
    return ROLE_RANK[a] > ROLE_RANK[t]


@dataclass(frozen=True, slots=True)
class UserContext:
    """Who is calling, and what they may do in the current workspace."""

    user_id: str
    email: str
    is_superuser: bool = False
    workspace_id: str | None = None
    role: Role | None = None
    permissions: frozenset[Permission] = field(default_factory=frozenset)

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise PermissionDeniedError(
                f"Your role does not allow {permission}.",
                details={"required_permission": str(permission)},
            )


__all__ = [
    "ROLE_PERMISSIONS",
    "ROLE_RANK",
    "Permission",
    "Role",
    "UserContext",
    "has_permission",
    "outranks",
    "parse_role",
    "permissions_for",
    "require_permission",
]
