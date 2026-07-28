"""The provider abstraction and the Sakana client.

Network calls are stubbed: these pin the decisions the client makes about a
provider response, not Sakana's uptime.
"""

from __future__ import annotations

import httpx
import pytest

from packages.shared_core.ai import (
    BaseAIProvider,
    ChatMessage,
    MockLLMClient,
    SakanaClient,
    get_llm_client,
)
from packages.shared_core.ai.errors import is_quota_error, raise_for_status
from packages.shared_core.ai.retry import MAX_BACKOFF_SECONDS, backoff_delay
from packages.shared_core.config import get_settings
from packages.shared_core.exceptions import (
    LLMError,
    LLMNotConfiguredError,
    LLMRateLimitError,
)

OK_BODY = {
    "model": "fugu",
    "choices": [{"message": {"role": "assistant", "content": "MIGRATION_OK"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 3},
}


def _client(**kw) -> SakanaClient:
    return SakanaClient(api_key="test-key", max_retries=kw.pop("max_retries", 1), **kw)


def _stub_post(monkeypatch, responses: list[httpx.Response]):
    """Serve the given responses in order; record how many calls were made."""
    calls = {"n": 0}

    async def fake_post(self, url, **kwargs):  # noqa: ARG001
        index = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[index]

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


def _response(status: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status, json=json_body, request=httpx.Request("POST", "http://x"))


# ---- contract -----------------------------------------------------------


def test_both_providers_implement_the_base_contract():
    assert issubclass(SakanaClient, BaseAIProvider)
    assert issubclass(MockLLMClient, BaseAIProvider)


def test_factory_returns_the_abstraction_not_a_vendor_type(monkeypatch):
    """Business logic must only ever see a BaseAIProvider."""
    monkeypatch.delenv("SAKANA_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_MOCK_LLM", "true")
    get_settings.cache_clear()
    try:
        assert isinstance(get_llm_client(), BaseAIProvider)
    finally:
        get_settings.cache_clear()


def test_factory_builds_sakana_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("SAKANA_API_KEY", "sk-live-xyz")
    get_settings.cache_clear()
    try:
        client = get_llm_client()
        assert isinstance(client, SakanaClient)
        assert client.provider == "sakana"
        assert client.base_url == "https://api.sakana.ai/v1"
        assert client.model == "fugu"
    finally:
        get_settings.cache_clear()


def test_factory_refuses_when_no_key_and_no_mock(monkeypatch):
    monkeypatch.delenv("SAKANA_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_MOCK_LLM", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(LLMNotConfiguredError):
            get_llm_client()
    finally:
        get_settings.cache_clear()


# ---- request validation --------------------------------------------------


async def test_empty_conversation_is_rejected_before_any_request(monkeypatch):
    calls = _stub_post(monkeypatch, [_response(200, OK_BODY)])
    with pytest.raises(LLMError):
        await _client().complete([])
    assert calls["n"] == 0, "a malformed request must not reach the provider"


async def test_unsupported_role_is_rejected(monkeypatch):
    _stub_post(monkeypatch, [_response(200, OK_BODY)])
    with pytest.raises(LLMError):
        await _client().complete([ChatMessage(role="root", content="hi")])


async def test_blank_content_is_rejected(monkeypatch):
    _stub_post(monkeypatch, [_response(200, OK_BODY)])
    with pytest.raises(LLMError):
        await _client().complete([ChatMessage(role="user", content="   ")])


# ---- responses -----------------------------------------------------------


async def test_successful_completion_is_normalised(monkeypatch):
    _stub_post(monkeypatch, [_response(200, OK_BODY)])
    result = await _client().complete([ChatMessage(role="user", content="hi")])
    assert result.content == "MIGRATION_OK"
    assert result.provider == "sakana"
    assert result.prompt_tokens == 11
    assert result.total_tokens == 14


async def test_a_200_with_no_choices_is_a_provider_error(monkeypatch):
    _stub_post(monkeypatch, [_response(200, {"model": "fugu"})])
    with pytest.raises(LLMError):
        await _client().complete([ChatMessage(role="user", content="hi")])


async def test_a_200_with_empty_content_is_a_provider_error(monkeypatch):
    """Returning "" to the user would look like the product simply failed."""
    body = {"choices": [{"message": {"content": "  "}}]}
    _stub_post(monkeypatch, [_response(200, body)])
    with pytest.raises(LLMError):
        await _client().complete([ChatMessage(role="user", content="hi")])


# ---- error mapping -------------------------------------------------------


async def test_credentials_rejected_is_not_retried(monkeypatch):
    calls = _stub_post(monkeypatch, [_response(401, {"error": {"message": "bad key"}})])
    with pytest.raises(LLMNotConfiguredError):
        await _client(max_retries=3).complete([ChatMessage(role="user", content="hi")])
    assert calls["n"] == 1


async def test_quota_exhausted_is_not_retried(monkeypatch):
    """Sakana answers 429 usage_limit_reached when a key has no subscription.

    It is a billing state, not a burst limit, so retrying spends the caller's
    whole timeout to arrive at the same answer.
    """
    body = {
        "error": {
            "message": "No active subscription. Subscribe at https://console.sakana.ai/billing",
            "type": "usage_limit_reached",
        }
    }
    calls = _stub_post(monkeypatch, [_response(429, body)])
    with pytest.raises(LLMNotConfiguredError) as err:
        await _client(max_retries=3).complete([ChatMessage(role="user", content="hi")])
    assert calls["n"] == 1
    assert "subscription" in str(err.value).lower()


async def test_a_plain_429_is_retried_then_surfaces_as_rate_limited(monkeypatch):
    body = {"error": {"message": "slow down", "type": "rate_limit_exceeded"}}
    calls = _stub_post(monkeypatch, [_response(429, body)])
    with pytest.raises(LLMRateLimitError):
        await _client(max_retries=1).complete([ChatMessage(role="user", content="hi")])
    assert calls["n"] == 2, "one initial attempt plus one retry"


async def test_transient_5xx_recovers_on_retry(monkeypatch):
    _stub_post(
        monkeypatch,
        [_response(503, {"error": {"message": "upstream"}}), _response(200, OK_BODY)],
    )
    result = await _client(max_retries=2).complete([ChatMessage(role="user", content="hi")])
    assert result.content == "MIGRATION_OK"


async def test_unknown_model_is_not_retried(monkeypatch):
    calls = _stub_post(monkeypatch, [_response(404, {"error": {"message": "no such model"}})])
    with pytest.raises(LLMError):
        await _client(max_retries=3).complete([ChatMessage(role="user", content="hi")])
    assert calls["n"] == 1


def test_quota_detection():
    assert is_quota_error({"error": {"type": "usage_limit_reached"}})
    assert is_quota_error({"error": {"type": "insufficient_quota"}})
    assert not is_quota_error({"error": {"type": "rate_limit_exceeded"}})
    assert not is_quota_error({"nonsense": True})
    assert not is_quota_error("not a dict")


def test_retryable_status_returns_rather_than_raising():
    # 503 is retryable, so the mapper must let the caller continue.
    raise_for_status("sakana", 503, {"error": {"message": "later"}})


# ---- retry policy --------------------------------------------------------


def test_backoff_is_capped_and_jittered():
    delays = {backoff_delay(5) for _ in range(20)}
    assert len(delays) > 1, "identical delays would synchronise every worker"
    assert all(d <= MAX_BACKOFF_SECONDS for d in delays)


def test_retry_after_header_is_honoured_and_capped():
    assert backoff_delay(0, "2") == 2.0
    assert backoff_delay(0, "9999") == MAX_BACKOFF_SECONDS
    # A malformed header must not crash the retry path.
    assert 0 < backoff_delay(0, "soon") <= MAX_BACKOFF_SECONDS


# ---- config safety -------------------------------------------------------


def test_client_refuses_to_be_built_without_a_key():
    with pytest.raises(LLMError):
        SakanaClient(api_key="")


def test_invalid_reasoning_effort_is_dropped_not_forwarded():
    """The API rejects any value outside the documented set."""
    assert _client(reasoning_effort="turbo").reasoning_effort is None
    assert _client(reasoning_effort="xhigh").reasoning_effort == "xhigh"


def test_reasoning_effort_reaches_the_payload():
    payload = _client(reasoning_effort="high")._payload(
        [ChatMessage(role="user", content="hi")], stream=False, temperature=0.5, model=None
    )
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["model"] == "fugu"


def test_no_reasoning_key_when_unset():
    payload = _client()._payload(
        [ChatMessage(role="user", content="hi")], stream=False, temperature=0.5, model=None
    )
    assert "reasoning" not in payload


def test_api_key_is_sent_as_a_bearer_token():
    assert _client()._headers()["Authorization"] == "Bearer test-key"
