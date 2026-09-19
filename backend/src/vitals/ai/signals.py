"""Deciding whether there is anything worth saying — in Python, before the model runs.

This is what makes the daily brief *quiet*. A model asked "write a note about this
day" will always find something to say, every day, because that is the task it was
given; an app built that way nags. So the judgement is made here instead, by rules
with published thresholds, and the model is told plainly when the answer is "nothing".

Each signal carries its own finished sentence. That serves three purposes at once: it
is what the model is shown, it is what the model is allowed to quote, and it is what
the brief falls back to when there is no API key or the model cannot stay grounded.
The last one matters most — the daily brief is never blocked on an LLM being available
or well behaved, because a health app that goes silent when a vendor has an outage is
not a health app.

Thresholds are calibration, not measurement, so they are named constants with the
claim they rest on written beside them. Phase 8 fits them to the individual.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vitals.analytics import canonical as gold
from vitals.api import format as fmt
from vitals.db.models import ScoreContribution, ScorePillar
from vitals.score.compose import MIN_TRUSTED_COVERAGE
from vitals.score.pillars import BY_NAME
from vitals.score.verdict import MIXED

# Three is the whole budget. A note that raises five things has prioritised nothing,
# and the point of ranking them is to be allowed to drop the rest.
MAX_SIGNALS = 3

# Points of score movement against the fortnight before it counts as a change rather
# than noise. Day-to-day score variance at steady state sits well under this.
SCORE_MOVE_POINTS = 5.0
# A contribution scoring below this is dragging; above it, it is merely not perfect.
DRAG_POINTS = 40.0
# ...and one scoring above this is genuinely going well, which is worth one sentence
# on a day when nothing is wrong.
LIFT_POINTS = 85.0

# Gabbett's acute:chronic workload ratio: roughly 0.8-1.3 is the settled range, and
# the injury-risk association climbs above it. Below it is detraining, not danger.
ACWR_LOW = 0.8
ACWR_HIGH = 1.3
# Foster's monotony: sustained values above 2 track with illness and overreaching.
MONOTONY_HIGH = 2.0
# Cumulative shortfall against the nightly need, over the debt window. Three hours is
# about the point at which the deficit stops being one bad night.
SLEEP_DEBT_SECONDS = 3 * 3600.0


@dataclass(frozen=True, slots=True)
class Signal:
    kind: str
    # Finished prose with finished numbers. Never a template the model fills in.
    sentence: str
    # Ranking only. Higher wins a place in the three.
    severity: float


def _label(metric: str) -> str:
    for pillar in BY_NAME.values():
        for contribution in pillar.contributions:
            if contribution.metric == metric:
                return contribution.label
    return metric


def detect(
    *,
    score: float,
    coverage: float,
    trusted: bool,
    pillars: Sequence[ScorePillar],
    contributions: Sequence[ScoreContribution],
    history: Sequence[float],
    context: dict[str, float],
) -> tuple[Signal, ...]:
    """Every rule that fires, ranked, truncated to the budget.

    `pillars` and `contributions` are the stored rows for the day; `context` holds the
    gold readings the score does not contribute from. Nothing here reads a database or
    a clock, so the same day always produces the same signals.
    """
    found: list[Signal] = []

    if not trusted:
        # Said first when it fires, because it qualifies every other sentence: these
        # numbers are real, there are just not many of them behind it.
        found.append(
            Signal(
                kind="thin_data",
                sentence=(
                    f"Only {fmt.percent(coverage)} of the score's inputs were "
                    f"present, below the {fmt.percent(MIN_TRUSTED_COVERAGE)} needed to "
                    "call it trustworthy — read today's number loosely."
                ),
                severity=90,
            )
        )

    if history:
        mean = sum(history) / len(history)
        delta = score - mean
        if abs(delta) >= SCORE_MOVE_POINTS:
            way = "above" if delta > 0 else "below"
            found.append(
                Signal(
                    kind="score_moved",
                    sentence=(
                        f"Today's {fmt.score(score)} is {fmt.number(abs(delta), places=0)} "
                        f"points {way} your {len(history)}-day mean of {fmt.score(mean)}."
                    ),
                    severity=60 + min(abs(delta), 30),
                )
            )

    weakest = min(pillars, key=lambda p: p.score, default=None)
    if weakest is not None and weakest.score < MIXED:
        label = BY_NAME[weakest.pillar].label if weakest.pillar in BY_NAME else weakest.pillar
        found.append(
            Signal(
                kind="low_pillar",
                sentence=(
                    f"{label} is your weakest pillar today at {fmt.score(weakest.score)} "
                    "out of 100."
                ),
                severity=70,
            )
        )

    acwr = context.get(gold.ACWR)
    if acwr is not None and not ACWR_LOW <= acwr <= ACWR_HIGH:
        if acwr > ACWR_HIGH:
            sentence = (
                f"Your acute-to-chronic load ratio is {fmt.number(acwr, places=2)}, above "
                f"the settled range of {ACWR_LOW} to {ACWR_HIGH} — the last week has "
                "outrun what the last six built."
            )
            severity = 75.0
        else:
            sentence = (
                f"Your acute-to-chronic load ratio is {fmt.number(acwr, places=2)}, below "
                f"the settled range of {ACWR_LOW} to {ACWR_HIGH} — you are training less "
                "than your base is used to."
            )
            severity = 45.0
        found.append(Signal(kind="load_balance", sentence=sentence, severity=severity))

    monotony = context.get(gold.MONOTONY)
    if monotony is not None and monotony > MONOTONY_HIGH:
        found.append(
            Signal(
                kind="monotony",
                sentence=(
                    f"Training monotony is {fmt.number(monotony, places=2)}, above "
                    f"{fmt.number(MONOTONY_HIGH, places=1)} — this week's days look much "
                    "alike, which is the pattern that tracks with overreaching."
                ),
                severity=55,
            )
        )

    debt = context.get(gold.SLEEP_DEBT)
    if debt is not None and debt >= SLEEP_DEBT_SECONDS:
        found.append(
            Signal(
                kind="sleep_debt",
                sentence=(
                    f"Sleep debt has reached {fmt.duration(debt)} against your nightly need."
                ),
                severity=65,
            )
        )

    worst = min(contributions, key=lambda c: c.points, default=None)
    if worst is not None and worst.points < DRAG_POINTS:
        found.append(
            Signal(
                kind="drag",
                sentence=(
                    f"{_label(worst.metric)} scored {fmt.score(worst.points)} out of 100, "
                    "the weakest line in today's score."
                ),
                severity=50,
            )
        )

    # Only when nothing is wrong. On a bad day this would read as consolation, which is
    # worse than saying nothing.
    if not found:
        best = max(contributions, key=lambda c: c.points, default=None)
        if best is not None and best.points >= LIFT_POINTS:
            found.append(
                Signal(
                    kind="lift",
                    sentence=(
                        f"{_label(best.metric)} scored {fmt.score(best.points)}, the "
                        "strongest line in today's score."
                    ),
                    severity=20,
                )
            )

    found.sort(key=lambda s: s.severity, reverse=True)
    return tuple(found[:MAX_SIGNALS])
