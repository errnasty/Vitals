"""Binary bronze → silver: turning stored FIT files into activity detail.

Deliberately its own pass rather than part of the normalizer runner next door. That
runner walks `raw_payload` and applies a per-endpoint function to JSON; this walks
`raw_file`, decompresses, decodes a binary format and throws away a hundred thousand
samples. Sharing a loop would have meant one of the two doing something unnatural.

It is also idempotent and cheap to re-run, which is the property that makes the
storage decision safe: the reduction in `fit.py` is the part most likely to be
improved later, and improving it is `vitals recordings --rebuild` rather than two
thousand downloads.
"""

from __future__ import annotations

import gzip
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import Activity, ActivityDetail, RawFile
from vitals.logging import get_logger
from vitals.normalize.fit import UnreadableFit, parse

log = get_logger(__name__)

SOURCE = "garmin"
KIND = "fit"


@dataclass
class RecordingResult:
    files: int = 0
    parsed: int = 0
    skipped: int = 0
    unreadable: int = 0
    orphaned: int = 0


async def rebuild(
    session: AsyncSession, *, user_id: uuid.UUID, force: bool = False
) -> RecordingResult:
    """Decode every stored recording that does not already have a detail row.

    `force` re-decodes everything, which is what a change to the reductions needs.
    """
    result = RecordingResult()

    if force:
        await session.execute(delete(ActivityDetail).where(ActivityDetail.user_id == user_id))
        await session.commit()

    done = set(
        (
            await session.execute(
                select(ActivityDetail.external_id).where(ActivityDetail.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )

    # The activity this recording belongs to. A file whose activity has not been
    # normalized yet is left alone rather than given a detail row pointing nowhere —
    # the next pass picks it up once the summary lands.
    activities = {
        external_id: activity_id
        for activity_id, external_id in (
            await session.execute(
                select(Activity.id, Activity.external_id).where(Activity.user_id == user_id)
            )
        ).all()
    }

    rows = (
        await session.execute(
            select(RawFile.id, RawFile.entity_key).where(
                RawFile.user_id == user_id, RawFile.source == SOURCE, RawFile.kind == KIND
            )
        )
    ).all()

    for file_id, entity_key in rows:
        result.files += 1
        if entity_key in done:
            result.skipped += 1
            continue
        activity_id = activities.get(entity_key)
        if activity_id is None:
            result.orphaned += 1
            continue

        blob = await session.get(RawFile, file_id)
        if blob is None:  # pragma: no cover - selected a moment ago
            continue

        try:
            summary = parse(gzip.decompress(blob.content))
        except (UnreadableFit, OSError) as exc:
            # Kept, not deleted. A file this decoder cannot read today may be readable
            # by the next one, and it cost a request to get.
            result.unreadable += 1
            log.warning("recordings.unreadable", activity=entity_key, error=str(exc))
            continue

        session.add(
            ActivityDetail(
                user_id=user_id,
                activity_id=activity_id,
                source=SOURCE,
                external_id=entity_key,
                samples=summary.samples,
                sample_interval_s=summary.sample_interval_s,
                normalized_power=summary.normalized_power,
                variability_index=summary.variability_index,
                decoupling_pct=summary.decoupling_pct,
                hr_drift_bpm=summary.hr_drift_bpm,
                ascent_m=summary.ascent_m,
                descent_m=summary.descent_m,
                moving_time_s=summary.moving_time_s,
                route_path=summary.route_path,
                route_points=summary.route_points,
            )
        )
        result.parsed += 1

    await session.commit()
    log.info(
        "recordings.rebuilt",
        files=result.files,
        parsed=result.parsed,
        skipped=result.skipped,
        unreadable=result.unreadable,
        orphaned=result.orphaned,
    )
    return result
