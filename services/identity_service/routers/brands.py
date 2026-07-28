"""Brands: the voice the AI writes in.

Nested under a workspace so tenancy is enforced by the path itself. A brand id
is never resolved without also matching the workspace from the URL, which is
what stops a valid id from one tenant being read by another.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared_core.db.models import Brand
from packages.shared_core.exceptions import NotFoundError
from packages.shared_core.security.rbac import Permission, UserContext
from services.identity_service.auth.dependencies import (
    SessionDep,
    requires,
)
from services.identity_service.routing import CommitRoute
from services.identity_service.schemas import (
    BrandCreate,
    BrandResponse,
    BrandUpdate,
    MessageResponse,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/brands", tags=["brands"], route_class=CommitRoute)


async def _get_owned(session: AsyncSession, workspace_id: str, brand_id: str) -> Brand:
    result = await session.execute(
        select(Brand).where(Brand.id == brand_id, Brand.workspace_id == workspace_id)
    )
    brand: Brand | None = result.scalar_one_or_none()
    if brand is None:
        raise NotFoundError("That brand does not exist.")
    return brand


@router.get("", response_model=list[BrandResponse])
async def list_brands(
    workspace_id: str,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.BRAND_READ))],
) -> list[BrandResponse]:
    result = await session.execute(
        select(Brand).where(Brand.workspace_id == workspace_id).order_by(Brand.created_at)
    )
    return [BrandResponse.model_validate(b) for b in result.scalars()]


@router.post("", response_model=BrandResponse, status_code=status.HTTP_201_CREATED)
async def create_brand(
    workspace_id: str,
    payload: BrandCreate,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.BRAND_WRITE))],
) -> BrandResponse:
    brand = Brand(workspace_id=workspace_id, **payload.model_dump())
    session.add(brand)
    await session.flush()
    return BrandResponse.model_validate(brand)


@router.get("/{brand_id}", response_model=BrandResponse)
async def get_brand(
    workspace_id: str,
    brand_id: str,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.BRAND_READ))],
) -> BrandResponse:
    return BrandResponse.model_validate(await _get_owned(session, workspace_id, brand_id))


@router.patch("/{brand_id}", response_model=BrandResponse)
async def update_brand(
    workspace_id: str,
    brand_id: str,
    payload: BrandUpdate,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.BRAND_WRITE))],
) -> BrandResponse:
    brand = await _get_owned(session, workspace_id, brand_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(brand, key, value)
    await session.flush()
    return BrandResponse.model_validate(brand)


@router.delete("/{brand_id}", response_model=MessageResponse)
async def delete_brand(
    workspace_id: str,
    brand_id: str,
    session: SessionDep,
    context: Annotated[UserContext, Depends(requires(Permission.BRAND_DELETE))],
) -> MessageResponse:
    await session.delete(await _get_owned(session, workspace_id, brand_id))
    return MessageResponse(message="Brand deleted.")


__all__ = ["router"]
