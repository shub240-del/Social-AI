"""Provider-neutral request and response types.

Nothing in here mentions a vendor. These are the only AI shapes the rest of the
application is allowed to see, which is what makes swapping the provider a
change confined to this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]

VALID_ROLES: frozenset[str] = frozenset({"system", "user", "assistant"})


@dataclass(slots=True)
class ChatMessage:
    """One turn of a conversation."""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class Completion:
    """A finished generation, normalised across providers."""

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    provider: str = "unknown"
    #: The untouched provider payload. Useful for debugging; never relied on by
    #: business logic, because its shape is vendor specific.
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


__all__ = ["VALID_ROLES", "ChatMessage", "Completion", "Role"]
