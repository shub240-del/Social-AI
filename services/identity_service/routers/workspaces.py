"""Workspace and membership management."""

from __future__ import annotations

import re

from fastapi import APIRouter, status
from sqlalchemy import select

from packages.shared_core.db.models import Membership, User, Workspace
from packages.shared_core.exceptions import ConflictError, NotFoundError, ValidationError
from packages.shared_core.security.rbac import (
    assert_can_assign_role,
    assert_member,
    assert_permission,
)
from packages.shared_core.security.roles import Permission, Role
from services.identity_service.auth.dependencies import CurrentUser, SessionDep
from services.identity_service.schemas import (
    MemberInvite,
    MemberOut,
    MemberRoleUpdate,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "workspace"


async def _unique_slug(session, base: str) -> str:
    slug, n = base, 1
    while (
        await session.execute(select(Workspace.id).where(Workspace.slug == slug))
    ).first() is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


async def _get_scoped(session, ctx, workspace_id: str) -> Workspace:
    """Load a workspace the caller is permitted to see, else 404."""
    assert_member(ctx, workspace_id)
    ws = await session.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("Workspace not found.")
    return ws


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(ctx: CurrentUser, session: SessionDep) -> list[WorkspaceOut]:
    rows = await session.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == ctx.user_id)
        .order_by(Workspace.created_at)
    )
    return [
        WorkspaceOut(
            **WorkspaceOut.model_validate(ws).model_dump(exclude={"role"}), role=role
        )
        for ws, role in rows.all()
    ]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate, ctx: CurrentUser, session: SessionDep
) -> WorkspaceOut:
    ws = Workspace(
        name=payload.name.strip(),
        slug=await _unique_slug(session, _slugify(payload.name)),
        owner_id=ctx.user_id,
    )
    session.add(ws)
    await session.flush()
    session.add(Membership(user_id=ctx.user_id, workspace_id=ws.id, role=Role.OWNER.value))
    await session.flush()
    return WorkspaceOut(
        **WorkspaceOut.model_validate(ws).model_dump(exclude={"role"}), role=Role.OWNER.value
    )


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: str, ctx: CurrentUser, session: SessionDep
) -> WorkspaceOut:
    ws = await _get_scoped(session, ctx, workspace_id)
    return WorkspaceOut(
        **WorkspaceOut.model_validate(ws).model_dump(exclude={"role"}),
        role=ctx.role_in(workspace_id),
    )


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: str, payload: WorkspaceUpdate, ctx: CurrentUser, session: SessionDep
) -> WorkspaceOut:
    ws = await _get_scoped(session, ctx, workspace_id)
    assert_permission(ctx, workspace_id, Permission.WORKSPACE_UPDATE)
    ws.name = payload.name.strip()
    await session.flush()
    return WorkspaceOut(
        **WorkspaceOut.model_validate(ws).model_dump(exclude={"role"}),
        role=ctx.role_in(workspace_id),
    )


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_workspace(workspace_id: str, ctx: CurrentUser, session: SessionDep) -> None:
    ws = await _get_scoped(session, ctx, workspace_id)
    assert_permission(ctx, workspace_id, Permission.WORKSPACE_DELETE)
    await session.delete(ws)


# ---- members ---------------------------------------------------------


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(
    workspace_id: str, ctx: CurrentUser, session: SessionDep
) -> list[MemberOut]:
    await _get_scoped(session, ctx, workspace_id)
    assert_permission(ctx, workspace_id, Permission.MEMBER_READ)
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(Membership.created_at)
    )
    return [
        MemberOut(
            user_id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=m.role,
            joined_at=m.created_at,
        )
        for m, u in rows.all()
    ]


@router.post(
    "/{workspace_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED
)
async def add_member(
    workspace_id: str, payload: MemberInvite, ctx: CurrentUser, session: SessionDep
) -> MemberOut:
    await _get_scoped(session, ctx, workspace_id)
    assert_permission(ctx, workspace_id, Permission.MEMBER_INVITE)
    assert_can_assign_role(ctx, workspace_id, payload.role)

    result = await session.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("No account exists with that email address.")

    dupe = await session.execute(
        select(Membership.id).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user.id
        )
    )
    if dupe.first() is not None:
        raise ConflictError("That user is already a member of this workspace.")

    membership = Membership(
        user_id=user.id, workspace_id=workspace_id, role=payload.role.value
    )
    session.add(membership)
    await session.flush()
    return MemberOut(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
async def update_member_role(
    workspace_id: str,
    user_id: str,
    payload: MemberRoleUpdate,
    ctx: CurrentUser,
    session: SessionDep,
) -> MemberOut:
    ws = await _get_scoped(session, ctx, workspace_id)
    assert_can_assign_role(ctx, workspace_id, payload.role)

    result = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
    )
    row = result.first()
    if row is None:
        raise NotFoundError("That user is not a member of this workspace.")
    membership, user = row

    if user_id == ws.owner_id and payload.role != Role.OWNER:
        raise ValidationError("The workspace owner's role cannot be downgraded.")

    membership.role = payload.role.value
    await session.flush()
    return MemberOut(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.delete(
    "/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def remove_member(
    workspace_id: str, user_id: str, ctx: CurrentUser, session: SessionDep
) -> None:
    ws = await _get_scoped(session, ctx, workspace_id)
    assert_permission(ctx, workspace_id, Permission.MEMBER_REMOVE)
    if user_id == ws.owner_id:
        raise ValidationError("The workspace owner cannot be removed.")
    result = await session.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise NotFoundError("That user is not a member of this workspace.")
    await session.delete(membership)
