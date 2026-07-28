"""Workspaces and their members.

Every handler that touches a specific workspace depends on
``WorkspaceContext``, which has already proven membership. A handler therefore
never filters by ``user_id`` itself — that duplication is exactly where
cross-tenant bugs come from.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

from packages.shared_core.db.models import Brand, Campaign, Membership, User, Workspace
from packages.shared_core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from packages.shared_core.security.rbac import Permission, Role, UserContext, outranks, parse_role
from services.identity_service.auth.dependencies import (
    CurrentUser,
    SessionDep,
    WorkspaceContext,
    requires,
)
from services.identity_service.schemas import (
    MemberInvite,
    MemberResponse,
    MemberRoleUpdate,
    MessageResponse,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from services.identity_service.services.user_provisioning import create_workspace, unique_slug

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(user: CurrentUser, session: SessionDep) -> list[WorkspaceResponse]:
    result = await session.execute(
        select(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.user_id == user.user_id)
        .order_by(Workspace.created_at)
    )
    return [
        WorkspaceResponse(
            **{
                k: getattr(workspace, k)
                for k in ("id", "name", "slug", "description", "owner_id", "created_at")
            },
            role=membership.role,
        )
        for membership, workspace in result.all()
    ]


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create(
    payload: WorkspaceCreate, user: CurrentUser, session: SessionDep
) -> WorkspaceResponse:
    owner = await session.get(User, user.user_id)
    if owner is None:
        raise NotFoundError("Your account could not be loaded.")
    workspace = await create_workspace(
        session, owner=owner, name=payload.name, description=payload.description
    )
    return WorkspaceResponse.model_validate(workspace).model_copy(update={"role": str(Role.OWNER)})


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_one(workspace_id: str, context: WorkspaceContext, session: SessionDep) -> WorkspaceResponse:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("That workspace does not exist.")
    return WorkspaceResponse.model_validate(workspace).model_copy(
        update={"role": str(context.role)}
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update(
    workspace_id: str,
    payload: WorkspaceUpdate,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.WORKSPACE_UPDATE))],
) -> WorkspaceResponse:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("That workspace does not exist.")

    if payload.name is not None and payload.name != workspace.name:
        workspace.name = payload.name
        workspace.slug = await unique_slug(session, workspace.owner_id, payload.name)
    if payload.description is not None:
        workspace.description = payload.description
    await session.flush()
    return WorkspaceResponse.model_validate(workspace).model_copy(
        update={"role": str(context.role)}
    )


@router.delete("/{workspace_id}", response_model=MessageResponse)
async def delete(
    workspace_id: str,
    user: CurrentUser,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.WORKSPACE_DELETE))],
) -> MessageResponse:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("That workspace does not exist.")

    # Losing your only workspace leaves the dashboard unusable with no way to
    # recover from the UI.
    remaining = await session.execute(
        select(func.count(Membership.id)).where(Membership.user_id == user.user_id)
    )
    if (remaining.scalar_one() or 0) <= 1:
        raise ValidationError("You cannot delete your only workspace.")

    await session.delete(workspace)
    return MessageResponse(message="Workspace deleted.")


@router.get("/{workspace_id}/stats")
async def stats(workspace_id: str, context: WorkspaceContext, session: SessionDep) -> dict[str, int]:
    async def count(model) -> int:
        result = await session.execute(
            select(func.count(model.id)).where(model.workspace_id == workspace_id)
        )
        return int(result.scalar_one() or 0)

    members = await session.execute(
        select(func.count(Membership.id)).where(Membership.workspace_id == workspace_id)
    )
    return {
        "brands": await count(Brand),
        "campaigns": await count(Campaign),
        "members": int(members.scalar_one() or 0),
    }


# ---- members ----------------------------------------------------------


@router.get("/{workspace_id}/members", response_model=list[MemberResponse])
async def list_members(
    workspace_id: str,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.MEMBER_READ))],
) -> list[MemberResponse]:
    result = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(User.email)
    )
    return [
        MemberResponse(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=membership.role,
            joined_at=membership.created_at,
        )
        for membership, user in result.all()
    ]


@router.post(
    "/{workspace_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED
)
async def add_member(
    workspace_id: str,
    payload: MemberInvite,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.MEMBER_INVITE))],
) -> MemberResponse:
    target_role = parse_role(payload.role)
    # You may only grant a role strictly below your own. Without this an admin
    # could grant owner and then be removed by the account they just created.
    if context.role is None or not outranks(context.role, target_role):
        raise PermissionDeniedError("You cannot grant a role at or above your own.")

    result = await session.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if user is None:
        # Not an enumeration risk: the caller is already a trusted member here.
        raise NotFoundError("No account with that email exists yet. Ask them to sign up first.")

    existing = await session.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user.id
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("That person is already a member of this workspace.")

    membership = Membership(user_id=user.id, workspace_id=workspace_id, role=str(target_role))
    session.add(membership)
    await session.flush()
    return MemberResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    workspace_id: str,
    user_id: str,
    payload: MemberRoleUpdate,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.MEMBER_ROLE_UPDATE))],
) -> MemberResponse:
    result = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
    )
    row = result.first()
    if row is None:
        raise NotFoundError("That person is not a member of this workspace.")
    membership, user = row

    current = parse_role(membership.role)
    target = parse_role(payload.role)
    if (
        context.role is not None
        and context.role != Role.OWNER
        and (not outranks(context.role, current) or not outranks(context.role, target))
    ):
        raise PermissionDeniedError("You cannot change a role at or above your own.")

    workspace = await session.get(Workspace, workspace_id)
    if workspace is not None and workspace.owner_id == user_id and target != Role.OWNER:
        raise ValidationError("Transfer ownership before demoting the workspace owner.")

    membership.role = str(target)
    await session.flush()
    return MemberResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.delete("/{workspace_id}/members/{user_id}", response_model=MessageResponse)
async def remove_member(
    workspace_id: str,
    user_id: str,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.MEMBER_REMOVE))],
) -> MessageResponse:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is not None and workspace.owner_id == user_id:
        raise ValidationError("The workspace owner cannot be removed.")

    result = await session.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise NotFoundError("That person is not a member of this workspace.")

    if (
        context.role is not None
        and context.role != Role.OWNER
        and not outranks(context.role, parse_role(membership.role))
    ):
        raise PermissionDeniedError("You cannot remove a member at or above your own role.")

    await session.delete(membership)
    return MessageResponse(message="Member removed.")


__all__ = ["router"]
