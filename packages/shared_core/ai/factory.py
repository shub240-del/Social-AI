"""The single place that decides which provider the application uses.

Business logic calls :func:`get_llm_client` and receives a
:class:`~packages.shared_core.ai.base.BaseAIProvider`. Nothing outside this
module names a concrete vendor, so adding or replacing a provider is a change
to this file plus one client module.
"""

from __future__ import annotations

import logging

from packages.shared_core.ai.base import BaseAIProvider
from packages.shared_core.ai.mock_client import MockLLMClient
from packages.shared_core.ai.sakana_client import SakanaClient
from packages.shared_core.config import get_settings
from packages.shared_core.exceptions import LLMNotConfiguredError

logger = logging.getLogger(__name__)


def get_llm_client() -> BaseAIProvider:
    """Build the configured provider.

    Production can only ever reach the real client: the settings guard refuses
    to boot when ``ALLOW_MOCK_LLM`` is true or the API key is absent.
    """
    settings = get_settings()

    if settings.llm_enabled:
        return SakanaClient(
            api_key=settings.sakana_api_key or "",
            base_url=settings.sakana_api_base_url,
            model=settings.default_llm_model,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            max_output_tokens=settings.llm_max_output_tokens,
            reasoning_effort=settings.llm_reasoning_effort,
        )

    if settings.allow_mock_llm:
        logger.warning("no SAKANA_API_KEY configured; using the mock provider")
        return MockLLMClient()

    raise LLMNotConfiguredError(
        "SAKANA_API_KEY is not set and the mock provider is disabled."
    )


__all__ = ["get_llm_client"]
