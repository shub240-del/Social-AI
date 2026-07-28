"""Campaigns — the "project" a user works inside.

The product models a campaign within a workspace; the UI calls it a project.
That is a naming difference, not a missing table, so no second entity was
invented for it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from packages.shared_core.db.models import Brand, Campaign
from packages.shared_core.exceptions import NotFoundError, ValidationError
from packages.shared_core.security.rbac import Permission, UserContext
from services.identity_service.auth.dependencies import (
    SessionDep,
    requires,
)
from services.identity_service.schemas import (
    CampaignCreate,
    CampaignResponse,
    CampaignUpdate,
    MessageResponse,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/campaigns", tags=["campaigns"])


async def _get_owned(session, workspace_id: str, campaign_id: str) -> Campaign:
    result = await session.execute(
        select(Campaign).where(
            Campaign.id == campaign_id, Campaign.workspace_id == workspace_id
        )
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise NotFoundError("That campaign does not exist.")
    return campaign


async def _validate_brand(session, workspace_id: str, brand_id: str | None) -> None:
    """A brand from another tenant must not be attachable by id."""
    if brand_id is None:
        return
    result = await session.execute(
        select(Brand.id).where(Brand.id == brand_id, Brand.workspace_id == workspace_id)
    )
    if result.scalar_one_or_none() is None:
        raise ValidationError("That brand does not belong to this workspace.")


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    workspace_id: str,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.CAMPAIGN_READ))],
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[CampaignResponse]:
    query = select(Campaign).where(Campaign.workspace_id == workspace_id)
    if status_filter:
        query = query.where(Campaign.status == status_filter)
    result = await session.execute(query.order_by(Campaign.created_at.desc()))
    return [CampaignResponse.model_validate(c) for c in result.scalars()]


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    workspace_id: str,
    payload: CampaignCreate,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.CAMPAIGN_WRITE))],
) -> CampaignResponse:
    await _validate_brand(session, workspace_id, payload.brand_id)
    campaign = Campaign(workspace_id=workspace_id, **payload.model_dump())
    session.add(campaign)
    await session.flush()
    return CampaignResponse.model_validate(campaign)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    workspace_id: str,
    campaign_id: str,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.CAMPAIGN_READ))],
) -> CampaignResponse:
    return CampaignResponse.model_validate(await _get_owned(session, workspace_id, campaign_id))


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    workspace_id: str,
    campaign_id: str,
    payload: CampaignUpdate,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.CAMPAIGN_WRITE))],
) -> CampaignResponse:
    campaign = await _get_owned(session, workspace_id, campaign_id)
    data = payload.model_dump(exclude_unset=True)
    if "brand_id" in data:
        await _validate_brand(session, workspace_id, data["brand_id"])
    for key, value in data.items():
        if value is not None:
            setattr(campaign, key, value)
    await session.flush()
    return CampaignResponse.model_validate(campaign)


@router.delete("/{campaign_id}", response_model=MessageResponse)
async def delete_campaign(
    workspace_id: str,
    campaign_id: str,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.CAMPAIGN_DELETE))],
) -> MessageResponse:
    await session.delete(await _get_owned(session, workspace_id, campaign_id))
    return MessageResponse(message="Campaign deleted.")


__all__ = ["router"]
