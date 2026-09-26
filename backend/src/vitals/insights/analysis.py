"""Testing whether a tagged day really does move a number.

Pure arithmetic: days in, findings out. No database, no clock, no I/O — so the
statistics can be argued with on their own terms, which matters more here than
anywhere else in the app.

**Why a permutation test.** The obvious choice is a t-test, and it is the wrong one.
A year of tagged days is a small, lumpy, autocorrelated sample of one person; the
distributional assumptions behind a t-test are not met, and the p-value it produced
would be confidently wrong. A permutation test asks a question that needs no
assumptions at all: if these labels meant nothing, how often would chance alone
produce a gap this big? Shuffle the labels a few thousand times and count. It is
slower, it is honest, and it needs nothing beyond the standard library.

**Why the correction.** Nine tags against a dozen metrics at two lags is a few hundred
tests. At p < 0.05 roughly one in twenty comes back "significant" with nothing behind
it — so an uncorrected run would hand you ten exciting discoveries, all noise, every
single time. Benjamini-Hochberg controls the false discovery rate across the whole
family, which is the right correction when the question is "which of these are worth
looking at" rather than "is this one specific thing true".

**Why the floors.** Below a handful of observations on either side no test means
anything, however good the arithmetic. And a difference too small to feel is not worth
a sentence even when it is real. Both are refusals to report, not caveats attached to
a report.

The honest consequence of all three: this will usually find nothing, especially early
on. That is the correct output for most people most of the time, and an engine that
always finds something is an engine that is lying.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

# Below this many days on either side of the split, no arithmetic rescues the sample.
MIN_GROUP = 6
# Shuffles. Enough that the smallest reportable p-value (~1/2001) sits well under the
# thresholds, without making a refresh take minutes.
PERMUTATIONS = 2000
# The false-discovery rate the correction targets.
FDR = 0.10
# A difference smaller than this fraction of the metric's own spread is not worth a
# sentence even if it is real — nobody can feel a quarter of a standard deviation.
MIN_EFFECT = 0.25
# Fixed, so the same data produces the same findings. A report that changes when you
# reload it is a report nobody can act on.
SEED = 20_260_926


@dataclass(frozen=True, slots=True)
class Observation:
    """One day: whether the tag was on, and what the metric read."""

    day: date
    tagged: bool
    value: float


@dataclass(frozen=True, slots=True)
class Finding:
    tag: str
    metric: str
    # 0 = the same day, 1 = the day after. Alcohol tonight shows up in tomorrow's HRV.
    lag: int
    n_with: int
    n_without: int
    mean_with: float
    mean_without: float
    delta: float
    # Standardised, so effects on different metrics can be ranked against each other.
    effect: float
    p_value: float
    # Set by the correction, once the whole family is known.
    significant: bool = False

    @property
    def direction(self) -> str:
        return "higher" if self.delta > 0 else "lower"


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _pooled_sd(a: Sequence[float], b: Sequence[float]) -> float:
    """Spread across both groups, for standardising the difference."""
    combined = [*a, *b]
    if len(combined) < 2:
        return 0.0
    mean = _mean(combined)
    variance = sum((value - mean) ** 2 for value in combined) / (len(combined) - 1)
    return float(variance**0.5)


def _permutation_p(
    values: Sequence[float], n_with: int, observed: float, rng: random.Random
) -> float:
    """How often chance alone produces a gap at least this big.

    Two-sided, with the +1 on both parts: 2000 shuffles cannot justify a p-value of
    exactly zero, and reporting one would overstate what the test can see.
    """
    pool = list(values)
    extreme = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(pool)
        shuffled = _mean(pool[:n_with]) - _mean(pool[n_with:])
        if abs(shuffled) >= abs(observed):
            extreme += 1
    return (extreme + 1) / (PERMUTATIONS + 1)


def test_one(
    observations: Sequence[Observation],
    *,
    tag: str,
    metric: str,
    lag: int,
    rng: random.Random,
) -> Finding | None:
    """One tag against one metric at one lag, or None when the sample cannot support it.

    Note what this does *not* do: it does not skip a test because the effect looks
    small. Every test that can be run has to be run and counted, because the
    correction below divides by how many were performed — see `analyse`.
    """
    with_tag = [o.value for o in observations if o.tagged]
    without = [o.value for o in observations if not o.tagged]

    if len(with_tag) < MIN_GROUP or len(without) < MIN_GROUP:
        return None

    mean_with, mean_without = _mean(with_tag), _mean(without)
    delta = mean_with - mean_without

    spread = _pooled_sd(with_tag, without)
    if spread <= 0:
        # The metric never moved. Nothing to attribute to anything.
        return None

    effect = delta / spread

    return Finding(
        tag=tag,
        metric=metric,
        lag=lag,
        n_with=len(with_tag),
        n_without=len(without),
        mean_with=mean_with,
        mean_without=mean_without,
        delta=delta,
        effect=effect,
        p_value=_permutation_p([*with_tag, *without], len(with_tag), delta, rng),
    )


def correct(findings: Sequence[Finding]) -> list[Finding]:
    """Benjamini-Hochberg across the whole family, marking what survives.

    Every finding is returned, not only the survivors: how many were tested is what
    makes a survivor meaningful, and a caller that wants to say "three of two hundred"
    needs both numbers.
    """
    if not findings:
        return []

    ranked = sorted(findings, key=lambda f: f.p_value)
    total = len(ranked)

    # The largest rank whose p-value clears its own threshold. Everything at or below
    # that rank survives — including any whose own p-value would have failed, which is
    # the step-up behaviour that makes this Benjamini-Hochberg rather than a filter.
    cutoff = 0
    for index, finding in enumerate(ranked, start=1):
        if finding.p_value <= (index / total) * FDR:
            cutoff = index

    return [
        replace(finding, significant=index <= cutoff)
        for index, finding in enumerate(ranked, start=1)
    ]


def observations_for(
    *, tagged_days: set[date], series: dict[date, float], lag: int
) -> list[Observation]:
    """Pair each day's metric with whether the tag was set `lag` days earlier.

    A day with no reading is absent rather than filled in. Interpolating here would
    invent the very thing being measured.
    """
    return [
        Observation(day=day, tagged=(day - timedelta(days=lag)) in tagged_days, value=value)
        for day, value in series.items()
    ]


def analyse(
    *,
    tagged: dict[str, set[date]],
    series: dict[str, dict[date, float]],
    lags: Sequence[int] = (0, 1),
) -> list[Finding]:
    """Every tag against every metric at every lag, corrected as one family.

    The order of the last two steps is the part that matters, and getting it wrong is
    silent. **Correct first, then filter by effect size.** Correcting over only the
    findings that already survived a filter divides by the wrong number — the whole
    point of Benjamini-Hochberg is that the denominator is how many tests were
    *performed*, and a pre-filter hides most of them. Done in the wrong order on pure
    noise, this engine reported fifteen confident discoveries; done in this order, it
    reports none.

    So a finding too small to act on still counts toward the correction even though it
    is never shown. It was a test, and it has to pay for itself.
    """
    rng = random.Random(SEED)
    tested: list[Finding] = []

    for tag, days in sorted(tagged.items()):
        for metric, readings in sorted(series.items()):
            for lag in lags:
                result = test_one(
                    observations_for(tagged_days=days, series=readings, lag=lag),
                    tag=tag,
                    metric=metric,
                    lag=lag,
                    rng=rng,
                )
                if result is not None:
                    tested.append(result)

    corrected = correct(tested)
    # Only now: real but too small to feel is not worth a sentence.
    return [finding for finding in corrected if abs(finding.effect) >= MIN_EFFECT]
