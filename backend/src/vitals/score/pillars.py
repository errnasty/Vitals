"""The four pillars, and every calibration claim the score makes.

This file is the opinionated one. Everything else in phase 5 is arithmetic; this is
where the app decides what "good" means, and it is written to be argued with — each
contribution names its anchor, its weight and why it is there, so disagreeing is a
matter of editing a number rather than reverse-engineering a formula.

Weights are a starting calibration, not a finding. Phase 8 fits them to the
individual; until then they are one defensible reading of the evidence.

**What is deliberately not scored: body weight.** There is no direction that is right
without knowing someone's goal, and a daily health score that silently rewards weight
loss is the kind of thing that hurts people with a history of disordered eating. Weight
and body-fat trends stay visible in the app as trends. They do not become a verdict.

**Sleep stages are also left out.** Wrist-based deep and REM estimates agree with
polysomnography only moderately, and scoring them would spend the user's attention on
the least trustworthy number on the screen.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vitals.analytics import canonical as gold
from vitals.score.curves import band, percentile, ramp

# value, personal history -> points, or None when it cannot be scored honestly.
Scorer = Callable[[float, Sequence[float]], float | None]

HOUR = 3600.0


def anchored(fn: Callable[[float], float]) -> Scorer:
    """Score against an external reference; the person's own history is irrelevant."""

    def scorer(value: float, history: Sequence[float]) -> float | None:
        return fn(value)

    return scorer


def personal(days: int) -> Scorer:
    """Score against this person's own recent distribution of the same metric."""

    def scorer(value: float, history: Sequence[float]) -> float | None:
        return percentile(value, history)

    scorer.history_days = days  # type: ignore[attr-defined]
    return scorer


def history_days(scorer: Scorer) -> int:
    return int(getattr(scorer, "history_days", 0))


@dataclass(frozen=True, slots=True)
class Contribution:
    metric: str
    label: str
    weight: float
    scorer: Scorer
    # Shown in the waterfall and handed to the phase-7 model as the reason this line
    # exists. Never a number — the numbers come from the columns.
    rationale: str


@dataclass(frozen=True, slots=True)
class Pillar:
    name: str
    label: str
    weight: float
    contributions: tuple[Contribution, ...]


RECOVERY = Pillar(
    name="recovery",
    label="Recovery",
    weight=30,
    contributions=(
        Contribution(
            metric=gold.HRV_DEVIATION,
            label="Overnight HRV",
            weight=40,
            # Two standard deviations below your own baseline is the floor; anything at
            # or above it is full marks, because a high HRV is not a thing to chase.
            scorer=anchored(lambda z: ramp(z, zero_at=-2.0, hundred_at=0.5)),
            rationale="the clearest single overnight signal of accumulated stress",
        ),
        Contribution(
            metric=gold.RHR_DEVIATION,
            label="Resting heart rate",
            weight=30,
            scorer=anchored(lambda z: ramp(z, zero_at=2.0, hundred_at=-0.5)),
            rationale="an elevated resting rate tracks strain, illness and poor sleep",
        ),
        Contribution(
            metric=gold.TSB,
            label="Form",
            weight=30,
            # Deeply negative is a body carrying more fatigue than fitness. Above zero
            # is rested; whether that has gone too far is the training pillar's problem.
            scorer=anchored(lambda tsb: ramp(tsb, zero_at=-30.0, hundred_at=5.0)),
            rationale="fitness minus fatigue: what the last six weeks left you with",
        ),
    ),
)

SLEEP = Pillar(
    name="sleep",
    label="Sleep",
    weight=25,
    contributions=(
        Contribution(
            metric=gold.SLEEP_DURATION_7D,
            label="Sleep duration",
            weight=35,
            # The 7-9 hour adult recommendation, scored on the week rather than the
            # night, because one short night is noise and a short week is not.
            scorer=anchored(lambda s: ramp(s, zero_at=5 * HOUR, hundred_at=8 * HOUR)),
            rationale="the seven-night average, against the adult recommendation",
        ),
        Contribution(
            metric=gold.SLEEP_DEBT,
            label="Sleep debt",
            weight=25,
            scorer=anchored(lambda s: ramp(s, zero_at=14 * HOUR, hundred_at=0.0)),
            rationale="a fortnight of shortfalls, which do not clear with one long night",
        ),
        Contribution(
            metric=gold.SLEEP_CONSISTENCY,
            label="Sleep regularity",
            weight=25,
            # Regularity predicts outcomes independently of how long you sleep, which
            # is why it carries the same weight as the debt.
            scorer=anchored(lambda m: ramp(m, zero_at=90.0, hundred_at=20.0)),
            rationale="how much your sleep midpoint moves; regularity matters on its own",
        ),
        Contribution(
            metric=gold.SLEEP_EFFICIENCY,
            label="Sleep efficiency",
            weight=15,
            scorer=anchored(lambda pct: ramp(pct, zero_at=70.0, hundred_at=90.0)),
            rationale="time asleep against time in bed; 85% is the usual clinical line",
        ),
    ),
)

TRAINING = Pillar(
    name="training",
    label="Training",
    weight=20,
    contributions=(
        Contribution(
            metric=gold.CTL,
            label="Fitness",
            weight=40,
            # No absolute anchor exists: a chronic load of 80 is a strong base for one
            # person and a deload for another. Six months of your own is the scale.
            scorer=personal(180),
            rationale="chronic training load, against your own last six months",
        ),
        Contribution(
            metric=gold.ACWR,
            label="Load balance",
            weight=35,
            scorer=anchored(lambda r: band(r, low=0.8, high=1.3, margin=0.5)),
            rationale="this week against the last six; both a spike and a collapse cost",
        ),
        Contribution(
            metric=gold.MONOTONY,
            label="Variety",
            weight=25,
            scorer=anchored(lambda m: ramp(m, zero_at=2.5, hundred_at=1.0)),
            rationale="Foster's monotony: the same session every day is its own risk",
        ),
    ),
)

LONGEVITY = Pillar(
    name="longevity",
    label="Longevity",
    weight=25,
    contributions=(
        Contribution(
            metric=gold.VO2MAX_TREND,
            label="Cardiorespiratory fitness",
            weight=40,
            # Absolute VO2max norms are age- and sex-adjusted and this app holds
            # neither, so the honest comparison is against your own year.
            scorer=personal(365),
            rationale="the strongest single predictor here, against your own year",
        ),
        Contribution(
            metric=gold.ACTIVITY_GUIDELINE_PCT,
            label="Weekly activity",
            weight=35,
            scorer=anchored(lambda pct: ramp(pct, zero_at=0.0, hundred_at=100.0)),
            rationale="against the WHO's 150 weekly minutes, vigorous counting double",
        ),
        Contribution(
            metric=gold.STEPS_7D,
            label="Daily movement",
            weight=25,
            # The all-cause mortality curve flattens around 7-8k/day; past that there
            # is little left to gain, so there is no reward for chasing 20,000.
            scorer=anchored(lambda steps: ramp(steps, zero_at=2000.0, hundred_at=8000.0)),
            rationale="where the mortality curve flattens, not a round number",
        ),
    ),
)

PILLARS: tuple[Pillar, ...] = (RECOVERY, SLEEP, TRAINING, LONGEVITY)

BY_NAME: dict[str, Pillar] = {pillar.name: pillar for pillar in PILLARS}
