"""Rate governance for an unofficial API that fails fast and does not forgive.

The library retries 5xx and network errors, and deliberately does *not* retry 401 or
429 — so everything about staying under Garmin's limits has to live here. Four
mechanisms, each answering a different failure:

* **token bucket** — a hard ceiling on requests per minute, whatever the caller does;
* **jitter** — 1–3 s of randomness between calls, so a backfill does not look like a
  metronome to anything watching;
* **backoff with a persisted cooldown** — a 429 sets a cooldown that survives the
  process, because a Railway redeploy mid-cooldown must not restart the stampede;
* **circuit breaker** — after repeated failures, stop, mark the source degraded and let
  the app keep serving the data it already has.

The clock and sleep are injected, which is what makes all of this testable in
milliseconds rather than by waiting out real backoffs.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from vitals.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimits:
    """Conservative by default: steady state is ~25-40 requests a day."""

    requests_per_minute: float = 20.0
    burst: int = 5
    min_delay_s: float = 1.0
    max_delay_s: float = 3.0
    # Consecutive failures before the breaker opens and the run stops.
    failure_threshold: int = 5
    # 429 backoff: 5 min, 10, 20 ... capped. Long on purpose — a rate limit is a
    # warning, and racing back to the API is how a warning becomes a lockout.
    backoff_base_s: float = 300.0
    backoff_max_s: float = 6 * 3600.0
    # Hard ceiling per run. A bug that loops must not become 10,000 requests.
    max_requests: int = 2000


class GovernorError(RuntimeError):
    """Base class for "stop making requests"."""


class CircuitOpen(GovernorError):
    """The source is in cooldown or has failed too often. Try again later."""


class BudgetExhausted(GovernorError):
    """This run hit its request ceiling."""


@dataclass
class GovernorState:
    """The part that must outlive the process, persisted on `source_connection`."""

    consecutive_failures: int = 0
    cooldown_until: datetime | None = None

    def cooling_down(self, now: datetime) -> bool:
        return self.cooldown_until is not None and now < self.cooldown_until


@dataclass
class RateGovernor:
    limits: RateLimits = field(default_factory=RateLimits)
    state: GovernorState = field(default_factory=GovernorState)
    # Injected so tests run in milliseconds and do not depend on wall-clock timing.
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    jitter: Callable[[float, float], float] = random.uniform

    requests_made: int = field(default=0, init=False)
    _tokens: float = field(init=False, default=0.0)
    _last_refill: float = field(init=False, default=0.0)
    _started: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.limits.burst)
        self._last_refill = self.monotonic()

    def check_ready(self) -> None:
        """Raise if no request may be made at all. Consumes nothing.

        Called before connecting, not just before each request: resuming a session
        already costs a token refresh over the network, and a run that is in cooldown
        should not spend even that.
        """
        now = self.now()
        if self.state.cooling_down(now):
            remaining = int((self.state.cooldown_until - now).total_seconds())  # type: ignore[operator]
            raise CircuitOpen(f"in cooldown for another {remaining}s after a rate limit")
        if self.state.consecutive_failures >= self.limits.failure_threshold:
            raise CircuitOpen(
                f"{self.state.consecutive_failures} consecutive failures; "
                "circuit open, not making further requests"
            )

    async def acquire(self) -> None:
        """Block until one request may be made, or refuse outright."""
        self.check_ready()
        if self.requests_made >= self.limits.max_requests:
            raise BudgetExhausted(f"request budget of {self.limits.max_requests} exhausted")

        if self._started:
            await self.sleep(self.jitter(self.limits.min_delay_s, self.limits.max_delay_s))
        self._started = True

        await self._take_token()
        self.requests_made += 1

    async def _take_token(self) -> None:
        rate = self.limits.requests_per_minute / 60.0
        while True:
            current = self.monotonic()
            elapsed = current - self._last_refill
            self._last_refill = current
            self._tokens = min(float(self.limits.burst), self._tokens + elapsed * rate)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            await self.sleep((1.0 - self._tokens) / rate)

    def record_success(self) -> None:
        self.state.consecutive_failures = 0
        self.state.cooldown_until = None

    def record_failure(self) -> None:
        self.state.consecutive_failures += 1

    def record_rate_limited(self) -> datetime:
        """Back off hard, and remember it across restarts."""
        self.state.consecutive_failures += 1
        exponent = max(0, self.state.consecutive_failures - 1)
        delay = min(self.limits.backoff_base_s * (2**exponent), self.limits.backoff_max_s)
        # Jitter the cooldown too: identical backoff from several processes is itself
        # a thundering herd, and phase 12 will have several.
        delay *= self.jitter(0.9, 1.2)
        until = self.now() + timedelta(seconds=delay)
        self.state.cooldown_until = until
        log.warning(
            "garmin.rate_limited",
            cooldown_s=int(delay),
            until=until.isoformat(),
            consecutive_failures=self.state.consecutive_failures,
        )
        return until
