"""Turning a physiological number into points, and being honest about which kind it is.

Two kinds of scoring, and the difference matters more than the arithmetic.

**Anchored.** Some numbers have an external reference worth deferring to: the WHO's
150 weekly activity minutes, the 7-9 hours of sleep adults are advised, the step count
where the mortality curve flattens. These score against the anchor, and the anchor is
named in the code so it can be argued with.

**Personal.** Others have no meaningful absolute scale. A chronic training load of 80
is excellent for one person and a deload for another; a VO2max of 45 means nothing
without an age. These score as a percentile against that individual's own recent
history — which is also the only honest answer to "is this good?" when the only
comparison available is you.

Nothing here knows about pillars, databases or dates. A curve is a float in and a
float out, so the calibration is arguable on its own terms.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

MIN = 0.0
MAX = 100.0

# Which way is better. `within` is a band — both ends are worse than the middle.
HIGHER = "higher"
LOWER = "lower"
WITHIN = "within"
PERSONAL = "personal"


# A curve with its calibration still attached: value and personal history in, points
# out, or None when it cannot be scored honestly yet.
Scorer = Callable[[float, Sequence[float]], float | None]


@dataclass(frozen=True, slots=True)
class Target:
    """What full marks on this curve actually look like.

    The point of naming this is that "what should I aim for" is a question the
    calibration already answers — `hundred_at` *is* the target — and leaving it inside
    a lambda meant the app could score you against a number it could not show you.

    `optimal` is the value that scores 100. For a band it is the near edge, because
    telling someone in the middle of the range to move is nonsense. `floor` is where
    the curve bottoms out, kept so a screen can say what the scale is rather than
    presenting a number out of nowhere.
    """

    direction: str
    optimal: float | None = None
    floor: float | None = None
    band: tuple[float, float] | None = None
    # For a personal percentile: how much of your own history you are ranked against.
    history_days: int = 0


def ramp(value: float, *, zero_at: float, hundred_at: float) -> float:
    """Linear between two named points, clamped outside them.

    Works in either direction: `zero_at` above `hundred_at` scores lower-is-better
    (resting heart rate, sleep debt), and below it scores higher-is-better (steps,
    activity minutes). Naming both ends rather than a midpoint and a slope means the
    calibration reads as a claim someone can disagree with.
    """
    if zero_at == hundred_at:
        raise ValueError("a ramp needs two distinct points")
    fraction = (value - zero_at) / (hundred_at - zero_at)
    return max(MIN, min(MAX, fraction * MAX))


def band(value: float, *, low: float, high: float, margin: float) -> float:
    """Full marks inside a range, falling away over `margin` on either side.

    For quantities where both too little and too much are worse than the middle —
    acute:chronic workload being the one this was written for.
    """
    if low > high:
        raise ValueError("band low must not exceed high")
    if margin <= 0:
        raise ValueError("band margin must be positive")
    if low <= value <= high:
        return MAX
    distance = low - value if value < low else value - high
    return max(MIN, MAX * (1.0 - distance / margin))


# ── scorers ─────────────────────────────────────────────────────────────────────
#
# A `Scorer` is a curve with its calibration still attached. The functions above are
# the arithmetic; these bind the anchors to them and keep them readable afterwards,
# so `score/explain` can say "8h scores full marks, you are at 7h 16m" without any
# layer above re-deriving what the curve was.


def ramp_at(*, zero_at: float, hundred_at: float) -> Scorer:
    """A ramp scorer carrying the two points it was calibrated against."""

    def scorer(value: float, history: Sequence[float]) -> float | None:
        return ramp(value, zero_at=zero_at, hundred_at=hundred_at)

    scorer.target = Target(  # type: ignore[attr-defined]
        direction=HIGHER if hundred_at > zero_at else LOWER,
        optimal=hundred_at,
        floor=zero_at,
    )
    return scorer


def band_at(*, low: float, high: float, margin: float) -> Scorer:
    """A band scorer carrying the range that earns full marks."""

    def scorer(value: float, history: Sequence[float]) -> float | None:
        return band(value, low=low, high=high, margin=margin)

    scorer.target = Target(  # type: ignore[attr-defined]
        direction=WITHIN,
        band=(low, high),
        # No single optimal: anywhere inside the band is full marks, and nudging
        # someone who is already inside it would be advice invented by the UI.
        optimal=None,
    )
    return scorer


def against_yourself(days: int) -> Scorer:
    """A percentile scorer, ranked against this person's own recent history.

    No fixed target, and that is the honest answer rather than a gap: there is no
    number a VO2max "should" be without an age, so the only thing to beat is your own
    recent best — which the score layer fills in when it has the history in hand.
    """

    def scorer(value: float, history: Sequence[float]) -> float | None:
        return percentile(value, history)

    scorer.target = Target(direction=PERSONAL, history_days=days)  # type: ignore[attr-defined]
    scorer.history_days = days  # type: ignore[attr-defined]
    return scorer


def target_of(scorer: object) -> Target | None:
    """The calibration behind a scorer, when it kept one."""
    found = getattr(scorer, "target", None)
    return found if isinstance(found, Target) else None


def percentile(value: float, history: Sequence[float]) -> float | None:
    """Where `value` sits in this person's own recent distribution, as 0-100.

    Ties count as half, so a metric that barely moves scores near the middle rather
    than at an extreme decided by a rounding error. Returns None below a usable amount
    of history — a percentile against four observations is a number with no content,
    and the layer above turns that into missing coverage rather than a guess.
    """
    if len(history) < MIN_HISTORY:
        return None
    below = sum(1 for past in history if past < value)
    equal = sum(1 for past in history if past == value)
    return MAX * (below + equal / 2) / len(history)


# Below this, a personal percentile says more about the sample than the person.
MIN_HISTORY = 20
