"""What to do first, and why it is that rather than something else.

Every coaching app ranks advice. Most rank it by how bad the number looks, which
reliably puts the same advice at the top every day — your worst line is your worst
line, and being told about it again is not coaching. This ranks by **how many points
of your score are actually available**, which is a different question and frequently
has a different answer: a line scoring 40 out of 100 on a 10% weight is worth less
than one scoring 75 on a 40% weight, and only the second is worth a sentence today.

Three things multiply together, and each exists to veto a different kind of bad
advice.

**Headroom** is the points the score would gain if this line were perfect. It comes
straight from the composition, already accounting for weight and coverage, so nothing
here multiplies weights a second time.

**Movability** vetoes advice you cannot act on. Phase 5 marked some contributions
`observed` — your overnight HRV is a reading of how your body responded to things you
can change, not a dial. "Get your HRV to +0.5 SD" is not advice; it is a target
someone will chase by sleeping badly and worrying about it.

**Responsiveness** vetoes advice that does not work *for you*. The correlation engine
has already tested, against your own days and with a correction for everything else it
tried, whether the things you log move the things you measure. Where it found
something, that lever is promoted. Where it looked and found nothing, the lever is not
demoted to zero — an absence of evidence after eleven tagged days is not evidence of
absence — but it does not get the promotion either.

Nothing here is written by a model. The ranking, the points and the sentences are all
computed, and the coach's job downstream is to choose which of them to say and how to
say it kindly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.db.models import Insight, ScoreContribution, VitalsScore
from vitals.insights import prose
from vitals.logging import get_logger
from vitals.score.pillars import PILLARS

log = get_logger(__name__)

# Below this there is nothing to gain worth mentioning. Two points of a hundred is
# inside the noise of the inputs the score is built from, and an app that suggests
# changing your life over it is an app people learn to ignore.
WORTH_SAYING_POINTS = 2.0

# How much a proven personal effect promotes a lever. Deliberately modest: the
# evidence says this tag moves this metric, not that acting on it recovers the whole
# gap, and a multiplier large enough to reorder everything would be claiming more
# than the finding supports.
PROVEN_BOOST = 1.5

# The most the coach ever puts in front of someone at once. A ranked list of eleven
# things to fix is a list nobody starts.
MAX_INTERVENTIONS = 3

# Which tags plausibly bear on which pillar, for matching a proven finding to a
# lever. Deliberately coarse — this decides whether a finding *promotes* a lever, not
# what the finding says.
TAG_PILLARS: dict[str, tuple[str, ...]] = {
    "alcohol": ("sleep", "recovery"),
    "late_meal": ("sleep",),
    "late_caffeine": ("sleep",),
    "stress": ("recovery", "sleep"),
    "poor_environment": ("sleep",),
    "travel": ("sleep", "recovery"),
    "illness": ("recovery",),
    "injury": ("training",),
    "menstruation": ("recovery",),
}


@dataclass(frozen=True, slots=True)
class Intervention:
    pillar: str
    pillar_label: str
    metric: str
    label: str
    # Points of the final score this line could still gain.
    headroom: float
    # What actually moves it, from `pillars.py`.
    lever: str
    # Set when the correlation engine found something of this person's own that
    # bears on this pillar. The sentence is the finding's, not a new claim.
    evidence: str | None
    rank: float


@dataclass(frozen=True, slots=True)
class _Lever:
    text: str
    pillar: str
    pillar_label: str
    label: str


def _levers() -> dict[str, _Lever]:
    """Every contribution that is actionable, keyed by the metric it reads.

    Labels come from the pillar definitions rather than the stored row, because that
    is where they are defined. A score row carries numbers; duplicating the words
    into it would give them two homes and one of them would go stale.
    """
    out: dict[str, _Lever] = {}
    for pillar in PILLARS:
        for contribution in pillar.contributions:
            if contribution.observed or not contribution.lever:
                continue
            out[contribution.metric] = _Lever(
                text=contribution.lever,
                pillar=pillar.name,
                pillar_label=pillar.label,
                label=contribution.label,
            )
    return out


async def rank(
    session: AsyncSession, *, user_id: uuid.UUID, day: date | None = None
) -> list[Intervention]:
    """The few things worth doing, most valuable first."""
    score = await session.scalar(
        select(VitalsScore)
        .where(
            VitalsScore.user_id == user_id,
            *([VitalsScore.calendar_date == day] if day else []),
        )
        .order_by(VitalsScore.calendar_date.desc())
        .limit(1)
    )
    if score is None:
        return []

    rows = (
        (
            await session.execute(
                select(ScoreContribution).where(
                    ScoreContribution.user_id == user_id,
                    ScoreContribution.calendar_date == score.calendar_date,
                )
            )
        )
        .scalars()
        .all()
    )

    proven = await _proven_by_pillar(session, user_id=user_id)
    levers = _levers()

    out: list[Intervention] = []
    for row in rows:
        lever = levers.get(row.metric)
        if lever is None:
            # Observed, not chosen. See the module docstring.
            continue
        if row.headroom < WORTH_SAYING_POINTS:
            continue

        evidence = proven.get(lever.pillar)
        out.append(
            Intervention(
                pillar=lever.pillar,
                pillar_label=lever.pillar_label,
                metric=row.metric,
                label=lever.label,
                headroom=row.headroom,
                lever=lever.text,
                evidence=evidence,
                rank=row.headroom * (PROVEN_BOOST if evidence else 1.0),
            )
        )

    out.sort(key=lambda i: i.rank, reverse=True)
    return out[:MAX_INTERVENTIONS]


async def _proven_by_pillar(session: AsyncSession, *, user_id: uuid.UUID) -> dict[str, str]:
    """The strongest surviving finding touching each pillar, if any.

    Only findings that survived the correction are read. One that did not is not
    weaker evidence — it is the engine saying it could not tell, and letting it tip a
    ranking would smuggle back exactly the false positives the correction removed.
    """
    rows = (
        (
            await session.execute(
                select(Insight)
                .where(Insight.user_id == user_id, Insight.significant.is_(True))
                .order_by(Insight.p_value)
            )
        )
        .scalars()
        .all()
    )

    out: dict[str, str] = {}
    for row in rows:
        for pillar in TAG_PILLARS.get(row.tag, ()):
            # Strongest first from the query, so the first one to claim a pillar wins.
            # The sentence is the finding's own, word for word: two phrasings of one
            # statistic is how an app comes to appear to disagree with itself.
            out.setdefault(pillar, prose.sentence(row))
    return out
