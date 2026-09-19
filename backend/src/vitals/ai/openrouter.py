"""A small OpenRouter client — one endpoint, and the failure modes that actually happen.

OpenRouter rather than a vendor SDK because the model is a *swappable part* here. The
brief is sixty words built from a digest Python already computed, so the difference
between frontier models on this task is small and the difference in price is not; being
able to change one environment variable and pay a tenth as much is worth more than any
SDK convenience. Nothing above this module knows which model wrote anything.

The error taxonomy is the point of the file. Three outcomes, because they want three
different responses from the caller:

  `Unavailable`  no key configured. Not an error — a deployment that has not set one
                 up. The brief falls back to its Python composition and says nothing
                 about it.
  `Refused`      the request was understood and rejected: unknown model slug, no
                 credit, content policy. Retrying sends the same request to the same
                 answer, so it does not retry.
  `Transient`    rate limited, or the provider fell over. Retried with backoff, then
                 given up on.

A daily brief that fails is not an incident — tomorrow's runs anyway — so nothing here
raises past `brief.py`, which treats all three as "compose it in Python instead".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from vitals.config import Settings
from vitals.logging import get_logger

log = get_logger(__name__)

# Sent as OpenRouter's attribution headers. They are optional, and they are what makes
# a request identifiable in the dashboard when you are trying to work out what spent
# your credit.
APP_TITLE = "Vitals"
APP_URL = "https://github.com/errnasty/vitals"

RETRY_STATUS = (408, 409, 429, 500, 502, 503, 504)
MAX_ATTEMPTS = 3
# Backoff between attempts. Short, because a cron job holding a Railway container
# awake for a minute of sleeping costs more than the call it is waiting on.
BACKOFF_S = (1.0, 3.0)


class AIError(RuntimeError):
    """Anything that stopped a completion coming back."""


class Unavailable(AIError):
    """No API key configured. The deployment simply has no model attached."""


class Refused(AIError):
    """The provider understood the request and declined it. Retrying changes nothing."""


class Transient(AIError):
    """Rate limited or briefly broken. Worth another attempt, but not forever."""


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    # OpenRouter reports this on accounts with usage accounting on; None otherwise.
    # Recorded rather than required, so the brief never depends on it.
    cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class OpenRouter:
    """Stateless; one httpx client per call.

    A held-open client is a connection pool, and a connection pool is outbound
    traffic — which is what Railway reads as "this container is busy". The sync cron
    runs four times a day; it should be asleep the rest of the time.
    """

    api_key: str
    base_url: str
    model: str
    max_output_tokens: int
    timeout_s: float
    # Low rather than zero: identical input should give near-identical output day to
    # day, so a change in the brief means a change in the data.
    temperature: float = 0.3

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenRouter:
        if not settings.openrouter_api_key:
            raise Unavailable(
                "OPENROUTER_API_KEY is unset — briefs will be composed in Python instead"
            )
        return cls(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url.rstrip("/"),
            model=settings.ai_model,
            max_output_tokens=settings.ai_max_output_tokens,
            timeout_s=settings.ai_timeout_s,
        )

    async def complete(self, *, system: str, user: str) -> Completion:
        """One chat completion, retried only where retrying can help."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_output_tokens,
            "temperature": self.temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": APP_URL,
            "X-Title": APP_TITLE,
        }

        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", json=payload, headers=headers
                    )
                return _parse(response, fallback_model=self.model)
            except Transient as exc:
                last = exc
            except httpx.TimeoutException as exc:
                last = Transient(f"timed out after {self.timeout_s}s")
                last.__cause__ = exc
            except httpx.HTTPError as exc:
                last = Transient(f"{type(exc).__name__}: {exc}")
                last.__cause__ = exc

            if attempt < len(BACKOFF_S):
                log.info("ai.retry", attempt=attempt + 1, reason=str(last))
                await asyncio.sleep(BACKOFF_S[attempt])

        raise last if last is not None else Transient("no attempt was made")


def _parse(response: httpx.Response, *, fallback_model: str) -> Completion:
    if response.status_code in RETRY_STATUS:
        raise Transient(f"HTTP {response.status_code}: {_message(response)}")
    if response.status_code >= 400:
        raise Refused(f"HTTP {response.status_code}: {_message(response)}")

    try:
        body = response.json()
    except ValueError as exc:
        raise Transient("response was not JSON") from exc

    # OpenRouter can return 200 with an error body when a provider fails mid-stream.
    if "error" in body and not body.get("choices"):
        raise Refused(str(body["error"].get("message", body["error"])))

    choices = body.get("choices") or []
    if not choices:
        raise Transient("no choices in the response")

    text = (choices[0].get("message") or {}).get("content") or ""
    if not text.strip():
        # An empty completion usually means the output cap cut it off before a word.
        raise Transient("the model returned an empty message")

    usage = body.get("usage") or {}
    return Completion(
        text=text.strip(),
        model=body.get("model") or fallback_model,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        cost_usd=_cost(usage),
    )


def _cost(usage: dict[str, object]) -> float | None:
    value = usage.get("cost")
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:  # pragma: no cover - defensive against shape drift
        return None


def _message(response: httpx.Response) -> str:
    """The provider's own explanation, which is usually the actionable part."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error or body)[:200]
