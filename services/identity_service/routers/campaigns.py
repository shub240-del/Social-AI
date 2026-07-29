"""Campaign (project) CRUD, scoped to the caller's workspace."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from packages.shared_core.db.models import Brand, Campaign
from packages.shared_core.exceptions import NotFoundError, ValidationError
from packages.shared_core.security.rbac import assert_member, assert_permission
from packages.shared_core.security.roles import Permission
from services.identity_service.auth.dependencies import CurrentUser, SessionDep
from services.identity_service.schemas import (
    CampaignCreate,
    CampaignOut,
    CampaignUpdate,
    Page,
    PagedCampaigns,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/campaigns", tags=["campaigns"])


async def _assert_brand_in_workspace(session, workspace_id: str, brand_id: str | None) -> None:
    """Prevent attaching a campaign to another tenant's brand."""
    if brand_id is None:
        return
    found = await session.execute(
        select(Brand.id).where(Brand.id == brand_id, Brand.workspace_id == workspace_id)
    )
    if found.first() is None:
        raise ValidationError("brand_id does not belong to this workspace.")


async def _get_scoped(session, ctx, workspace_id: str, campaign_id: str) -> Campaign:
    assert_member(ctx, workspace_id)
    result = await session.execute(
        select(Campaign).where(
            Campaign.id == campaign_id, Campaign.workspace_id == workspace_id
        )
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise NotFoundError("Campaign not found.")
    return campaign


@router.get("", response_model=PagedCampaigns)
async def list_campaigns(
    workspace_id: str,
    ctx: CurrentUser,
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
) -> PagedCampaigns:
    assert_permission(ctx, workspace_id, Permission.CAMPAIGN_READ)
    conditions = [Campaign.workspace_id == workspace_id]
    if status_filter:
        conditions.append(Campaign.status == status_filter)
    total = await session.scalar(select(func.count(Campaign.id)).where(*conditions))
    rows = await session.execute(
        select(Campaign)
        .where(*conditions)
        .order_by(Campaign.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return PagedCampaigns(
        items=[CampaignOut.model_validate(c) for c in rows.scalars()],
        page=Page(total=total or 0, limit=limit, offset=offset),
    )


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    workspace_id: str, payload: CampaignCreate, ctx: CurrentUser, session: SessionDep
) -> CampaignOut:
    assert_permission(ctx, workspace_id, Permission.CAMPAIGN_WRITE)
    await _assert_brand_in_workspace(session, workspace_id, payload.brand_id)
    campaign = Campaign(workspace_id=workspace_id, **payload.model_dump())
    session.add(campaign)
    await session.flush()
    return CampaignOut.model_validate(campaign)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    workspace_id: str, campaign_id: str, ctx: CurrentUser, session: SessionDep
) -> CampaignOut:
    assert_permission(ctx, workspace_id, Permission.CAMPAIGN_READ)
    return CampaignOut.model_validate(
        await _get_scoped(session, ctx, workspace_id, campaign_id)
    )


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    workspace_id: str,
    campaign_id: str,
    payload: CampaignUpdate,
    ctx: CurrentUser,
    session: SessionDep,
) -> CampaignOut:
    assert_permission(ctx, workspace_id, Permission.CAMPAIGN_WRITE)
    campaign = await _get_scoped(session, ctx, workspace_id, campaign_id)
    data = payload.model_dump(exclude_unset=True)
    if "brand_id" in data:
        await _assert_brand_in_workspace(session, workspace_id, data["brand_id"])
    for field, value in data.items():
        if value is not None:
            setattr(campaign, field, value)
    await session.flush()
    return CampaignOut.model_validate(campaign)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_campaign(
    workspace_id: str, campaign_id: str, ctx: CurrentUser, session: SessionDep
) -> None:
    assert_permission(ctx, workspace_id, Permission.CAMPAIGN_WRITE)
    await session.delete(await _get_scoped(session, ctx, workspace_id, campaign_id))
