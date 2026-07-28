"""AI provider package.

The public surface of this package is provider-neutral. Import from here:

    from packages.shared_core.ai import ChatMessage, get_llm_client

Concrete clients (``sakana_client``, ``mock_client``) are implementation
detail and should not be imported by business logic.
"""

from __future__ import annotations

from packages.shared_core.ai.base import BaseAIProvider
from packages.shared_core.ai.errors import (
    LLMError,
    LLMNotConfiguredError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from packages.shared_core.ai.factory import get_llm_client
from packages.shared_core.ai.mock_client import MockLLMClient
from packages.shared_core.ai.sakana_client import SakanaClient
from packages.shared_core.ai.types import ChatMessage, Completion, Role

__all__ = [
    "BaseAIProvider",
    "ChatMessage",
    "Completion",
    "LLMError",
    "LLMNotConfiguredError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "MockLLMClient",
    "Role",
    "SakanaClient",
    "get_llm_client",
]
