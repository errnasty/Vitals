"""The two gates that keep a public URL from being an open health-data endpoint."""

from __future__ import annotations

import pytest

from tests.support import EMAIL, PROJECT_URL, local_settings
from vitals.auth.errors import NotAllowed
from vitals.auth.policy import AuthNotReady, assert_auth_ready, check_allowed
from vitals.auth.verifier import TokenVerifier


async def _principal(**overrides: object):
    from tests.support import hs256

    return await TokenVerifier(local_settings()).verify(hs256(**overrides))


async def test_allowlisted_address_is_accepted() -> None:
    principal = await _principal()
    check_allowed(local_settings(allowed_emails=[EMAIL]), principal)


async def test_allowlist_is_case_insensitive() -> None:
    principal = await _principal(email="Owner@Example.com")
    check_allowed(local_settings(allowed_emails=["OWNER@example.COM"]), principal)


async def test_other_accounts_are_rejected() -> None:
    """Supabase sign-ups are disabled; this is the gate that does not depend on that."""
    principal = await _principal(email="stranger@example.com")
    with pytest.raises(NotAllowed):
        check_allowed(local_settings(allowed_emails=[EMAIL]), principal)


async def test_token_without_an_email_is_rejected_when_an_allowlist_exists() -> None:
    principal = await _principal(email=None)
    with pytest.raises(NotAllowed):
        check_allowed(local_settings(allowed_emails=[EMAIL]), principal)


def test_allowlist_parses_a_comma_separated_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    from vitals.config import Settings

    monkeypatch.setenv("VITALS_ALLOWED_EMAILS", "One@Example.com, two@example.com")
    assert Settings().allowed_emails == ["one@example.com", "two@example.com"]


def test_local_may_run_with_nothing_configured() -> None:
    assert_auth_ready(local_settings(supabase_jwt_secret=None))


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "VITALS_ALLOWED_EMAILS is empty"),
        ({"supabase_jwt_secret": None, "allowed_emails": [EMAIL]}, "neither SUPABASE_URL"),
        (
            {"auth_disabled": True, "allowed_emails": [EMAIL], "supabase_url": PROJECT_URL},
            "VITALS_AUTH_DISABLED",
        ),
    ],
)
def test_production_refuses_to_start_when_misconfigured(
    overrides: dict[str, object], expected: str
) -> None:
    """Fail the deploy, rather than serve health data unprotected on a public URL."""
    settings = local_settings(environment="production", **overrides)
    with pytest.raises(AuthNotReady, match=expected):
        assert_auth_ready(settings)


def test_production_starts_when_configured() -> None:
    assert_auth_ready(
        local_settings(environment="production", supabase_url=PROJECT_URL, allowed_emails=[EMAIL])
    )
