"""Connecting Garmin from the app, for when there is no terminal to hand.

`vitals garmin login` remains the right way to do this and the reason is unchanged:
Garmin's SSO sits behind Cloudflare, which treats datacenter IPs far more harshly than
residential ones, and these endpoints run inside Railway. Nothing here makes that
safer. What it does is make the login *possible* from a phone, which the CLI cannot —
and a connector nobody can connect is not much of a connector.

So the endpoints are built as if the risk were real, because it is:

* **A hard attempt cap with a lockout.** A web form turns "one careful annual login"
  into something that can be retried thirty times in a minute, and thirty SSO attempts
  from a datacenter IP is how an account gets locked. Failures are counted and the
  door closes for a while.
* **Nothing is held in memory between the two requests.** The MFA step arrives minutes
  later, possibly at a container that has since slept or restarted. The half-finished
  login is encrypted into the vault with an expiry instead.
* **The password lives for minutes, not forever.** Rebuilding the client for the resume
  needs it, so it is stored under the same Fernet key as everything else and deleted
  the moment the login resolves either way. This is a deliberately smaller promise than
  `vitals garmin login --store-password`, which keeps it indefinitely on purpose.
* **Neither secret is ever logged.** Not at debug, not in an error path.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.api import format as fmt
from vitals.api.deps import CurrentUserDep, SessionDep
from vitals.config import get_settings
from vitals.db.models import (
    GARMIN_LOGIN_ATTEMPTS,
    GARMIN_PASSWORD,
    GARMIN_PENDING_LOGIN,
    GARMIN_TOKENS,
    AppUser,
)
from vitals.ingest import backfill
from vitals.ingest.pipeline import connection_for
from vitals.logging import get_logger
from vitals.security.vault import CredentialVault, VaultUnavailable, build_vault
from vitals.sources.garmin import (
    SOURCE,
    GarminClient,
    GarminError,
    MFARequired,
    NeedsReauth,
    RateGovernor,
    RateLimited,
    begin_login,
    finish_login,
)

log = get_logger(__name__)

router = APIRouter(prefix="/garmin", tags=["garmin"])

# How long a half-finished login stays resumable. Long enough to fetch a code from a
# text message or an authenticator, short enough that the password it carries is not
# sitting there for the afternoon.
PENDING_TTL = timedelta(minutes=10)
# Consecutive failures before the door closes. Low on purpose: every failure is an SSO
# request from a datacenter IP, and the thing being protected is the account itself.
MAX_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=15)

# Said on success, because "Connected." on its own invites a reload of an empty
# dashboard. The history is arriving; it is not instant, and the reason is Garmin's
# rate limit rather than anything this app could hurry.
CONNECTED_DETAIL = "Connected. Pulling your history now — this takes a few minutes."


class ConnectRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    # SecretStr so a stray repr, a validation error or a logged request body cannot
    # spill it. The value is only ever read with .get_secret_value().
    password: SecretStr = Field(min_length=1)


class MFARequest(BaseModel):
    code: str = Field(min_length=4, max_length=16)


class ConnectResponse(BaseModel):
    # "connected" | "mfa_required"
    status: str
    detail: str
    display_name: str | None = None


class BackfillView(BaseModel):
    """How far the history pull has got, for a screen to show rather than compute."""

    running: bool
    done: bool
    # Already a percentage string: the UI renders, Python does the arithmetic.
    progress: str | None = None
    since: date | None = None
    reached: date | None = None
    detail: str | None = None


class StatusResponse(BaseModel):
    connected: bool
    state: str
    detail: str | None = None
    # Set while a login is waiting on a code, so a reloaded page resumes where it was
    # rather than starting again and burning another SSO request.
    awaiting_mfa: bool = False
    last_success_at: datetime | None = None
    locked_until: datetime | None = None
    history: BackfillView | None = None


# ── attempt accounting ──────────────────────────────────────────────────────────


async def _attempts(vault: CredentialVault, user_id: uuid.UUID) -> dict[str, Any]:
    raw = await vault.get(user_id, GARMIN_LOGIN_ATTEMPTS)
    if not raw:
        return {"failures": 0, "locked_until": None}
    try:
        record: dict[str, Any] = json.loads(raw)
    except ValueError:  # pragma: no cover - defensive against a hand-edited row
        return {"failures": 0, "locked_until": None}
    return record


def _locked_until(record: dict[str, Any]) -> datetime | None:
    raw = record.get("locked_until")
    if not raw:
        return None
    when = datetime.fromisoformat(raw)
    return when if when > datetime.now(UTC) else None


async def _record_failure(vault: CredentialVault, user_id: uuid.UUID) -> None:
    record = await _attempts(vault, user_id)
    failures = int(record.get("failures", 0)) + 1
    locked = datetime.now(UTC) + LOCKOUT if failures >= MAX_ATTEMPTS else None
    await vault.put(
        user_id,
        GARMIN_LOGIN_ATTEMPTS,
        json.dumps({"failures": failures, "locked_until": locked.isoformat() if locked else None}),
    )
    if locked:
        log.warning("garmin.login_locked", failures=failures, until=locked.isoformat())


async def _guard(vault: CredentialVault, user_id: uuid.UUID) -> None:
    locked = _locked_until(await _attempts(vault, user_id))
    if locked is None:
        return
    wait = int((locked - datetime.now(UTC)).total_seconds() // 60) + 1
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"too many failed attempts — try again in about {wait} minute(s). "
        "Each attempt is a real login against Garmin, and repeated failures are "
        "what gets an account locked.",
    )


# ── pending login ───────────────────────────────────────────────────────────────


async def _pending(vault: CredentialVault, user_id: uuid.UUID) -> dict[str, Any] | None:
    """The half-finished login, if one is still within its window."""
    raw = await vault.get(user_id, GARMIN_PENDING_LOGIN)
    if not raw:
        return None
    try:
        record: dict[str, Any] = json.loads(raw)
        expires = datetime.fromisoformat(record["expires_at"])
    except (ValueError, KeyError):  # pragma: no cover - defensive
        await vault.delete(user_id, GARMIN_PENDING_LOGIN)
        return None
    if expires <= datetime.now(UTC):
        await vault.delete(user_id, GARMIN_PENDING_LOGIN)
        return None
    return record


async def pull_history(user_id: uuid.UUID) -> None:
    """Work the history pull, on its own session, after the response has gone.

    Its own session because the request's is closed the moment the response is
    written, and this outlives it by minutes. Nothing here can fail the connection
    that started it — by the time this runs the tokens are stored and the user has
    already been told they are connected.
    """
    from vitals.db.session import get_sessionmaker

    try:
        async with get_sessionmaker()() as session:
            result = await backfill.run(session, user_id=user_id)
        log.info(
            "garmin.history_pulled",
            chunks=result.chunks,
            requests=result.requests,
            done=result.done,
        )
    except Exception as exc:  # noqa: BLE001 - a background task has nobody to raise to
        log.error("garmin.history_failed", error=f"{type(exc).__name__}: {exc}")


async def _store_tokens(
    session: AsyncSession,
    vault: CredentialVault,
    user: AppUser,
    client: GarminClient,
    *,
    email: str,
) -> str:
    """Persist a successful login and clear everything transient behind it."""
    await vault.put(user.id, GARMIN_TOKENS, client.export_tokens())
    # The pending record carries the password; a finished login has no use for it.
    await vault.delete(user.id, GARMIN_PENDING_LOGIN)
    await vault.delete(user.id, GARMIN_LOGIN_ATTEMPTS)

    connection = await connection_for(session, user.id)
    name = client.display_name or email
    if connection is None:
        from vitals.db.models import SourceConnection

        connection = SourceConnection(user_id=user.id, source=SOURCE)
        session.add(connection)
    connection.status = "active"
    connection.status_detail = None
    connection.external_id = name
    connection.consecutive_failures = 0
    connection.cooldown_until = None
    connection.last_success_at = datetime.now(UTC)
    await session.commit()

    log.info("garmin.connected", via="api")
    return name


def _backfill_view(progress: backfill.BackfillProgress) -> BackfillView | None:
    if progress.requested_from is None:
        return None
    return BackfillView(
        running=progress.running,
        done=progress.done,
        progress=None if progress.fraction is None else fmt.percent(progress.fraction),
        since=progress.requested_from,
        reached=progress.cursor,
        detail=progress.detail,
    )


async def _start_history(
    session: AsyncSession, background: BackgroundTasks, *, user_id: uuid.UUID
) -> None:
    """Ask for the history, and start pulling it without making the caller wait.

    Connecting a source and then showing an empty dashboard is a strange thing to do
    to someone who just handed over their password, so the pull starts here rather
    than at the next cron tick. It cannot be done *in* the request: a few hundred
    rate-governed calls is ten minutes, and nothing should hold a connection open
    that long. So the cursor is written now and the work happens after the response.
    """
    await backfill.request(session, user_id=user_id)
    background.add_task(pull_history, user_id)


def _vault(session: AsyncSession) -> CredentialVault:
    try:
        return build_vault(session, get_settings())
    except VaultUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"credential storage is not configured: {exc}",
        ) from exc


# ── endpoints ───────────────────────────────────────────────────────────────────


@router.get("/status", response_model=StatusResponse)
async def connection_status(user: CurrentUserDep, session: SessionDep) -> StatusResponse:
    """Whether Garmin is connected, and whether a login is mid-flight."""
    vault = _vault(session)
    connection = await connection_for(session, user.id)
    has_tokens = await vault.get(user.id, GARMIN_TOKENS) is not None
    pending = await _pending(vault, user.id)
    locked = _locked_until(await _attempts(vault, user.id))

    if has_tokens and connection is not None and connection.status == "active":
        state = "connected"
    elif has_tokens:
        state = connection.status if connection is not None else "connected"
    else:
        state = "disconnected"

    return StatusResponse(
        connected=has_tokens and state == "connected",
        state=state,
        detail=connection.status_detail if connection is not None else None,
        awaiting_mfa=pending is not None,
        last_success_at=connection.last_success_at if connection is not None else None,
        locked_until=locked,
        history=_backfill_view(await backfill.progress(session, user_id=user.id)),
    )


@router.post("/connect", response_model=ConnectResponse)
async def connect(
    body: ConnectRequest,
    user: CurrentUserDep,
    session: SessionDep,
    background: BackgroundTasks,
) -> ConnectResponse:
    """Start a login. Returns either a finished connection or a demand for a code."""
    vault = _vault(session)
    await _guard(vault, user.id)

    password = body.password.get_secret_value()
    try:
        result = await begin_login(body.email, password, governor=RateGovernor())
    except (NeedsReauth, RateLimited) as exc:
        await _record_failure(vault, user.id)
        # `str(exc)` is the library's own message and never contains the password.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except GarminError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    if isinstance(result, MFARequired):
        await vault.put(
            user.id,
            GARMIN_PENDING_LOGIN,
            json.dumps(
                {
                    "client_state": result.client_state,
                    "email": body.email,
                    "password": password,
                    "expires_at": (datetime.now(UTC) + PENDING_TTL).isoformat(),
                }
            ),
        )
        log.info("garmin.mfa_required", via="api")
        return ConnectResponse(
            status="mfa_required",
            detail="Garmin sent a code. Enter it to finish connecting.",
        )

    name = await _store_tokens(session, vault, user, result, email=body.email)
    await _start_history(session, background, user_id=user.id)
    return ConnectResponse(status="connected", detail=CONNECTED_DETAIL, display_name=name)


@router.post("/connect/mfa", response_model=ConnectResponse)
async def submit_mfa(
    body: MFARequest,
    user: CurrentUserDep,
    session: SessionDep,
    background: BackgroundTasks,
) -> ConnectResponse:
    """Finish a login that was waiting on a code."""
    vault = _vault(session)
    await _guard(vault, user.id)

    pending = await _pending(vault, user.id)
    if pending is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "no login is waiting for a code, or it expired — start again.",
        )

    try:
        client = await finish_login(
            pending["email"],
            pending["password"],
            pending["client_state"],
            body.code.strip(),
            governor=RateGovernor(),
        )
    except (NeedsReauth, RateLimited) as exc:
        await _record_failure(vault, user.id)
        # The state is single-use: Garmin will not accept a second code against a
        # rejected one, and leaving it would put the user in a loop that cannot end.
        await vault.delete(user.id, GARMIN_PENDING_LOGIN)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except GarminError as exc:
        await vault.delete(user.id, GARMIN_PENDING_LOGIN)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    name = await _store_tokens(session, vault, user, client, email=pending["email"])
    await _start_history(session, background, user_id=user.id)
    return ConnectResponse(status="connected", detail=CONNECTED_DETAIL, display_name=name)


@router.post("/disconnect", response_model=StatusResponse)
async def disconnect(user: CurrentUserDep, session: SessionDep) -> StatusResponse:
    """Forget the tokens. Bronze is untouched — this is a credential, not the data."""
    vault = _vault(session)
    for name in (GARMIN_TOKENS, GARMIN_PASSWORD, GARMIN_PENDING_LOGIN, GARMIN_LOGIN_ATTEMPTS):
        await vault.delete(user.id, name)

    connection = await connection_for(session, user.id)
    if connection is not None:
        connection.status = "needs_reauth"
        connection.status_detail = "disconnected from the app"
        await session.commit()

    log.info("garmin.disconnected", via="api")
    return StatusResponse(connected=False, state="disconnected", detail="Disconnected.")
