"""The contract every AI provider implements.

Business logic depends on this class and never on a concrete vendor client.
``routers/chat.py`` holds a ``BaseAIProvider``; whether that is Sakana or the
mock is decided once, in :mod:`packages.shared_core.ai.factory`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from packages.shared_core.ai.types import VALID_ROLES, ChatMessage, Completion
from packages.shared_core.exceptions import LLMError


class BaseAIProvider(ABC):
    """An async chat-completion provider."""

    #: Short identifier recorded on completions and used in log lines.
    provider: str = "base"

    #: The model this instance talks to.
    model: str = ""

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> Completion:
        """Generate one complete response."""

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield content deltas as they arrive.

        Declared as a normal method returning an async iterator rather than as
        an ``async def``: an implementation written with ``yield`` is already a
        function returning an async generator, and marking it ``async`` here
        would force every caller into an extra ``await``.
        """

    # ---- shared helpers -------------------------------------------------

    @staticmethod
    def validate_messages(messages: list[ChatMessage]) -> None:
        """Reject malformed conversations before they reach the network.

        Catching this locally turns a wasted round trip and an opaque provider
        400 into an immediate, specific error.
        """
        if not messages:
            raise LLMError("Cannot generate from an empty conversation.")
        for index, message in enumerate(messages):
            if message.role not in VALID_ROLES:
                raise LLMError(
                    f"Message {index} has unsupported role {message.role!r}.",
                    details={"role": message.role},
                )
            if not isinstance(message.content, str) or not message.content.strip():
                raise LLMError(f"Message {index} has empty content.")


__all__ = ["BaseAIProvider"]
