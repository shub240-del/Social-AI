"""Authorization decisions.

Fails closed everywhere. Cross-tenant reads return 404 rather than 403 so the
API does not confirm the existence of resources in workspaces the caller
cannot see.
"""

from __future__ import annotations

from packages.shared_core.exceptions import AuthorizationError, NotFoundError
from packages.shared_core.security.roles import (
    ROLE_RANK,
    Permission,
    Role,
    permissions_for,
)
from packages.shared_core.security.user_context import UserContext


def has_permission(ctx: UserContext, workspace_id: str, permission: Permission) -> bool:
    if ctx.is_superuser:
        return True
    role = ctx.role_in(workspace_id)
    if role is None:
        return False
    return permission in permissions_for(role)


def assert_member(ctx: UserContext, workspace_id: str) -> None:
    """Caller must belong to the workspace.

    Raises NotFoundError, not AuthorizationError: a non-member must not be able
    to distinguish 'workspace exists but is denied' from 'no such workspace'.
    """
    if ctx.is_superuser or ctx.is_member_of(workspace_id):
        return
    raise NotFoundError("Workspace not found.")


def assert_permission(ctx: UserContext, workspace_id: str, permission: Permission) -> None:
    assert_member(ctx, workspace_id)
    if not has_permission(ctx, workspace_id, permission):
        raise AuthorizationError(
            f"Role '{ctx.role_in(workspace_id)}' lacks permission '{permission.value}'.",
            details={"required_permission": permission.value},
        )


def assert_can_assign_role(ctx: UserContext, workspace_id: str, target_role: Role) -> None:
    """Block privilege escalation.

    A principal may only grant roles strictly below their own rank, so an admin
    can never mint another owner, nor promote themselves.
    """
    assert_permission(ctx, workspace_id, Permission.MEMBER_ROLE_UPDATE)
    if ctx.is_superuser:
        return
    actor_role = ctx.role_in(workspace_id)
    if actor_role is None:
        raise AuthorizationError("You are not a member of this workspace.")
    if ROLE_RANK[Role(target_role)] >= ROLE_RANK[Role(actor_role)]:
        raise AuthorizationError(
            "You cannot assign a role equal to or above your own.",
            details={"your_role": actor_role, "attempted_role": str(target_role)},
        )
