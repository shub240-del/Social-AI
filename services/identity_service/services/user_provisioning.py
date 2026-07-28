"""Creating a user and everything a user needs to be useful immediately.

A brand-new account with no workspace lands on an empty dashboard and has to
guess what to do. Registration therefore also creates one starter workspace,
owned by the new user, plus a default brand to make the chat useful on the
first try.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared_core.db.models import Brand, Membership, User, Workspace
from packages.shared_core.exceptions import ConflictError
from packages.shared_core.security.passwords import hash_password
from packages.shared_core.security.rbac import Role

logger = logging.getLogger(__name__)


def slugify(value: str, *, fallback: str = "workspace") -> str:
    normalised = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalised.lower()).strip("-")
    return (slug or fallback)[:120]


async def unique_slug(session: AsyncSession, owner_id: str, base: str) -> str:
    """Slugs are unique per owner, so two users may both have 'marketing'."""
    slug = slugify(base)
    candidate = slug
    suffix = 2
    while True:
        exists = await session.execute(
            select(Workspace.id).where(
                Workspace.owner_id == owner_id, Workspace.slug == candidate
            )
        )
        if exists.scalar_one_or_none() is None:
            return candidate
        candidate = f"{slug}-{suffix}"
        suffix += 1


async def email_exists(session: AsyncSession, email: str) -> bool:
    result = await session.execute(
        select(User.id).where(func.lower(User.email) == email.lower())
    )
    return result.scalar_one_or_none() is not None


async def create_workspace(
    session: AsyncSession,
    *,
    owner: User,
    name: str,
    description: str = "",
    role: Role = Role.OWNER,
) -> Workspace:
    workspace = Workspace(
        name=name,
        slug=await unique_slug(session, owner.id, name),
        description=description,
        owner_id=owner.id,
    )
    session.add(workspace)
    await session.flush()

    session.add(Membership(user_id=owner.id, workspace_id=workspace.id, role=str(role)))
    await session.flush()
    return workspace


async def provision_user(
    session: AsyncSession,
    *,
    email: str,
    password: str | None,
    full_name: str,
    external_id: str | None = None,
    is_superuser: bool = False,
) -> tuple[User, Workspace]:
    """Create the user, a starter workspace and a default brand.

    Raises ConflictError if the address is taken. The check is advisory: the
    unique index on users.email is the real guarantee against a race.
    """
    email = email.strip().lower()
    if await email_exists(session, email):
        raise ConflictError("An account with that email already exists.")

    user = User(
        email=email,
        full_name=full_name.strip() or email.split("@")[0],
        hashed_password=hash_password(password) if password else None,
        external_id=external_id,
        is_superuser=is_superuser,
    )
    session.add(user)
    await session.flush()

    display = user.full_name.split()[0] if user.full_name else "My"
    workspace = await create_workspace(
        session,
        owner=user,
        name=f"{display}'s Workspace",
        description="Your starter workspace. Rename it or create more at any time.",
    )

    session.add(
        Brand(
            workspace_id=workspace.id,
            name="Default Brand",
            description="Describe your product and the voice you want the AI to use.",
            tone="professional",
            audience="General audience",
        )
    )
    await session.flush()

    logger.info("provisioned user", extra={"user_id": user.id, "workspace_id": workspace.id})
    return user, workspace


__all__ = [
    "create_workspace",
    "email_exists",
    "provision_user",
    "slugify",
    "unique_slug",
]
