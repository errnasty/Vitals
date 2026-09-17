"""Silver: provider JSON turned into one canonical vocabulary.

The layer exists so that nothing above it ever learns what a `bodyBatteryValuesArray`
is. Bronze keeps Garmin's words verbatim and forever; this package translates them
once, into metrics declared in `canonical`, and everything from phase 4 up reads only
the translation.

Because normalizers are pure and the runner is idempotent, silver is disposable: drop
every row, run `vitals normalize`, and it rebuilds identically from bronze. A
normalizer bug is therefore a recompute, never data loss — which is the whole reason
the raw store came first.
"""

from vitals.normalize.model import (
    ActivityRecord,
    Bronze,
    DailyValue,
    Normalized,
    Sample,
    SleepRecord,
)
from vitals.normalize.resolver import Point, available_metrics, daily_series
from vitals.normalize.runner import EndpointCoverage, NormalizeResult, normalize

__all__ = [
    "ActivityRecord",
    "Bronze",
    "DailyValue",
    "EndpointCoverage",
    "NormalizeResult",
    "Normalized",
    "Point",
    "Sample",
    "SleepRecord",
    "available_metrics",
    "daily_series",
    "normalize",
]
