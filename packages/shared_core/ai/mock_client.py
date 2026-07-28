"""Deterministic provider used for development, tests and CI.

Kept deliberately: it is what lets the whole product flow -- conversations,
persistence, RBAC, streaming -- be exercised without credentials or spend. The
settings guard refuses to boot production with it enabled, so it cannot
silently serve canned text to real users.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from packages.shared_core.ai.base import BaseAIProvider
from packages.shared_core.ai.types import ChatMessage, Completion


class MockLLMClient(BaseAIProvider):
    """Canned responses that always contain the word "mock".

    That word is load-bearing: ``tests/post_deploy_verify.py`` asserts a
    production deployment's output does *not* contain it, which turns an
    accidentally mock-configured production deploy into a failed verification
    rather than a plausible-looking but worthless product.
    """

    provider = "mock"

    def __init__(self, model: str = "mock/social-ai") -> None:
        self.model = model

    def _reply(self, messages: list[ChatMessage]) -> str:
        prompt = next(
            (m.content for m in reversed(messages) if m.role == "user"), "your request"
        )
        trimmed = prompt.strip()[:180]
        return (
            f"[mock completion] Here is a draft responding to: {trimmed}\n\n"
            "1. Lead with the outcome, not the feature.\n"
            "2. Keep it under two sentences.\n"
            "3. Close with one clear call to action.\n\n"
            "Set SAKANA_API_KEY and ALLOW_MOCK_LLM=false for real generations."
        )

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        model: str | None = None,
        **_: Any,
    ) -> Completion:
        started = time.perf_counter()
        await asyncio.sleep(0)  # keep the call genuinely awaitable
        text = self._reply(messages)
        return Completion(
            content=text,
            model=model or self.model,
            prompt_tokens=sum(len(m.content.split()) for m in messages),
            completion_tokens=len(text.split()),
            latency_ms=int((time.perf_counter() - started) * 1000),
            provider=self.provider,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        model: str | None = None,
        **_: Any,
    ) -> AsyncIterator[str]:
        for word in self._reply(messages).split(" "):
            await asyncio.sleep(0)
            yield word + " "


__all__ = ["MockLLMClient"]
