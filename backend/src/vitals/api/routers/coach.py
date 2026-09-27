"""The coach: what to do first, what your own data says, and what to test next.

Three things a screen can render without doing arithmetic, which is the same contract
every other router here keeps. The ranking, the points, the anchors and the
conclusions are all computed before they reach this module; its job is to name them.

What this deliberately does not do is let a model decide any of it. Phase 7 settled
that the model writes prose and never numbers; the same line holds here, one level
up — the model may choose how to say "your sleep regularity is worth six points", and
never which line is worth six points.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from vitals.api import format as fmt
from vitals.api.deps import CurrentUserDep, SessionDep
from vitals.coach import experiments, interventions
from vitals.context import canonical as tags
from vitals.db.models import Experiment
from vitals.insights.prose import PHRASE
from vitals.profile import canonical as profile_vocab
from vitals.profile import fit as profile_fit

router = APIRouter(prefix="/coach", tags=["coach"])


class InterventionView(BaseModel):
    pillar: str
    pillar_label: str
    metric: str
    label: str
    # "worth up to 6 points" — already rounded, already worded.
    worth: str
    worth_points: float
    lever: str
    # The finding from this person's own days that promoted this line, when there
    # was one. The sentence is the finding's own, word for word.
    evidence: str | None = None


class ZoneView(BaseModel):
    label: str
    lower: str
    upper: str
    # The band as one finished string, unit included. `fmt.metric` renders a heart
    # rate as a bare number because every other screen shows it under a label that
    # already says bpm; a zone row has no such label, so the unit is attached here
    # rather than left to a component to append.
    band: str


class TraitView(BaseModel):
    trait: str
    label: str
    value: str
    observations: int
    basis: str


class ProfileView(BaseModel):
    traits: list[TraitView]
    zones: list[ZoneView]
    # Why a trait is missing, when it is. Missing is the normal state early on.
    missing: dict[str, str] = Field(default_factory=dict)


class ExperimentView(BaseModel):
    id: str
    tag: str
    tag_label: str
    metric: str
    hypothesis: str
    status: str
    started_on: date | None
    ends_on: date | None
    days_left: int | None = None
    conclusion: str | None = None
    sample: str | None = None


class CoachResponse(BaseModel):
    interventions: list[InterventionView]
    profile: ProfileView
    experiment: ExperimentView | None = None
    # Said once, at the top, because everything below is a claim about one person.
    caveat: str


CAVEAT = (
    "Everything here comes from your own days, compared against each other. None of "
    "it is medical advice, and none of it is a cause — only what tends to go with what."
)

TRAIT_LABELS: dict[str, str] = {
    profile_vocab.MAX_HR: "Maximum heart rate",
    profile_vocab.RESTING_HR_FLOOR: "Resting heart rate floor",
    profile_vocab.SLEEP_NEED: "Nightly sleep need",
    profile_vocab.HRV_TYPICAL: "Typical overnight HRV",
}


def _worth(points: float) -> str:
    """Rounded here, once, so no screen ever rounds a score point itself.

    Half-up rather than Python's default. `f"{6.5:.0f}"` is `"6"` — round-half-even,
    which is right for statistics and wrong for a person reading a ranked list: 6.5
    and 5.8 both came out as "6 points", so the top two lines claimed the same value
    while being in a deliberate order. Rounding away from zero at the halfway point
    is what anyone reading this expects a number to do.
    """
    whole = math.floor(points + 0.5)
    return f"worth up to {whole} point{'' if whole == 1 else 's'}"


def _trait_value(value: float, unit: str) -> str:
    """A measured anchor, with its unit attached.

    `fmt.metric` renders a heart rate as a bare number because every dashboard tile
    showing one sits under a label that already says bpm. A profile row does not, and
    "Maximum heart rate: 188" beside "Nightly sleep need: 7h 30m" reads as though one
    of them forgot its unit.
    """
    formatted = fmt.metric(value, unit)
    if unit in ("bpm", "count") and not formatted.endswith(unit):
        return f"{formatted} {unit}"
    return formatted


def _experiment_view(row: Experiment, today: date) -> ExperimentView:
    left = None
    if row.ends_on is not None and row.status in {"proposed", "running"}:
        left = max(0, (row.ends_on - today).days)

    sample = None
    if row.n_with is not None and row.n_without is not None:
        sample = f"{row.n_with} days with, {row.n_without} without"

    return ExperimentView(
        id=str(row.id),
        tag=row.tag,
        tag_label=tags.BY_NAME[row.tag].label if row.tag in tags.BY_NAME else row.tag,
        metric=row.metric,
        hypothesis=row.hypothesis,
        status=row.status,
        started_on=row.started_on,
        ends_on=row.ends_on,
        days_left=left,
        conclusion=row.conclusion,
        sample=sample,
    )


@router.get("", response_model=CoachResponse)
async def read(user: CurrentUserDep, session: SessionDep) -> CoachResponse:
    ranked = await interventions.rank(session, user_id=user.id)
    held = await profile_fit.load(session, user_id=user.id)

    zones: list[ZoneView] = []
    if profile_vocab.MAX_HR in held:
        zones = [
            ZoneView(
                label=label,
                lower=fmt.metric(lower, "bpm"),
                upper=fmt.metric(upper, "bpm"),
                band=f"{fmt.metric(lower, 'bpm')}–{fmt.metric(upper, 'bpm')} bpm",
            )
            for label, lower, upper in profile_vocab.zones(held[profile_vocab.MAX_HR].value)
        ]

    current = await session.scalar(
        select(Experiment)
        .where(Experiment.user_id == user.id)
        .order_by(Experiment.created_at.desc())
        .limit(1)
    )

    today = datetime.now(UTC).date()

    return CoachResponse(
        interventions=[
            InterventionView(
                pillar=item.pillar,
                pillar_label=item.pillar_label,
                metric=item.metric,
                label=item.label,
                worth=_worth(item.headroom),
                worth_points=round(item.headroom, 1),
                lever=item.lever,
                evidence=item.evidence,
            )
            for item in ranked
        ],
        profile=ProfileView(
            traits=[
                TraitView(
                    trait=row.trait,
                    label=TRAIT_LABELS.get(row.trait, row.trait),
                    value=_trait_value(row.value, row.unit),
                    observations=row.observations,
                    basis=row.basis,
                )
                for row in sorted(held.values(), key=lambda r: r.trait)
            ],
            zones=zones,
        ),
        experiment=_experiment_view(current, today) if current is not None else None,
        caveat=CAVEAT,
    )


class StartExperiment(BaseModel):
    tag: str
    metric: str
    lag: int = 1
    days: int = experiments.DEFAULT_DAYS


@router.post("/experiment", response_model=ExperimentView)
async def begin(body: StartExperiment, user: CurrentUserDep, session: SessionDep) -> ExperimentView:
    """Start an N-of-1. Starting a second one abandons the first, deliberately."""
    if body.tag not in tags.BY_NAME:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{body.tag}' is not something this app knows how to log",
        )
    if body.metric not in PHRASE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{body.metric}' is not a metric an experiment can ask about",
        )
    if body.lag not in (0, 1):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "an effect is either same-day or next-day"
        )

    proposal = experiments.propose(tag=body.tag, metric=body.metric, lag=body.lag, days=body.days)
    row = await experiments.start(session, user_id=user.id, proposal=proposal)
    return _experiment_view(row, datetime.now(UTC).date())
