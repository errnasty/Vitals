"""Turning numbers into the strings the UI renders.

Formatting belongs here, in Python, for the same reason every other calculation does.
The design system's contract is explicit — *components take formatted values, never raw
records* — and the root README's rule is that the UI layer has no arithmetic in it. A
React component deciding that 26400 seconds should read "7h 20m" is arithmetic in the
UI, and it is the kind that quietly disagrees with itself between two screens.

So the API ships `"7h 20m"`, and the browser renders it.
"""

from __future__ import annotations

MINUTE = 60
HOUR = 3600


def duration(seconds: float | None) -> str:
    """`26400` → `7h 20m`. Sleep, recovery time, anything measured in hours."""
    if seconds is None:
        return "—"
    total = int(round(seconds))
    hours, remainder = divmod(abs(total), HOUR)
    minutes = remainder // MINUTE
    sign = "-" if total < 0 else ""
    if hours:
        return f"{sign}{hours}h {minutes}m"
    return f"{sign}{minutes}m"


def minutes(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{int(round(value))} min"


def number(value: float | None, *, places: int = 0) -> str:
    """A plain number, thousands-separated, with no unit attached.

    Negatives get a real minus sign rather than the hyphen Python reaches for. At
    display sizes the two are visibly different widths, and one screen using each is
    the sort of thing that makes a layout feel slightly wrong without saying why.
    """
    if value is None:
        return "—"
    body = f"{round(abs(value)):,}" if places <= 0 else f"{abs(value):,.{places}f}"
    return f"−{body}" if value < 0 else body


def signed(value: float | None, *, places: int = 1, unit: str = "") -> str:
    """`-0.4` → `−0.4 kg`. Uses a real minus sign, not a hyphen."""
    if value is None:
        return "—"
    body = f"{abs(value):,.{places}f}"
    sign = "−" if value < 0 else "+"
    return f"{sign}{body}{f' {unit}' if unit else ''}"


def percent(fraction: float | None, *, of_one: bool = True) -> str:
    """`0.83` → `83%`. Pass `of_one=False` for a value already out of 100."""
    if fraction is None:
        return "—"
    value = fraction * 100 if of_one else fraction
    return f"{int(round(value))}%"


def score(value: float | None) -> str:
    if value is None:
        return "—"
    return str(int(round(value)))


def direction(delta: float | None, *, tolerance: float = 0.0) -> str:
    """Which way a number moved, as the design system's Delta expects it."""
    if delta is None or abs(delta) <= tolerance:
        return "flat"
    return "up" if delta > 0 else "down"


# Units a bare number cannot carry on its own. A waterfall has a column header to
# explain what `0.05` means; a sentence does not, and a model or a reader handed
# `0.05` for a heart-rate-variability line has every reason to think the HRV was 0.05.
UNIT_SUFFIX = {"sd": "SD from your own baseline", "au": "load units"}


def reading(value: float | None, unit: str) -> str:
    """A value for prose: like `metric`, but never leaves the unit to be guessed."""
    if value is None:
        return "—"
    if unit == "sd":
        # A z-score is a direction as much as a magnitude, so it keeps its sign.
        return f"{signed(value, places=2)} {UNIT_SUFFIX[unit]}"
    suffix = UNIT_SUFFIX.get(unit)
    text = metric(value, unit)
    return f"{text} {suffix}" if suffix else text


# How each canonical unit reads on screen. The vocabulary is small on purpose: a unit
# nobody has taught this table falls through to a plain number rather than guessing.
def metric(value: float | None, unit: str) -> str:
    """Format a silver or gold value the way its unit wants to be read."""
    if value is None:
        return "—"
    if unit == "s":
        return duration(value)
    if unit == "%":
        return percent(value, of_one=False)
    if unit == "min":
        return minutes(value)
    if unit in ("kg", "kg/m2", "ml/kg/min", "ms", "brpm"):
        return f"{number(value, places=1)} {unit}"
    if unit in ("ratio", "sd", "kg/week", "ml/kg/min/year"):
        return number(value, places=2)
    if unit in ("bpm", "count", "au", "level", "index", "score"):
        return number(value)
    return number(value, places=1)
