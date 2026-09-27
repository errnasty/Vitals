"""What can honestly be personalised, and what cannot.

Phase 5 wrote that its weights were "a starting calibration, not a finding", and that
phase 8 would fit them to the individual. Having got here, that promise was wrong and
this file does not keep it.

**Pillar weights are not fitted, and cannot be.** Fitting requires an outcome to fit
against, and the Vitals Score has none — it *is* the weighted sum, so regressing it on
its own components recovers the weights that were put in. The only real outcome would
be something like how well someone felt or performed, which this app does not measure
and could not measure without asking every day. Four free parameters against a few
hundred autocorrelated days of one person would fit noise beautifully and generalise
to nothing. An app that shipped per-user weights on that basis would look far more
personalised and be strictly less true.

**What evidence can support is anchors and ranking.** Two things:

*Anchors* are the constants the scoring curves compare against — a maximum heart rate,
a nightly sleep need. These are measured, not fitted: the number either is in the data
or is not, and when it is not there is no trait, rather than a guess dressed up. This
is where the heart-rate zones that phase 3b deliberately refused to invent finally come
from, because "your observed maximum across four years of training" is a real anchor
and "220 minus your age" is a number that looks precise and is not.

*Ranking* is which advice to give first. That is a question about what moves **your**
numbers, and the correlation engine already answers it from your own days, with a
correction for how many things it tried. Phase 8 does not need a new statistical idea;
it needs to point the one already here at the levers the score exposes.

Every trait carries the evidence behind it, because a personalised constant with no
sample size is indistinguishable from a made-up one.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── anchors ─────────────────────────────────────────────────────────────────────
MAX_HR = "max_hr"
RESTING_HR_FLOOR = "resting_hr_floor"
SLEEP_NEED = "sleep_need"
HRV_TYPICAL = "hrv_typical"

# ── zones, derived from the anchors above ───────────────────────────────────────
# Boundaries as a fraction of maximum heart rate. These are the widely used
# five-zone percentages; they are conventional rather than discovered, and the only
# personalised part is what they are a percentage *of*.
ZONE_BOUNDS: tuple[float, ...] = (0.50, 0.60, 0.70, 0.80, 0.90)
ZONE_LABELS: tuple[str, ...] = ("Recovery", "Endurance", "Tempo", "Threshold", "VO2max")


@dataclass(frozen=True, slots=True)
class TraitDef:
    name: str
    unit: str
    # What it is measured from, in one line, for a screen that has to justify it.
    source: str
    # Below this many observations the trait is not written at all.
    min_observations: int


REGISTRY: dict[str, TraitDef] = {
    t.name: t
    for t in (
        TraitDef(
            name=MAX_HR,
            unit="bpm",
            source="the highest heart rate seen in any recorded activity",
            # One freak reading from a loose strap would otherwise define every zone.
            min_observations=10,
        ),
        TraitDef(
            name=RESTING_HR_FLOOR,
            unit="bpm",
            source="the lowest resting heart rate seen on a well-rested morning",
            min_observations=30,
        ),
        TraitDef(
            name=SLEEP_NEED,
            unit="s",
            source="the nightly duration your own next-day HRV is best after",
            min_observations=60,
        ),
        TraitDef(
            name=HRV_TYPICAL,
            unit="ms",
            source="the middle of your own overnight HRV distribution",
            min_observations=30,
        ),
    )
}


class UnknownTrait(KeyError):
    """A name this vocabulary does not define."""


def trait_for(name: str) -> TraitDef:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise UnknownTrait(name) from exc


def zones(max_hr: float) -> list[tuple[str, float, float]]:
    """`(label, lower bpm, upper bpm)` for each zone, against a measured maximum.

    Returned rather than stored, because it is arithmetic on one trait and storing
    both is how the two come to disagree.
    """
    bounds = [max_hr * f for f in ZONE_BOUNDS]
    out: list[tuple[str, float, float]] = []
    for index, label in enumerate(ZONE_LABELS):
        lower = bounds[index]
        upper = bounds[index + 1] if index + 1 < len(bounds) else max_hr
        out.append((label, lower, upper))
    return out
