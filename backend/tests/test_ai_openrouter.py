"""The client's job is to turn provider failures into the three the caller can act on."""

from __future__ import annotations

import httpx
import pytest

from vitals.ai import openrouter
from vitals.config import Settings

SUCCESS = {
    "model": "anthropic/claude-sonnet-5",
    "choices": [{"message": {"role": "assistant", "content": "  Balanced at 78.  "}}],
    "usage": {"prompt_tokens": 812, "completion_tokens": 47, "cost": 0.00121},
}


def client(**overrides) -> openrouter.OpenRouter:
    base = {
        "api_key": "stub",
        "base_url": "https://stub/api/v1",
        "model": "anthropic/claude-sonnet-5",
        "max_output_tokens": 300,
        "timeout_s": 5.0,
    }
    base.update(overrides)
    return openrouter.OpenRouter(**base)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch):
    """Replace the network with a scripted list of responses, recording each request."""
    calls: list[dict] = []

    def install(*responses: httpx.Response | Exception):
        queue = list(responses)

        async def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(httpx.AsyncClient, "post", post)
        return calls

    return install


async def test_a_completion_comes_back_stripped_and_accounted(transport) -> None:
    transport(httpx.Response(200, json=SUCCESS))
    result = await client().complete(system="rules", user="digest")
    assert result.text == "Balanced at 78."
    assert result.prompt_tokens == 812
    assert result.completion_tokens == 47
    assert result.total_tokens == 859
    assert result.cost_usd == pytest.approx(0.00121)


async def test_the_request_carries_the_model_and_the_cap(transport) -> None:
    calls = transport(httpx.Response(200, json=SUCCESS))
    await client(max_output_tokens=120).complete(system="rules", user="digest")
    body = calls[0]["json"]
    assert body["model"] == "anthropic/claude-sonnet-5"
    assert body["max_tokens"] == 120
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert calls[0]["headers"]["Authorization"] == "Bearer stub"


async def test_no_key_is_not_an_error_it_is_a_deployment_choice() -> None:
    settings = Settings(environment="local", auth_jwt_secret="x" * 32, openrouter_api_key=None)
    with pytest.raises(openrouter.Unavailable):
        openrouter.OpenRouter.from_settings(settings)


async def test_a_rejected_request_is_not_retried(transport) -> None:
    """An unknown model slug answers the same way however many times you ask."""
    calls = transport(
        httpx.Response(400, json={"error": {"message": "not a valid model id"}}),
    )
    with pytest.raises(openrouter.Refused, match="not a valid model id"):
        await client().complete(system="rules", user="digest")
    assert len(calls) == 1


async def test_rate_limiting_is_retried_then_succeeds(transport, monkeypatch) -> None:
    monkeypatch.setattr(openrouter, "BACKOFF_S", (0.0, 0.0))
    calls = transport(
        httpx.Response(429, json={"error": {"message": "slow down"}}),
        httpx.Response(200, json=SUCCESS),
    )
    result = await client().complete(system="rules", user="digest")
    assert result.text == "Balanced at 78."
    assert len(calls) == 2


async def test_retries_are_bounded(transport, monkeypatch) -> None:
    """A cron holding a Railway container awake costs more than the call it waits on."""
    monkeypatch.setattr(openrouter, "BACKOFF_S", (0.0, 0.0))
    calls = transport(*[httpx.Response(503, text="upstream down")] * openrouter.MAX_ATTEMPTS)
    with pytest.raises(openrouter.Transient):
        await client().complete(system="rules", user="digest")
    assert len(calls) == openrouter.MAX_ATTEMPTS


async def test_a_timeout_is_transient(transport, monkeypatch) -> None:
    monkeypatch.setattr(openrouter, "BACKOFF_S", (0.0, 0.0))
    transport(*[httpx.TimeoutException("too slow")] * openrouter.MAX_ATTEMPTS)
    with pytest.raises(openrouter.Transient, match="timed out"):
        await client().complete(system="rules", user="digest")


async def test_a_200_carrying_an_error_body_is_a_refusal(transport) -> None:
    """OpenRouter can answer 200 when the provider behind it fails."""
    transport(httpx.Response(200, json={"error": {"message": "no credit remaining"}}))
    with pytest.raises(openrouter.Refused, match="no credit"):
        await client().complete(system="rules", user="digest")


async def test_an_empty_completion_is_transient(transport, monkeypatch) -> None:
    monkeypatch.setattr(openrouter, "BACKOFF_S", (0.0, 0.0))
    empty = {"model": "m", "choices": [{"message": {"content": "   "}}], "usage": {}}
    transport(*[httpx.Response(200, json=empty)] * openrouter.MAX_ATTEMPTS)
    with pytest.raises(openrouter.Transient, match="empty"):
        await client().complete(system="rules", user="digest")


async def test_usage_without_a_cost_is_not_a_failure(transport) -> None:
    """Cost accounting is an account setting; the brief never depends on it."""
    body = dict(SUCCESS, usage={"prompt_tokens": 10, "completion_tokens": 5})
    transport(httpx.Response(200, json=body))
    result = await client().complete(system="rules", user="digest")
    assert result.cost_usd is None
    assert result.total_tokens == 15
