"""Training load: what the last six weeks did to you.

The model is the standard impulse-response one — an exponentially weighted long-term
average standing for fitness, a short-term one for fatigue, and their difference for
form. It is forty years old, it is what every endurance platform ships, and its value
is in the trend rather than the absolute number.

The one judgement call worth stating: a day the watch was worn with no workout on it
is a **zero**, and a day the watch was not worn at all is **unknown**. Conflating them
is the difference between a rest week reading as recovery and reading as data loss.
Fitness decays through the first and holds through the second.
"""

from __future__ import annotations

from datetime import date, timedelta

from vitals.analytics import canonical as d
from vitals.analytics.math import ewma, mean, stdev
from vitals.analytics.model import Derived
from vitals.analytics.series import Inputs
from vitals.normalize import canonical as silver

# Time constants, in days. 42/7 is the settled pairing: six weeks of adaptation
# against one week of fatigue.
CTL_DAYS = 42
ATL_DAYS = 7
WEEK = 7

# How much run-up an exponential average needs before it has forgotten where it
# started. Four time constants leaves under 2% of the seed.
#
# This is not a refinement. An exponential average seeded from the first value of a
# window exactly one time constant long is *dominated* by that first value — and as
# the window slides, the seed alternates between a hard day and a rest day. Computed
# that way, "fitness" swung between 55 and 120 on consecutive days while the athlete
# trained an identical week. The run-up is what makes the number mean anything.
WARMUP_FACTOR = 4
CTL_WARMUP_DAYS = CTL_DAYS * WARMUP_FACTOR

# Foster's monotony divides the week's mean load by its spread, which is undefined for
# a week of identical sessions — and that week is the *most* monotonous one there is,
# so dropping it would lose exactly the case the metric exists to flag. Reported at a
# ceiling instead, well clear of the 2.0 that is usually read as the warning line.
MONOTONY_CEILING = 5.0

# Evidence that the watch was on the wrist at all. Any one of these present means a
# day with no activity is a genuine rest day rather than a hole in the record.
WEAR_EVIDENCE = (silver.STEPS, silver.RESTING_HR, silver.SLEEP_DURATION)


def was_tracked(inputs: Inputs, day: date) -> bool:
    return any(inputs.get(metric).at(day) is not None for metric in WEAR_EVIDENCE)


def load_history(inputs: Inputs, day: date, days: int) -> list[float | None]:
    """Daily training load ending on `day`: a number, a zero, or unknown."""
    history: list[float | None] = []
    for offset in range(days - 1, -1, -1):
        current = day - timedelta(days=offset)
        recorded = inputs.activity_load.get(current)
        if recorded is not None:
            history.append(recorded)
        elif was_tracked(inputs, current):
            history.append(0.0)
        else:
            history.append(None)
    return history


def compute(inputs: Inputs, day: date) -> list[Derived]:
    out: list[Derived] = []

    # From the recording, where there is one. Absent rather than zero on a day with
    # no FIT file — "the altimeter said nothing" and "you climbed nothing" are
    # different facts, and a zero here would flatten a mountain week into the
    # baseline of anyone whose history predates the downloads.
    recorded = inputs.recordings.get(day)
    if recorded is not None:
        if recorded.decoupling_pct is not None:
            out.append(
                Derived(
                    metric=d.DECOUPLING,
                    calendar_date=day,
                    value=recorded.decoupling_pct,
                    inputs=1,
                )
            )
        if recorded.ascent_m is not None:
            out.append(
                Derived(metric=d.ASCENT, calendar_date=day, value=recorded.ascent_m, inputs=1)
            )

    today_load = inputs.activity_load.get(day)
    tracked_today = was_tracked(inputs, day)
    if today_load is not None or tracked_today:
        out.append(
            Derived(
                metric=d.TRAINING_LOAD,
                calendar_date=day,
                value=today_load or 0.0,
                # A rest day is one real observation, not zero observations.
                inputs=1,
            )
        )

    # The averages run over every day available, not just the window they are named
    # for; the name is the time constant, not the amount of history it needs.
    history = load_history(inputs, day, CTL_WARMUP_DAYS)
    observed = sum(1 for value in history if value is not None)
    if observed == 0:
        return out

    ctl = ewma(history, time_constant_days=CTL_DAYS)[-1]
    atl = ewma(history, time_constant_days=ATL_DAYS)[-1]
    if ctl is None or atl is None:
        return out

    # Coverage is still a claim about the six weeks the number describes, however
    # much run-up went into computing it.
    recent = sum(1 for value in history[-CTL_DAYS:] if value is not None)
    out.append(Derived(metric=d.CTL, calendar_date=day, value=ctl, inputs=recent))
    out.append(Derived(metric=d.ATL, calendar_date=day, value=atl, inputs=min(observed, ATL_DAYS)))
    out.append(Derived(metric=d.TSB, calendar_date=day, value=ctl - atl, inputs=observed))

    if ctl > 0:
        # Acute:chronic ratio. Read as a trend and a rate of change, not a threshold —
        # the "danger zone" literature it comes from has not held up well.
        out.append(Derived(metric=d.ACWR, calendar_date=day, value=atl / ctl, inputs=recent))

    out.extend(_weekly_strain(inputs, day))
    return out


def _weekly_strain(inputs: Inputs, day: date) -> list[Derived]:
    """Foster's monotony and strain: how *evenly* the week's load was spread.

    Two weeks with identical totals are not equivalent — the one that put it all in
    two sessions is the one that gets people injured. Monotony is the week's mean load
    over its standard deviation, and strain multiplies it back by the total.
    """
    week = [value for value in load_history(inputs, day, WEEK) if value is not None]
    if len(week) < 2:
        return []

    average = mean(week)
    spread = stdev(week)
    if average is None or spread is None:
        return []

    if spread > 0:
        monotony = average / spread
    elif average > 0:
        monotony = MONOTONY_CEILING
    else:
        # A week of complete rest: no load to be monotonous about.
        return []
    return [
        Derived(metric=d.MONOTONY, calendar_date=day, value=monotony, inputs=len(week)),
        Derived(metric=d.STRAIN, calendar_date=day, value=sum(week) * monotony, inputs=len(week)),
    ]
