"""Rate governance, with time injected so the whole file runs in milliseconds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vitals.sources.garmin.governor import (
    BudgetExhausted,
    CircuitOpen,
    GovernorState,
    RateGovernor,
    RateLimits,
)

START = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


class FakeClock:
    """Sleeping advances time instead of passing it."""

    def __init__(self) -> None:
        self.elapsed = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> datetime:
        return START + timedelta(seconds=self.elapsed)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed += seconds


def _governor(clock: FakeClock, limits: RateLimits | None = None, **kwargs: object) -> RateGovernor:
    return RateGovernor(
        limits=limits or RateLimits(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        now=clock.now,
        # Deterministic "jitter": always the midpoint of the range.
        jitter=lambda lo, hi: (lo + hi) / 2,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_first_request_is_not_delayed() -> None:
    clock = FakeClock()
    governor = _governor(clock)

    await governor.acquire()

    assert clock.sleeps == []
    assert governor.requests_made == 1


async def test_calls_are_spaced_by_jitter() -> None:
    """A metronome is a signature; 1-3s of randomness between calls is not."""
    clock = FakeClock()
    governor = _governor(clock)

    for _ in range(3):
        await governor.acquire()

    assert clock.sleeps == [2.0, 2.0]  # midpoint of min_delay_s..max_delay_s


async def test_burst_is_capped_by_the_token_bucket() -> None:
    clock = FakeClock()
    # 60/min = one token per second, with a burst of 3.
    governor = _governor(
        clock, RateLimits(requests_per_minute=60, burst=3, min_delay_s=0, max_delay_s=0)
    )

    for _ in range(3):
        await governor.acquire()
    assert clock.sleeps == [0.0, 0.0]  # burst absorbed, no bucket wait

    await governor.acquire()
    assert clock.sleeps[-1] == pytest.approx(1.0, abs=0.01)  # had to wait for a token


async def test_sustained_rate_respects_the_limit() -> None:
    clock = FakeClock()
    governor = _governor(
        clock, RateLimits(requests_per_minute=20, burst=1, min_delay_s=0, max_delay_s=0)
    )

    for _ in range(21):
        await governor.acquire()

    # 20/min means 3s apart; 20 requests after the first take at least a minute.
    assert clock.elapsed >= 60.0


async def test_a_persisted_cooldown_survives_the_process() -> None:
    """A redeploy mid-cooldown must not restart the stampede."""
    clock = FakeClock()
    state = GovernorState(cooldown_until=clock.now() + timedelta(minutes=5))
    governor = _governor(clock, state=state)

    with pytest.raises(CircuitOpen, match="cooldown"):
        await governor.acquire()
    assert governor.requests_made == 0


async def test_cooldown_expires() -> None:
    clock = FakeClock()
    state = GovernorState(cooldown_until=clock.now() + timedelta(seconds=30))
    governor = _governor(clock, state=state)

    await clock.sleep(31)
    await governor.acquire()

    assert governor.requests_made == 1


async def test_circuit_opens_after_repeated_failures() -> None:
    clock = FakeClock()
    governor = _governor(clock, RateLimits(failure_threshold=3))

    for _ in range(3):
        governor.record_failure()

    with pytest.raises(CircuitOpen, match="circuit open"):
        await governor.acquire()


async def test_success_resets_the_breaker() -> None:
    clock = FakeClock()
    governor = _governor(clock, RateLimits(failure_threshold=2))
    governor.record_failure()
    governor.record_success()
    governor.record_failure()

    await governor.acquire()  # one failure short of the threshold


async def test_rate_limit_backs_off_exponentially_and_caps() -> None:
    clock = FakeClock()
    governor = _governor(
        clock, RateLimits(backoff_base_s=300, backoff_max_s=3600, failure_threshold=99)
    )

    delays = []
    for _ in range(6):
        until = governor.record_rate_limited()
        delays.append((until - clock.now()).total_seconds())
        governor.state.cooldown_until = None  # so the next call is measurable

    assert delays[0] == pytest.approx(300 * 1.05, rel=0.01)
    assert delays[1] == pytest.approx(600 * 1.05, rel=0.01)
    assert delays[2] == pytest.approx(1200 * 1.05, rel=0.01)
    assert delays[-1] == pytest.approx(3600 * 1.05, rel=0.01)  # capped


async def test_a_runaway_loop_hits_the_request_budget() -> None:
    clock = FakeClock()
    governor = _governor(clock, RateLimits(max_requests=5, min_delay_s=0, max_delay_s=0, burst=100))

    for _ in range(5):
        await governor.acquire()

    with pytest.raises(BudgetExhausted):
        await governor.acquire()
