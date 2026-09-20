"""The screens that answer "why is this number what it is, and what would change it".

Everything here is a read. The score already stored its own decomposition — each
line's value, the points it scored, the points of the final score it is worth, and
(since this phase) the points it would add if it scored full marks. So "what would
help most" is `order by headroom desc`, not a calculation.

The one thing not stored is the **target**: the value that would score 100. That lives
in `score/pillars.py` as the calibration itself, which is the point — the app scores
you against `8h` of sleep, so `8h` is what it should be able to show you. Reading it
back out of the scorer rather than restating it here means the screen cannot drift
from what the score actually did.

Three kinds of advice fall out of the three kinds of curve, and the differences are
honest ones:

  ramp   one direction is better, so there is a number to aim for.
  band   a range is best, so someone already inside it is told nothing.
  personal  no fixed target exists — a VO2max means nothing without an age — so the
            comparison is against your own recent history and the screen says so.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vitals.analytics import canonical as gold
from vitals.api import format as fmt
from vitals.api.deps import CurrentUserDep, SessionDep
from vitals.db.models import ScoreContribution, ScorePillar, VitalsScore
from vitals.score import curves
from vitals.score.compose import MIN_TRUSTED_COVERAGE
from vitals.score.pillars import BY_NAME, PILLARS, Contribution, target_for

router = APIRouter(tags=["detail"])

# Below this many points of the final score, a suggestion is not worth making. An app
# that tells you to change your sleep to gain a fifth of a point is wasting the only
# thing it is really spending, which is attention.
WORTH_SAYING = 0.5


class FactorView(BaseModel):
    """One contribution, with everything needed to explain and improve it."""

    metric: str
    label: str
    rationale: str

    value: str
    points: str
    points_value: float
    coverage: str

    # Points of the overall score this line is worth now, and could be worth.
    effect: str
    headroom: str
    headroom_value: float

    # How it is graded, and what full marks look like. `target` is None where no
    # single number is the right answer.
    basis: str
    target: str | None = None
    scale: str | None = None
    # A sentence, already written, about what would move this. None when nothing
    # useful can be said — which is a real answer and better than filler.
    advice: str | None = None


class PillarDetail(BaseModel):
    name: str
    label: str
    display: str
    value: float
    coverage: str
    trusted: bool
    # This pillar's share of the day's score, as weighted.
    weight: str
    summary: str
    factors: list[FactorView]


class PillarResponse(BaseModel):
    date: date
    pillar: PillarDetail


class PillarLink(BaseModel):
    name: str
    label: str
    display: str
    value: float
    coverage: str
    weight: str
    summary: str


class ScoreMethod(BaseModel):
    """How the number is built, in the app's own words."""

    headline: str
    steps: list[str]
    coverage_floor: str


class ScoreDetailResponse(BaseModel):
    date: date
    value: float
    display: str
    caption: str
    coverage: str
    trusted: bool
    method: ScoreMethod
    pillars: list[PillarLink]
    # Ranked by what would move the score most, not by what scored worst — a weak
    # line that barely counts is not where anyone's effort should go.
    opportunities: list[FactorView]


# ── describing a contribution ───────────────────────────────────────────────────


def _describe(target: curves.Target | None, unit: str) -> tuple[str, str | None, str | None]:
    """The basis, the target and the scale, formatted."""
    if target is None:  # pragma: no cover - every scorer carries one
        return "scored against a fixed scale", None, None

    if target.direction == curves.PERSONAL:
        days = target.history_days
        return (f"ranked against your own last {days} days", None, None)

    if target.direction == curves.WITHIN and target.band is not None:
        low, high = target.band
        return (
            "best inside a range — too little and too much both cost",
            f"{fmt.reading(low, unit)}–{fmt.metric(high, unit)}",
            None,
        )

    optimal = None if target.optimal is None else fmt.reading(target.optimal, unit)
    floor = None if target.floor is None else fmt.reading(target.floor, unit)
    basis = (
        "higher is better, up to the anchor"
        if target.direction == curves.HIGHER
        else "lower is better, down to the anchor"
    )
    scale = None if floor is None else f"{floor} scores 0, {optimal} scores 100"
    return basis, optimal, scale


def _advice(
    *,
    definition: Contribution | None,
    target: curves.Target | None,
    unit: str,
    value: float,
    headroom: float,
) -> str | None:
    """What would move this line, or nothing.

    Deliberately conditional. There is no advice worth giving when a line is already
    near full marks or is worth a fraction of a point, and filling those cases with
    something encouraging is how an app starts sounding like it is not paying
    attention.

    The `observed` case matters most. Some inputs are readings rather than dials —
    "get your overnight HRV to +0.5 SD" is not advice, it is a number you do not
    control — so those never get a gap sentence, only the note about what does move
    them.
    """
    lever = definition.lever if definition else None
    if headroom < WORTH_SAYING or target is None:
        return None

    if definition is not None and definition.observed:
        return lever

    if target.direction == curves.PERSONAL:
        ranked = (
            f"No fixed target — this is graded against your own last "
            f"{target.history_days} days, so it improves by beating your recent range."
        )
        return f"{ranked} {lever}" if lever else ranked

    gain = f"{fmt.number(headroom, places=1)} points"

    if target.direction == curves.WITHIN and target.band is not None:
        low, high = target.band
        if value < low:
            gap = (
                f"Below the settled range; bringing it up toward "
                f"{fmt.reading(low, unit)} is worth {gain}."
            )
        elif value > high:
            gap = (
                f"Above the settled range; easing back toward "
                f"{fmt.reading(high, unit)} is worth {gain}."
            )
        else:
            # Already inside the band. Nudging someone who is where they should be
            # is advice invented by the screen.
            return None
        return f"{gap} {lever}" if lever else gap

    if target.optimal is None:  # pragma: no cover - ramps always have one
        return lever

    way = "up to" if target.direction == curves.HIGHER else "down to"
    gap = (
        f"Now {fmt.reading(value, unit)}; {way} {fmt.metric(target.optimal, unit)} is worth {gain}."
    )
    return f"{gap} {lever}" if lever else gap


def _factor(row: ScoreContribution, definition: Contribution | None) -> FactorView:
    unit = gold.unit_for(row.metric)
    target = target_for(definition.scorer) if definition else None
    basis, target_display, scale = _describe(target, unit)
    label = definition.label if definition else row.metric
    if definition is not None and definition.observed:
        # A reading, not a dial — so no "aim for this" is offered at all.
        target_display = None

    return FactorView(
        metric=row.metric,
        label=label,
        rationale=definition.rationale if definition else "",
        value=fmt.reading(row.value, unit),
        points=fmt.score(row.points),
        points_value=round(row.points),
        coverage=fmt.percent(row.coverage),
        effect=f"{fmt.number(row.effect, places=1)} pts",
        headroom=f"{fmt.number(row.headroom, places=1)} pts",
        headroom_value=row.headroom,
        basis=basis,
        target=target_display,
        scale=scale,
        advice=_advice(
            definition=definition,
            target=target,
            unit=unit,
            value=row.value,
            headroom=row.headroom,
        ),
    )


def _definition(metric: str) -> Contribution | None:
    for pillar in PILLARS:
        for contribution in pillar.contributions:
            if contribution.metric == metric:
                return contribution
    return None


def _summary(name: str, score: float, coverage: float) -> str:
    """What this pillar is measuring, said once, in plain words."""
    said = {
        "recovery": (
            "How much load your body is carrying right now, read from your overnight signals."
        ),
        "sleep": (
            "How much you slept, how regularly, and how well — over the week, not last night."
        ),
        "training": "Whether your training is building fitness or outrunning it.",
        "longevity": ("The habits with the strongest evidence behind them for living longer."),
    }
    return said.get(name, "")


# ── reads ───────────────────────────────────────────────────────────────────────


async def _day(session: AsyncSession, user_id: uuid.UUID, day: date | None) -> VitalsScore:
    statement = select(VitalsScore).where(VitalsScore.user_id == user_id)
    if day is not None:
        statement = statement.where(VitalsScore.calendar_date == day)
    row: VitalsScore | None = await session.scalar(
        statement.order_by(VitalsScore.calendar_date.desc()).limit(1)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no score for that day")
    return row


async def _contributions(
    session: AsyncSession, user_id: uuid.UUID, day: date, pillar: str | None = None
) -> list[ScoreContribution]:
    statement = select(ScoreContribution).where(
        ScoreContribution.user_id == user_id, ScoreContribution.calendar_date == day
    )
    if pillar is not None:
        statement = statement.where(ScoreContribution.pillar == pillar)
    return list((await session.execute(statement)).scalars().all())


async def _pillars(session: AsyncSession, user_id: uuid.UUID, day: date) -> list[ScorePillar]:
    return list(
        (
            await session.execute(
                select(ScorePillar)
                .where(ScorePillar.user_id == user_id, ScorePillar.calendar_date == day)
                .order_by(ScorePillar.weight.desc())
            )
        )
        .scalars()
        .all()
    )


# ── endpoints ───────────────────────────────────────────────────────────────────

DayQuery = date | None


@router.get("/score/detail", response_model=ScoreDetailResponse)
async def score_detail(
    user: CurrentUserDep, session: SessionDep, day: DayQuery = None
) -> ScoreDetailResponse:
    """The whole number: how it is built, what it is built from, and what would move it."""
    row = await _day(session, user.id, day)
    on = row.calendar_date

    pillars = await _pillars(session, user.id, on)
    contributions = await _contributions(session, user.id, on)

    factors = [_factor(item, _definition(item.metric)) for item in contributions]
    # By what would move the score, not by what scored worst. A line scoring 12 that
    # is worth a third of a point is not where anyone's week should go.
    opportunities = sorted(factors, key=lambda f: f.headroom_value, reverse=True)

    from vitals.score import verdict

    return ScoreDetailResponse(
        date=on,
        value=round(row.score),
        display=fmt.score(row.score),
        caption=verdict.caption(row.score, trusted=row.trusted),
        coverage=fmt.percent(row.coverage),
        trusted=row.trusted,
        method=ScoreMethod(
            headline="One number out of 100, built from four pillars.",
            steps=[
                "Each pillar scores its own inputs against a published anchor — the "
                "WHO's activity guideline, the adult sleep recommendation — or, where "
                "no anchor is honest, against your own recent history.",
                "A pillar is the weighted mean of its inputs, and each input is "
                "weighted by how much data was actually behind it.",
                "The four pillars combine the same way, so a pillar you have little "
                "data for counts for less rather than being quietly guessed at.",
                "Every line's effect is worked out here, not on this screen — they "
                "sum to exactly the score above.",
            ],
            coverage_floor=(
                f"Below {fmt.percent(MIN_TRUSTED_COVERAGE)} coverage the day is still "
                "scored, but flagged as thin rather than presented as fact."
            ),
        ),
        pillars=[
            PillarLink(
                name=item.pillar,
                label=BY_NAME[item.pillar].label if item.pillar in BY_NAME else item.pillar,
                display=fmt.score(item.score),
                value=round(item.score),
                coverage=fmt.percent(item.coverage),
                weight=fmt.percent(item.weight, of_one=False),
                summary=_summary(item.pillar, item.score, item.coverage),
            )
            for item in pillars
        ],
        opportunities=[f for f in opportunities if f.headroom_value >= WORTH_SAYING][:4],
    )


@router.get("/score/pillar/{name}", response_model=PillarResponse)
async def pillar_detail(
    name: str, user: CurrentUserDep, session: SessionDep, day: DayQuery = None
) -> PillarResponse:
    """One pillar in full: every input, how it is graded, and what would improve it."""
    if name not in BY_NAME:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no pillar called {name!r}")

    row = await _day(session, user.id, day)
    on = row.calendar_date

    stored = next((p for p in await _pillars(session, user.id, on) if p.pillar == name), None)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "that pillar was not scored that day")

    contributions = await _contributions(session, user.id, on, pillar=name)
    factors = [_factor(item, _definition(item.metric)) for item in contributions]
    # Biggest contributor first: the reader is looking for what carried the number.
    factors.sort(key=lambda f: f.points_value, reverse=True)

    return PillarResponse(
        date=on,
        pillar=PillarDetail(
            name=name,
            label=BY_NAME[name].label,
            display=fmt.score(stored.score),
            value=round(stored.score),
            coverage=fmt.percent(stored.coverage),
            trusted=stored.coverage >= MIN_TRUSTED_COVERAGE,
            weight=fmt.percent(stored.weight, of_one=False),
            summary=_summary(name, stored.score, stored.coverage),
            factors=factors,
        ),
    )
