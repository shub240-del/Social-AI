"""Brand and campaign grounding of the system prompt.

Regression cover: `campaign_id` used to be validated and persisted but never
reached the model, so selecting a campaign changed nothing about the output.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared_core.db.models import Brand, Campaign, User, Workspace
from packages.shared_core.exceptions import ValidationError
from services.identity_service.routers.chat import (
    BASE_SYSTEM_PROMPT,
    _build_system_prompt,
)


@pytest.fixture
async def seeded(db_session: AsyncSession):
    """A workspace with a brand and a campaign, plus a second tenant."""
    user = User(email="grounding@example.com", full_name="G", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    ws = Workspace(name="Acme", slug=f"acme-{user.id[:8]}", owner_id=user.id)
    other = Workspace(name="Other", slug=f"other-{user.id[:8]}", owner_id=user.id)
    db_session.add_all([ws, other])
    await db_session.flush()

    brand = Brand(
        workspace_id=ws.id,
        name="Acme Voice",
        description="Payments for small shops",
        tone_of_voice="Direct, warm, no jargon",
        target_audience="Independent retailers",
    )
    campaign = Campaign(
        workspace_id=ws.id,
        name="Series A launch",
        objective="Drive demo signups from retailers",
        status="active",
    )
    foreign_brand = Brand(workspace_id=other.id, name="Foreign", description="secret")
    foreign_campaign = Campaign(workspace_id=other.id, name="Foreign", objective="secret")
    db_session.add_all([brand, campaign, foreign_brand, foreign_campaign])
    await db_session.flush()

    return {
        "session": db_session,
        "ws": ws.id,
        "brand": brand.id,
        "campaign": campaign.id,
        "foreign_brand": foreign_brand.id,
        "foreign_campaign": foreign_campaign.id,
    }


async def test_no_brand_or_campaign_returns_the_base_prompt(seeded):
    prompt = await _build_system_prompt(seeded["session"], seeded["ws"], None, None)
    assert prompt == BASE_SYSTEM_PROMPT


async def test_brand_voice_is_injected(seeded):
    prompt = await _build_system_prompt(seeded["session"], seeded["ws"], seeded["brand"], None)
    assert "Acme Voice" in prompt
    assert "Direct, warm, no jargon" in prompt
    assert "Independent retailers" in prompt
    assert prompt.startswith(BASE_SYSTEM_PROMPT)


async def test_campaign_objective_is_injected(seeded):
    """The regression: this returned the bare base prompt."""
    prompt = await _build_system_prompt(seeded["session"], seeded["ws"], None, seeded["campaign"])
    assert "Series A launch" in prompt
    assert "Drive demo signups from retailers" in prompt
    assert prompt != BASE_SYSTEM_PROMPT


async def test_brand_and_campaign_combine(seeded):
    prompt = await _build_system_prompt(
        seeded["session"], seeded["ws"], seeded["brand"], seeded["campaign"]
    )
    assert "Direct, warm, no jargon" in prompt
    assert "Drive demo signups from retailers" in prompt
    # Brand voice first, then the campaign objective that must be served.
    assert prompt.index("Acme Voice") < prompt.index("Series A launch")


async def test_brand_from_another_workspace_is_rejected(seeded):
    with pytest.raises(ValidationError):
        await _build_system_prompt(
            seeded["session"], seeded["ws"], seeded["foreign_brand"], None
        )


async def test_campaign_from_another_workspace_is_rejected(seeded):
    """Otherwise another tenant's positioning leaks into this tenant's prompt."""
    with pytest.raises(ValidationError):
        await _build_system_prompt(
            seeded["session"], seeded["ws"], None, seeded["foreign_campaign"]
        )


async def test_unknown_ids_are_rejected(seeded):
    with pytest.raises(ValidationError):
        await _build_system_prompt(seeded["session"], seeded["ws"], "no-such-brand", None)
    with pytest.raises(ValidationError):
        await _build_system_prompt(seeded["session"], seeded["ws"], None, "no-such-campaign")
