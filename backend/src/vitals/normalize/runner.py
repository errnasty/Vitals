"""Bronze → silver: read payloads, apply normalizers, upsert canonical rows.

Three properties are load-bearing.

**Idempotent.** Every write is an upsert on the natural key, so running it twice is
indistinguishable from running it once. There is no "already normalized" flag to get
out of step with reality, and no need for one: bronze is the truth and silver is a
projection of it that can be rebuilt at any time.

**Deterministic precedence.** Endpoints are processed in ascending priority, so when
`rhr_daily` and `user_summary` both report a resting heart rate for the same day, the
higher-priority endpoint writes last and wins — regardless of what order rows happened
to arrive in. Within an endpoint, rows are ordered oldest-first, so a day Garmin
revised overwrites the original rather than racing it.

**Bounded memory.** A seven-year backfill is tens of thousands of JSONB payloads, some
of them large. Rows are streamed one endpoint at a time through a keyset cursor, so
peak memory is a page, not a history.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.bulk import chunked
from vitals.db.models import Activity, MetricDaily, MetricSample, RawPayload, SleepSession
from vitals.logging import get_logger
from vitals.normalize import canonical as c
from vitals.normalize.garmin import NORMALIZERS, SOURCE
from vitals.normalize.model import Bronze, Normalized

log = get_logger(__name__)

PAGE_SIZE = 500


@dataclass(frozen=True, slots=True)
class EndpointCoverage:
    """What one endpoint's payloads actually turned into.

    `barren` is the number that produced nothing at all, and it is the single most
    useful number in this whole package: against real Garmin data it is how a
    normalizer written from library docs announces that the live shape differs.
    """

    endpoint: str
    payloads: int
    rows: int
    barren: int

    @property
    def ok(self) -> bool:
        return self.payloads > 0 and self.barren == 0


@dataclass
class NormalizeResult:
    payloads: int = 0
    daily: int = 0
    samples: int = 0
    sleep: int = 0
    activities: int = 0
    rejected: int = 0
    coverage: list[EndpointCoverage] = field(default_factory=list)
    # Endpoints sitting in bronze that nothing knows how to read yet.
    unmapped: list[str] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return self.daily + self.samples + self.sleep + self.activities


# How many keys of an empty payload are worth naming. Enough to recognise the
# response, short enough that a log line stays a log line.
SHAPE_KEYS = 12


def _shape(payload: object, depth: int = 0) -> str:
    """The key names of a payload, never its values.

    Deliberately structure-only. A barren warning that says which endpoint produced
    nothing cannot distinguish "Garmin returned an empty response" from "the
    normalizer is reading the wrong keys", and the only way to tell them apart used
    to be reading someone's raw health data out of the database. Key names settle it
    and are not health data.
    """
    if isinstance(payload, dict):
        keys = list(payload)[:SHAPE_KEYS]
        more = "…" if len(payload) > SHAPE_KEYS else ""
        inner = ""
        # One level down for the wrapper shapes Garmin favours, where the useful
        # names are never at the top.
        if depth == 0:
            for key in ("values", "individualStats", "allMetrics", "dailyMetrics"):
                if isinstance(payload.get(key), (dict, list)):
                    inner = f" {key}=" + _shape(payload[key], depth + 1)
                    break
        return "{" + ", ".join(keys) + more + "}" + inner
    if isinstance(payload, list):
        return f"[{len(payload)}]" + (_shape(payload[0], depth) if payload else "")
    return type(payload).__name__


def _window(statement: Select[Any], start: date | None, end: date | None) -> Select[Any]:
    """Restrict to a date window, keeping undated payloads.

    Undated rows (an activity, a response Garmin filed under no date) have a null
    `calendar_date` and would be silently dropped by a naive BETWEEN — which is how a
    recompute quietly loses every activity you own.
    """
    if start is not None:
        statement = statement.where(
            or_(RawPayload.calendar_date.is_(None), RawPayload.calendar_date >= start)
        )
    if end is not None:
        statement = statement.where(
            or_(RawPayload.calendar_date.is_(None), RawPayload.calendar_date <= end)
        )
    return statement


class SilverWriter:
    """Upserts canonical records. One instance per run."""

    def __init__(self, session: AsyncSession, *, user_id: uuid.UUID, source: str) -> None:
        self._session = session
        self._user_id = user_id
        self._source = source

    async def write(self, batch: Sequence[tuple[uuid.UUID, Normalized]]) -> NormalizeResult:
        result = NormalizeResult()
        daily: dict[tuple[str, date], dict[str, Any]] = {}
        samples: dict[tuple[str, datetime], dict[str, Any]] = {}
        sleep: dict[date, dict[str, Any]] = {}
        activities: dict[str, dict[str, Any]] = {}

        for payload_id, normalized in batch:
            for value in normalized.daily:
                try:
                    unit = c.unit_for(value.metric)
                except c.UnknownMetric:
                    log.warning("normalize.unknown_metric", metric=value.metric)
                    result.rejected += 1
                    continue
                daily[(value.metric, value.calendar_date)] = {
                    "id": uuid.uuid4(),
                    "user_id": self._user_id,
                    "metric": value.metric,
                    "calendar_date": value.calendar_date,
                    "source": self._source,
                    "value": value.value,
                    "unit": unit,
                    "raw_payload_id": payload_id,
                }
            for sample in normalized.samples:
                try:
                    unit = c.unit_for(sample.metric)
                except c.UnknownMetric:
                    log.warning("normalize.unknown_metric", metric=sample.metric)
                    result.rejected += 1
                    continue
                samples[(sample.metric, sample.recorded_at)] = {
                    "id": uuid.uuid4(),
                    "user_id": self._user_id,
                    "metric": sample.metric,
                    "recorded_at": sample.recorded_at,
                    "source": self._source,
                    "value": sample.value,
                    "unit": unit,
                    "raw_payload_id": payload_id,
                }
            for night in normalized.sleep:
                sleep[night.calendar_date] = {
                    "id": uuid.uuid4(),
                    "user_id": self._user_id,
                    "source": self._source,
                    "calendar_date": night.calendar_date,
                    "started_at": night.started_at,
                    "ended_at": night.ended_at,
                    "duration_s": night.duration_s,
                    "deep_s": night.deep_s,
                    "light_s": night.light_s,
                    "rem_s": night.rem_s,
                    "awake_s": night.awake_s,
                    "nap_s": night.nap_s,
                    "score": night.score,
                    "avg_hrv": night.avg_hrv,
                    "avg_spo2": night.avg_spo2,
                    "avg_respiration": night.avg_respiration,
                    "raw_payload_id": payload_id,
                }
            for item in normalized.activities:
                activities[item.external_id] = {
                    "id": uuid.uuid4(),
                    "user_id": self._user_id,
                    "source": self._source,
                    "external_id": item.external_id,
                    "name": item.name,
                    "activity_type": item.activity_type,
                    "started_at": item.started_at,
                    "duration_s": item.duration_s,
                    "moving_duration_s": item.moving_duration_s,
                    "distance_m": item.distance_m,
                    "elevation_gain_m": item.elevation_gain_m,
                    "elevation_loss_m": item.elevation_loss_m,
                    "avg_speed_mps": item.avg_speed_mps,
                    "max_speed_mps": item.max_speed_mps,
                    "calories": item.calories,
                    "avg_hr": item.avg_hr,
                    "max_hr": item.max_hr,
                    "avg_power": item.avg_power,
                    "max_power": item.max_power,
                    "normalized_power": item.normalized_power,
                    "aerobic_training_effect": item.aerobic_training_effect,
                    "anaerobic_training_effect": item.anaerobic_training_effect,
                    "training_load": item.training_load,
                    "total_sets": item.total_sets,
                    "total_reps": item.total_reps,
                    "total_volume_kg": item.total_volume_kg,
                    "raw_payload_id": payload_id,
                }

        result.daily = await self._upsert(
            MetricDaily, list(daily.values()), "uq_metric_daily_point"
        )
        result.samples = await self._upsert(
            MetricSample, list(samples.values()), "uq_metric_sample_point"
        )
        result.sleep = await self._upsert(
            SleepSession, list(sleep.values()), "uq_sleep_session_night"
        )
        result.activities = await self._upsert(
            Activity, list(activities.values()), "uq_activity_external"
        )
        return result

    async def _upsert(self, model: Any, rows: list[dict[str, Any]], constraint: str) -> int:
        if not rows:
            return 0
        # Everything but the natural key is refreshed: a recompute after a normalizer
        # fix must be able to *change* a value, not just fill in a missing one.
        updatable = {k: v for k, v in rows[0].items() if k not in ("id", "user_id")}
        # A single page of intraday payloads is thousands of sample rows, which is
        # well past what one statement can bind.
        for group in chunked(rows):
            statement = (
                pg_insert(model)
                .values(group)
                .on_conflict_do_update(
                    constraint=constraint,
                    set_={k: getattr(pg_insert(model).excluded, k) for k in updatable},
                )
            )
            await self._session.execute(statement)
        return len(rows)


async def normalize(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    source: str = SOURCE,
    start: date | None = None,
    end: date | None = None,
    endpoints: Sequence[str] | None = None,
    dry_run: bool = False,
) -> NormalizeResult:
    """Rebuild silver from bronze for one user and window."""
    total = NormalizeResult()
    writer = SilverWriter(session, user_id=user_id, source=source)

    known = set(NORMALIZERS)
    wanted = known if endpoints is None else known & set(endpoints)

    present = await _endpoints_in_bronze(session, user_id=user_id, source=source)
    total.unmapped = sorted(present - known)

    # Ascending priority: the endpoint with the last word writes last.
    ordered = sorted(wanted, key=lambda name: (NORMALIZERS[name].priority, name))

    for endpoint in ordered:
        if endpoint not in present:
            continue
        coverage = await _run_endpoint(
            session,
            writer,
            user_id=user_id,
            source=source,
            endpoint=endpoint,
            start=start,
            end=end,
            dry_run=dry_run,
            total=total,
        )
        total.coverage.append(coverage)

    if not dry_run:
        await session.commit()

    log.info(
        "normalize.finished",
        source=source,
        payloads=total.payloads,
        rows=total.rows,
        rejected=total.rejected,
        dry_run=dry_run,
    )
    return total


async def _endpoints_in_bronze(
    session: AsyncSession, *, user_id: uuid.UUID, source: str
) -> set[str]:
    result = await session.execute(
        select(RawPayload.endpoint)
        .where(RawPayload.user_id == user_id, RawPayload.source == source)
        .distinct()
    )
    return set(result.scalars())


async def _run_endpoint(
    session: AsyncSession,
    writer: SilverWriter,
    *,
    user_id: uuid.UUID,
    source: str,
    endpoint: str,
    start: date | None,
    end: date | None,
    dry_run: bool,
    total: NormalizeResult,
) -> EndpointCoverage:
    fn = NORMALIZERS[endpoint].fn
    payloads = rows = barren = 0
    barren_shape: str | None = None
    cursor: tuple[datetime, uuid.UUID] | None = None

    while True:
        statement = select(
            RawPayload.id,
            RawPayload.payload,
            RawPayload.calendar_date,
            RawPayload.entity_key,
            RawPayload.first_seen_at,
        ).where(
            RawPayload.user_id == user_id,
            RawPayload.source == source,
            RawPayload.endpoint == endpoint,
        )
        statement = _window(statement, start, end)
        if cursor is not None:
            seen_at, last_id = cursor
            statement = statement.where(
                or_(
                    RawPayload.first_seen_at > seen_at,
                    and_(RawPayload.first_seen_at == seen_at, RawPayload.id > last_id),
                )
            )
        # Oldest first, so a later revision of the same day overwrites the original.
        statement = statement.order_by(RawPayload.first_seen_at, RawPayload.id).limit(PAGE_SIZE)

        page = (await session.execute(statement)).all()
        if not page:
            break

        batch: list[tuple[uuid.UUID, Normalized]] = []
        for payload_id, payload, calendar_date, entity_key, _ in page:
            normalized = fn(
                Bronze(
                    endpoint=endpoint,
                    payload=payload,
                    calendar_date=calendar_date,
                    entity_key=entity_key,
                )
            )
            payloads += 1
            if normalized:
                rows += normalized.row_count
                batch.append((payload_id, normalized))
            else:
                barren += 1
                if barren_shape is None:
                    barren_shape = _shape(payload)

        if batch and not dry_run:
            written = await writer.write(batch)
            total.daily += written.daily
            total.samples += written.samples
            total.sleep += written.sleep
            total.activities += written.activities
            total.rejected += written.rejected

        last = page[-1]
        cursor = (last[4], last[0])

    total.payloads += payloads
    if barren:
        # The shape, not the contents. "Every sleep payload produced nothing" is a
        # real finding and a useless one: it cannot tell you whether Garmin sent an
        # empty response or the normalizer is looking for the wrong keys, and the
        # only way to find out was to read the person's raw health data. Key names
        # separate those two cases without any of that leaving the database.
        log.warning(
            "normalize.barren_payloads",
            endpoint=endpoint,
            barren=barren,
            seen=payloads,
            shape=barren_shape,
        )

    return EndpointCoverage(endpoint=endpoint, payloads=payloads, rows=rows, barren=barren)
