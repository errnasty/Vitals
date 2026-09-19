"""The two-halves login, which is what makes connecting from a phone possible at all.

`prompt_mfa` blocks inside `login()` until a callback produces a code — fine for a
terminal, impossible for a web request, because the HTTP response has to go back
before the user can read their code. These cover the alternative: hand the
half-finished login out, store it, pick it up later.
"""

from __future__ import annotations

from typing import Any

import pytest
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from vitals.sources.garmin import client as mod
from vitals.sources.garmin.client import (
    GarminClient,
    GarminError,
    MFARequired,
    NeedsReauth,
    RateLimited,
    begin_login,
    finish_login,
)
from vitals.sources.garmin.governor import RateGovernor, RateLimits

FAST = RateLimits(min_delay_s=0, max_delay_s=0, burst=10_000, requests_per_minute=1e6)
STATE = {"ticket": "abc123"}


class FakeGarmin:
    """Enough of `garminconnect.Garmin` for the two entry points under test."""

    instances: list[FakeGarmin] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.resumed: tuple[dict[str, Any], str] | None = None
        FakeGarmin.instances.append(self)

    # Set per test.
    login_result: Any = (None, None)
    login_error: Exception | None = None
    resume_error: Exception | None = None

    def login(self, tokenstore: str | None = None) -> Any:
        if self.login_error:
            raise self.login_error
        return self.login_result

    def resume_login(self, client_state: dict[str, Any], code: str) -> Any:
        if self.resume_error:
            raise self.resume_error
        self.resumed = (client_state, code)
        return ("ok", None)


@pytest.fixture(autouse=True)
def fake(monkeypatch: pytest.MonkeyPatch):
    FakeGarmin.instances = []
    FakeGarmin.login_result = (None, None)
    FakeGarmin.login_error = None
    FakeGarmin.resume_error = None
    monkeypatch.setattr(mod, "Garmin", FakeGarmin)
    return FakeGarmin


def governor() -> RateGovernor:
    return RateGovernor(limits=FAST)


async def test_a_login_with_no_mfa_returns_a_client(fake) -> None:
    fake.login_result = (None, None)
    result = await begin_login("a@b.c", "pw", governor=governor())
    assert isinstance(result, GarminClient)


async def test_an_mfa_demand_returns_the_resumable_state(fake) -> None:
    """Returned, not waited on — the response has to reach the user first."""
    fake.login_result = (mod.NEEDS_MFA, STATE)
    result = await begin_login("a@b.c", "pw", governor=governor())
    assert isinstance(result, MFARequired)
    assert result.client_state == STATE


async def test_begin_asks_the_library_to_return_rather_than_prompt(fake) -> None:
    fake.login_result = (None, None)
    await begin_login("a@b.c", "pw", governor=governor())
    assert fake.instances[-1].kwargs["return_on_mfa"] is True
    assert fake.instances[-1].kwargs["verify_login"] is True


async def test_a_demand_with_no_state_is_an_error_not_a_dead_end(fake) -> None:
    """Without resumable state the user would be stranded on a code screen forever."""
    fake.login_result = (mod.NEEDS_MFA, None)
    with pytest.raises(GarminError, match="no resumable state"):
        await begin_login("a@b.c", "pw", governor=governor())


async def test_finish_resumes_on_a_fresh_client(fake) -> None:
    """The two halves are different requests, and may be different processes."""
    result = await finish_login("a@b.c", "pw", STATE, "123456", governor=governor())
    assert isinstance(result, GarminClient)
    assert fake.instances[-1].resumed == (STATE, "123456")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (GarminConnectAuthenticationError("bad password"), NeedsReauth),
        (GarminConnectTooManyRequestsError("slow down"), RateLimited),
        (GarminConnectConnectionError("dns"), GarminError),
    ],
)
async def test_begin_maps_library_failures_to_ours(fake, error, expected) -> None:
    fake.login_error = error
    with pytest.raises(expected):
        await begin_login("a@b.c", "pw", governor=governor())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (GarminConnectAuthenticationError("wrong code"), NeedsReauth),
        (GarminConnectTooManyRequestsError("slow down"), RateLimited),
        (GarminConnectConnectionError("dns"), GarminError),
    ],
)
async def test_finish_maps_library_failures_to_ours(fake, error, expected) -> None:
    fake.resume_error = error
    with pytest.raises(expected):
        await finish_login("a@b.c", "pw", STATE, "123456", governor=governor())


async def test_rate_limiting_is_recorded_against_the_governor(fake) -> None:
    """The circuit that protects the account has to hear about it."""
    fake.login_error = GarminConnectTooManyRequestsError("slow down")
    gov = governor()
    with pytest.raises(RateLimited):
        await begin_login("a@b.c", "pw", governor=gov)
    assert gov.state.consecutive_failures == 1
    assert gov.state.cooldown_until is not None
