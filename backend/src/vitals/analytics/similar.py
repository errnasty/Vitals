"""Finding the days most like this one.

**Why there is no pgvector here.** The roadmap said phase 9 would want it, and
deployment.md recorded the cost: Railway's official Postgres image does not ship the
extension, and moving to one that does means giving up the managed backups and
point-in-time recovery on a database whose whole purpose is to be kept forever.

That trade never had to be made, because this is not a vector-search problem. A day is
a dozen numbers, and a lifetime of them is a few thousand rows. Exact nearest-neighbour
over 3,000 days by 12 features is about 36,000 multiplications — under a millisecond,
in Python, with no index. pgvector earns its keep on millions of 1,536-dimensional
embeddings where exact search is genuinely infeasible and an approximate index is the
only option. Here an approximate index would be slower to build than the exact answer
is to compute, and it would return *approximately* the right days.

So: no extension, no image change, no lost backups, and the answer is exact.

**Why standardised features.** Resting heart rate moves over a range of about ten;
steps move over a range of about ten thousand. Euclidean distance on the raw numbers is
a step-count search with some rounding noise attached. Each feature is divided by its
own spread across the person's history, so "unusual for you" means the same amount on
every axis — which is also the only definition of similarity that survives someone
getting fitter.

**Why missing features are dropped rather than filled.** A day with no HRV reading is
not a day with average HRV. Distance is computed over the features both days have and
scaled by how many that was, so a day matched on three axes does not come out closer
than one matched on ten simply for having less to disagree about.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

# Fewer than this in common and the two days were not really compared.
MIN_SHARED_FEATURES = 4

# Below this spread a feature is constant and carries no information; dividing by it
# would turn rounding noise into the dominant axis.
MIN_SPREAD = 1e-9


@dataclass(frozen=True, slots=True)
class Neighbour:
    day: date
    # 0 is identical. Scaled per shared feature, so days matched on different numbers
    # of axes are comparable.
    distance: float
    shared: int
    # The features that were closest, strongest first — what made these days alike.
    alike: tuple[str, ...]
    # The features that differed most. Often the more interesting half.
    unlike: tuple[str, ...]


def spreads(rows: dict[date, dict[str, float]]) -> dict[str, float]:
    """One scale per feature, from the person's own history.

    The standard deviation rather than the range: one freak day would otherwise set
    the scale for every comparison, and every other day would look identical.
    """
    columns: dict[str, list[float]] = {}
    for values in rows.values():
        for name, value in values.items():
            columns.setdefault(name, []).append(value)

    out: dict[str, float] = {}
    for name, series in columns.items():
        if len(series) < 2:
            continue
        mean = sum(series) / len(series)
        variance = sum((v - mean) ** 2 for v in series) / (len(series) - 1)
        out[name] = math.sqrt(variance)
    return out


def _compare(
    target: dict[str, float], other: dict[str, float], scale: dict[str, float]
) -> tuple[float, int, list[tuple[str, float]]]:
    gaps: list[tuple[str, float]] = []
    total = 0.0
    for name, value in target.items():
        if name not in other:
            continue
        spread = scale.get(name, 0.0)
        if spread <= MIN_SPREAD:
            continue
        gap = abs(value - other[name]) / spread
        gaps.append((name, gap))
        total += gap * gap

    if not gaps:
        return math.inf, 0, []
    # Divided by the count, so a day matched on three axes is not automatically
    # closer than one matched on ten.
    return math.sqrt(total / len(gaps)), len(gaps), gaps


def nearest(
    rows: dict[date, dict[str, float]],
    *,
    target: date,
    limit: int = 5,
    exclude_within_days: int = 3,
) -> list[Neighbour]:
    """The days most like `target`, closest first.

    Days immediately around the target are excluded by default. Yesterday resembles
    today because it *is* nearly today — the same training block, the same week of
    sleep — and a list of the four days either side is a true answer that tells you
    nothing you did not know.
    """
    if target not in rows:
        return []

    scale = spreads(rows)
    reference = rows[target]

    found: list[Neighbour] = []
    for day, values in rows.items():
        if day == target or abs((day - target).days) <= exclude_within_days:
            continue

        distance, shared, gaps = _compare(reference, values, scale)
        if shared < MIN_SHARED_FEATURES:
            continue

        gaps.sort(key=lambda pair: pair[1])
        found.append(
            Neighbour(
                day=day,
                distance=distance,
                shared=shared,
                alike=tuple(name for name, _ in gaps[:3]),
                unlike=tuple(name for name, _ in reversed(gaps[-2:])),
            )
        )

    found.sort(key=lambda n: n.distance)
    return found[:limit]
