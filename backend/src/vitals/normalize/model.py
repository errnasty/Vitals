"""What a normalizer returns.

Normalizers are **pure functions**: bronze row in, canonical records out, no database,
no clock, no network. That is not purity for its own sake — it is what makes the whole
layer re-runnable. Every silver row is a deterministic function of a bronze payload, so
fixing a normalizer and recomputing produces exactly the state you would have had if
it had been right the first time.

It also makes them trivially testable: a payload literal in, a `Normalized` out, no
fixtures and no database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Bronze:
    """One `raw_payload` row, as a normalizer sees it."""

    endpoint: str
    payload: Any
    calendar_date: date | None = None
    entity_key: str | None = None


@dataclass(frozen=True, slots=True)
class DailyValue:
    metric: str
    calendar_date: date
    value: float


@dataclass(frozen=True, slots=True)
class Sample:
    metric: str
    recorded_at: datetime
    value: float


@dataclass(frozen=True, slots=True)
class SleepRecord:
    calendar_date: date
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_s: int | None = None
    deep_s: int | None = None
    light_s: int | None = None
    rem_s: int | None = None
    awake_s: int | None = None
    nap_s: int | None = None
    score: int | None = None
    avg_hrv: float | None = None
    avg_spo2: float | None = None
    avg_respiration: float | None = None


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    external_id: str
    name: str | None = None
    activity_type: str | None = None
    started_at: datetime | None = None
    duration_s: float | None = None
    moving_duration_s: float | None = None
    distance_m: float | None = None
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    avg_speed_mps: float | None = None
    max_speed_mps: float | None = None
    calories: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_power: float | None = None
    max_power: float | None = None
    normalized_power: float | None = None
    aerobic_training_effect: float | None = None
    anaerobic_training_effect: float | None = None
    training_load: float | None = None
    total_sets: int | None = None
    total_reps: int | None = None
    total_volume_kg: float | None = None


@dataclass(frozen=True, slots=True)
class Normalized:
    """Everything one bronze payload yields. Empty is a legitimate answer."""

    daily: list[DailyValue] = field(default_factory=list)
    samples: list[Sample] = field(default_factory=list)
    sleep: list[SleepRecord] = field(default_factory=list)
    activities: list[ActivityRecord] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.daily or self.samples or self.sleep or self.activities)

    @property
    def row_count(self) -> int:
        return len(self.daily) + len(self.samples) + len(self.sleep) + len(self.activities)


EMPTY = Normalized()
