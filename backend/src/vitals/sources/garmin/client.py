"""Async wrapper around `python-garminconnect`, with the token round-trip that matters.

Two things this file exists to get right.

**Tokens survive the container.** The library caches tokens to a file; Railway wipes the
filesystem on every redeploy. Left alone, each deploy would run a fresh SSO login from a
datacenter IP — the exact path to a locked account. So tokens are loaded from the
encrypted vault as *inline JSON* (`login()` accepts a JSON string directly) and read back
out of the client with `dumps()` after every run. The library refreshes the DI token
before expiry and only writes it to disk when it was loaded from a path, so with inline
JSON that refresh exists purely in memory: capturing it afterwards is not an optimisation,
it is the difference between a token that lives a year and one that dies with the process.

**SSO is never touched from the cloud.** `login()` with credentials is what Cloudflare
punishes datacenter IPs for; `login()` with tokens refreshes over the ordinary API. Only
`vitals garmin login` passes credentials, and it warns when run outside `local`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from vitals.logging import get_logger
from vitals.sources.garmin.governor import RateGovernor

# Re-exported so the rest of the app never imports the library directly: this module
# is the boundary, and a download format is part of its vocabulary.
#
# ORIGINAL is the watch's own FIT recording. Every other format Garmin offers —
# TCX, GPX, CSV — is a lossy re-encoding it generates on request, and taking one of
# those would mean keeping a derived file forever while the original stayed on
# Garmin's servers, which is the opposite of what bronze is for.
ActivityDownloadFormat = Garmin.ActivityDownloadFormat

log = get_logger(__name__)

# What `login()` returns in place of a client when a code is needed.
NEEDS_MFA = "needs_mfa"


class GarminError(RuntimeError):
    """Base class for connector failures that callers are expected to handle."""


class NeedsReauth(GarminError):
    """Tokens are gone or rejected. Only a local `vitals garmin login` fixes this."""


class RateLimited(GarminError):
    """Garmin returned 429. The governor has already set a cooldown."""


class GarminClient:
    """Every call is governed, off the event loop, and mapped to our own errors."""

    def __init__(self, garmin: Garmin, governor: RateGovernor) -> None:
        self._garmin = garmin
        self._governor = governor

    @property
    def governor(self) -> RateGovernor:
        return self._governor

    @property
    def display_name(self) -> str | None:
        name = getattr(self._garmin, "display_name", None)
        return str(name) if name else None

    @classmethod
    async def from_tokens(
        cls, tokens: str, *, governor: RateGovernor, is_cn: bool = False
    ) -> GarminClient:
        """Resume a session from stored tokens. Never hits the SSO login path."""
        garmin = Garmin(is_cn=is_cn)
        try:
            await asyncio.to_thread(garmin.login, tokenstore=tokens)
        except GarminConnectAuthenticationError as exc:
            raise NeedsReauth(f"stored Garmin tokens were rejected: {exc}") from exc
        except GarminConnectTooManyRequestsError as exc:
            governor.record_rate_limited()
            raise RateLimited("Garmin rate-limited the token refresh") from exc
        except GarminConnectConnectionError as exc:
            raise GarminError(f"could not reach Garmin: {exc}") from exc
        return cls(garmin, governor)

    def export_tokens(self) -> str:
        """Current tokens as JSON, including any refresh performed during this run."""
        tokens: str = self._garmin.client.dumps()
        return tokens

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """One governed API call.

        A 404 is data, not a failure: Garmin returns it for days a device recorded
        nothing, and a gap in a backfill window must not stop the run.
        """
        await self._governor.acquire()
        fn: Callable[..., Any] = getattr(self._garmin, method)
        try:
            result = await asyncio.to_thread(fn, *args, **kwargs)
        except GarminConnectTooManyRequestsError as exc:
            self._governor.record_rate_limited()
            raise RateLimited(f"rate limited on {method}") from exc
        except GarminConnectAuthenticationError as exc:
            # The library does not retry 401, and neither should we: re-logging in from
            # here is the datacenter-IP SSO path this whole design avoids.
            self._governor.record_failure()
            raise NeedsReauth(f"authentication failed on {method}: {exc}") from exc
        except GarminConnectNotFoundError:
            self._governor.record_success()
            log.debug("garmin.not_found", method=method, args=[str(a) for a in args])
            return None
        except GarminConnectConnectionError as exc:
            self._governor.record_failure()
            raise GarminError(f"{method} failed: {exc}") from exc

        self._governor.record_success()
        return result


@dataclass(frozen=True, slots=True)
class MFARequired:
    """Garmin wants a code, and `client_state` is everything needed to resume.

    The state is returned rather than waited on. `prompt_mfa` blocks inside
    `login()` until a callback produces a code, which is fine for a terminal and
    impossible for a web request — the HTTP response has to go back before the user
    can read their code. `return_on_mfa` hands the half-finished login out instead,
    so it can be stored and picked up by a second request minutes later.
    """

    client_state: dict[str, Any]


async def begin_login(
    email: str,
    password: str,
    *,
    governor: RateGovernor,
    is_cn: bool = False,
) -> GarminClient | MFARequired:
    """First half of an interactive login: credentials in, tokens or an MFA demand out.

    Same SSO endpoint and the same Cloudflare exposure as `login_with_credentials` —
    see the module docstring. Splitting it in two changes when the code is collected,
    not where the request comes from.
    """
    garmin = Garmin(
        email=email,
        password=password,
        is_cn=is_cn,
        return_on_mfa=True,
        verify_login=True,
    )
    try:
        status, state = await asyncio.to_thread(garmin.login)
    except GarminConnectTooManyRequestsError as exc:
        governor.record_rate_limited()
        raise RateLimited("Garmin rate-limited the login; wait before retrying") from exc
    except GarminConnectAuthenticationError as exc:
        raise NeedsReauth(f"Garmin rejected the credentials: {exc}") from exc
    except GarminConnectConnectionError as exc:
        raise GarminError(f"could not reach Garmin: {exc}") from exc

    if status == NEEDS_MFA:
        if not isinstance(state, dict):
            # The library promises a resumable state alongside the demand. Without
            # it there is nothing to resume from, and pretending otherwise would
            # strand the user on a code entry screen that can never succeed.
            raise GarminError("Garmin asked for an MFA code but returned no resumable state")
        return MFARequired(client_state=state)

    return GarminClient(garmin, governor)


async def finish_login(
    email: str,
    password: str,
    client_state: dict[str, Any],
    code: str,
    *,
    governor: RateGovernor,
    is_cn: bool = False,
) -> GarminClient:
    """Second half: the code plus the stored state, on a fresh client.

    Rebuilt rather than resumed on the original object, because the two halves are
    different HTTP requests and may well be different processes — a Railway container
    is free to sleep between them. Everything that carries the login forward is in
    `client_state`; the credentials are passed back only so the rebuilt client is
    identical to the one that started.
    """
    garmin = Garmin(
        email=email,
        password=password,
        is_cn=is_cn,
        return_on_mfa=True,
        verify_login=True,
    )
    try:
        await asyncio.to_thread(garmin.resume_login, client_state, code)
    except GarminConnectTooManyRequestsError as exc:
        governor.record_rate_limited()
        raise RateLimited("Garmin rate-limited the login; wait before retrying") from exc
    except GarminConnectAuthenticationError as exc:
        raise NeedsReauth(f"Garmin rejected the code: {exc}") from exc
    except GarminConnectConnectionError as exc:
        raise GarminError(f"could not reach Garmin: {exc}") from exc
    return GarminClient(garmin, governor)


async def login_with_credentials(
    email: str,
    password: str,
    *,
    governor: RateGovernor,
    prompt_mfa: Callable[[], str] | None = None,
    is_cn: bool = False,
) -> GarminClient:
    """Interactive SSO login. Run this locally — see the module docstring."""
    garmin = Garmin(
        email=email,
        password=password,
        is_cn=is_cn,
        prompt_mfa=prompt_mfa,
        # Verify each strategy's token against the API before accepting it, so a token
        # the API would reject never reaches the vault.
        verify_login=True,
    )
    try:
        await asyncio.to_thread(garmin.login)
    except GarminConnectTooManyRequestsError as exc:
        governor.record_rate_limited()
        raise RateLimited("Garmin rate-limited the login; wait before retrying") from exc
    except GarminConnectAuthenticationError as exc:
        raise NeedsReauth(f"Garmin rejected the credentials: {exc}") from exc
    except GarminConnectConnectionError as exc:
        raise GarminError(f"could not reach Garmin: {exc}") from exc
    return GarminClient(garmin, governor)
