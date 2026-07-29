"""Brand CRUD. Every query is scoped to the caller's workspace."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from packages.shared_core.db.models import Brand
from packages.shared_core.exceptions import NotFoundError
from packages.shared_core.security.rbac import assert_member, assert_permission
from packages.shared_core.security.roles import Permission
from services.identity_service.auth.dependencies import CurrentUser, SessionDep
from services.identity_service.schemas import (
    BrandCreate,
    BrandOut,
    BrandUpdate,
    Page,
    PagedBrands,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/brands", tags=["brands"])


async def _get_scoped(session, ctx, workspace_id: str, brand_id: str) -> Brand:
    assert_member(ctx, workspace_id)
    # workspace_id is part of the predicate, so a valid brand id from another
    # tenant cannot be reached by guessing.
    result = await session.execute(
        select(Brand).where(Brand.id == brand_id, Brand.workspace_id == workspace_id)
    )
    brand = result.scalar_one_or_none()
    if brand is None:
        raise NotFoundError("Brand not found.")
    return brand


@router.get("", response_model=PagedBrands)
async def list_brands(
    workspace_id: str,
    ctx: CurrentUser,
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PagedBrands:
    assert_permission(ctx, workspace_id, Permission.BRAND_READ)
    total = await session.scalar(
        select(func.count(Brand.id)).where(Brand.workspace_id == workspace_id)
    )
    rows = await session.execute(
        select(Brand)
        .where(Brand.workspace_id == workspace_id)
        .order_by(Brand.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return PagedBrands(
        items=[BrandOut.model_validate(b) for b in rows.scalars()],
        page=Page(total=total or 0, limit=limit, offset=offset),
    )


@router.post("", response_model=BrandOut, status_code=status.HTTP_201_CREATED)
async def create_brand(
    workspace_id: str, payload: BrandCreate, ctx: CurrentUser, session: SessionDep
) -> BrandOut:
    assert_permission(ctx, workspace_id, Permission.BRAND_WRITE)
    brand = Brand(workspace_id=workspace_id, **payload.model_dump())
    session.add(brand)
    await session.flush()
    return BrandOut.model_validate(brand)


@router.get("/{brand_id}", response_model=BrandOut)
async def get_brand(
    workspace_id: str, brand_id: str, ctx: CurrentUser, session: SessionDep
) -> BrandOut:
    assert_permission(ctx, workspace_id, Permission.BRAND_READ)
    return BrandOut.model_validate(await _get_scoped(session, ctx, workspace_id, brand_id))


@router.patch("/{brand_id}", response_model=BrandOut)
async def update_brand(
    workspace_id: str,
    brand_id: str,
    payload: BrandUpdate,
    ctx: CurrentUser,
    session: SessionDep,
) -> BrandOut:
    assert_permission(ctx, workspace_id, Permission.BRAND_WRITE)
    brand = await _get_scoped(session, ctx, workspace_id, brand_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(brand, field, value)
    await session.flush()
    return BrandOut.model_validate(brand)


@router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_brand(
    workspace_id: str, brand_id: str, ctx: CurrentUser, session: SessionDep
) -> None:
    assert_permission(ctx, workspace_id, Permission.BRAND_WRITE)
    await session.delete(await _get_scoped(session, ctx, workspace_id, brand_id))
