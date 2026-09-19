"""Garmin Connect (pull source).

Read through the unofficial Connect API via `python-garminconnect`, because the
official Health API does not support personal use and the commercial aggregators are
B2B-only. That path is fragile by nature, so the fragile part is quarantined here and
everything downstream depends only on bronze.
"""

from vitals.sources.garmin.client import (
    GarminClient,
    GarminError,
    MFARequired,
    NeedsReauth,
    RateLimited,
    begin_login,
    finish_login,
    login_with_credentials,
)
from vitals.sources.garmin.governor import (
    BudgetExhausted,
    CircuitOpen,
    GovernorState,
    RateGovernor,
    RateLimits,
)
from vitals.sources.garmin.source import SOURCE, GarminSource

__all__ = [
    "SOURCE",
    "BudgetExhausted",
    "CircuitOpen",
    "GarminClient",
    "GarminError",
    "GarminSource",
    "GovernorState",
    "MFARequired",
    "NeedsReauth",
    "RateGovernor",
    "RateLimited",
    "RateLimits",
    "begin_login",
    "finish_login",
    "login_with_credentials",
]
