"""Brand and campaign grounding of the chat system prompt.

Grounding is the whole product: without it the assistant is a generic chatbot
that ignores the brand voice and campaign objective the user configured.

The failure mode these tests exist to prevent is the quiet one. An unresolved
brand or campaign id used to be skipped, so the request succeeded, the answer
came back, and nothing in it reflected the selection. Rejecting the id makes
that visible instead.
"""

from __future__ import annotations

import pytest

from packages.shared_core.db.models import Brand, Campaign, User, Workspace
from packages.shared_core.exceptions import ValidationError
from services.identity_service.routers.chat import (
    BASE_SYSTEM_PROMPT,
    _build_system_prompt,
)


@pytest.fixture
async def seeded(db_session):
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
        tone="Direct, warm, no jargon",
        audience="Independent retailers",
        keywords="payments, retail",
    )
    campaign = Campaign(
        workspace_id=ws.id,
        name="Series A launch",
        objective="Drive demo signups from retailers",
        status="active",
        channel="twitter",
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
    # Brand voice first, then the campaign objective it must serve.
    assert prompt.index("Acme Voice") < prompt.index("Series A launch")


async def test_grounding_is_wrapped_as_data_not_instructions(seeded):
    """Brand text is attacker-influenced; it must stay inside its tag."""
    prompt = await _build_system_prompt(
        seeded["session"], seeded["ws"], seeded["brand"], seeded["campaign"]
    )
    assert "<brand>" in prompt and "</brand>" in prompt
    assert "<campaign>" in prompt and "</campaign>" in prompt


async def test_brand_from_another_workspace_is_rejected(seeded):
    with pytest.raises(ValidationError):
        await _build_system_prompt(seeded["session"], seeded["ws"], seeded["foreign_brand"], None)


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
