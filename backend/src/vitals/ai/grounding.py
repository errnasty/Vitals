"""Checking that the model only said numbers Python gave it.

The rule at the top of the README — *the LLM never does arithmetic* — is a promise,
and a promise nothing enforces is a hope. This module is the enforcement. It is
deliberately mechanical: no model judges another model's output here, because a
checker that can be talked out of its answer is not a checker.

The rule it applies is one sentence: **every number in the brief must appear in the
digest the brief was written from.** Not "must be close to", not "must be derivable
from" — derivable is exactly the failure being prevented. If the digest says
`7h 20m` and the brief says `7.3 hours`, that conversion is arithmetic the model did,
it is unverifiable by the person reading it, and it is rejected.

The permitted set is extracted from the rendered digest with the same extractor that
reads the brief, so the two cannot disagree about what a number is. The consequence
worth stating plainly: incidental digits in the digest's prose are permitted too —
`VO2max` makes `2` sayable. That is a real, small hole, and it is the price of a rule
simple enough to be obviously correct. The alternative, a curated whitelist of "the
numbers that count", is a second thing to keep in sync with the digest, and it would
be wrong the first time a contribution was added.

What this does **not** check: that a number is attached to the right unit or the right
claim. "Your resting heart rate is 48 kg" is grounded and wrong. Unit and claim
correctness is phase 8's problem, and the mitigation until then is that the model is
handed finished sentences to quote rather than fields to assemble.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Matches a run of digits with optional thousands separators and decimals. Both minus
# signs are included because `format.py` emits a real `−` (U+2212) and a model writing
# prose will reach for an ASCII hyphen; treating them as different numbers would fail
# briefs that are perfectly grounded.
NUMBER = re.compile(r"[-−+]?\d+(?:[, ]\d{3})*(?:\.\d+)?")

# Spelled-out quantities are only a number when they quantify something. "one of the
# four pillars" is prose; "seven hours" is a claim about the data. Checking the first
# would reject every readable sentence, and ignoring the second would leave the whole
# rule trivially avoidable by writing the digits out.
WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
}  # fmt: skip

UNITS = (
    "hour", "hours", "minute", "minutes", "second", "seconds", "point", "points",
    "percent", "bpm", "kg", "ms", "day", "days", "week", "weeks", "night", "nights",
    "step", "steps", "beat", "beats",
)  # fmt: skip

_WORD_NUMBER = re.compile(
    rf"\b({'|'.join(WORD_NUMBERS)})\b[\s-]+(?:{'|'.join(UNITS)})\b", re.IGNORECASE
)

VERDICTS = ("Strong", "Balanced", "Mixed", "Strained")


@dataclass(frozen=True, slots=True)
class Violation:
    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class Grounding:
    """The result of checking one brief against one digest."""

    grounded: bool
    violations: tuple[Violation, ...]

    @property
    def summary(self) -> str:
        """What the retry tells the model it got wrong. Specific, so it can comply."""
        return "; ".join(f"{v.kind}: {v.detail}" for v in self.violations)


def _normalise(token: str) -> str:
    """One canonical spelling per numeric value, so `1,250` and `1250` are one number.

    Trailing zeros go too: a digest holding `7.0` permits `7`, because the model
    dropping a meaningless decimal is not arithmetic — it is the same number.
    """
    cleaned = token.replace(",", "").replace(" ", "").replace("−", "-").lstrip("+")
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    if cleaned in ("", "-"):
        return "0"
    # -0 and 0 are the same number, and only one of them is ever written on purpose.
    return "0" if cleaned == "-0" else cleaned


def numbers(text: str) -> set[str]:
    """Every number the text states, normalised."""
    found = {_normalise(match.group()) for match in NUMBER.finditer(text)}
    for match in _WORD_NUMBER.finditer(text):
        found.add(str(WORD_NUMBERS[match.group(1).lower()]))
    return found


def permitted(digest_text: str) -> set[str]:
    """The numbers a brief written from this digest is allowed to state."""
    allowed = numbers(digest_text)
    # A digest holding a signed value permits the unsigned reading of it and vice
    # versa: "4 points below" and "−4" are the same fact said two ways, and the brief
    # carries the direction in words.
    allowed |= {value.lstrip("-") for value in allowed}
    return allowed


def check(text: str, digest_text: str) -> Grounding:
    """Validate one brief against the digest it was written from."""
    violations: list[Violation] = []

    allowed = permitted(digest_text)
    ungrounded = sorted(numbers(text) - allowed, key=_sort_key)
    if ungrounded:
        violations.append(
            Violation(
                kind="ungrounded number",
                detail=(
                    f"{', '.join(ungrounded)} — not in the digest. Every number must be "
                    "copied from it exactly, never converted or combined."
                ),
            )
        )

    claimed = {word for word in VERDICTS if re.search(rf"\b{word}\b", text)}
    expected = _expected_verdict(digest_text)
    wrong = claimed - {expected} if expected else claimed
    if wrong:
        violations.append(
            Violation(
                kind="wrong verdict",
                detail=(
                    f"called the day {', '.join(sorted(wrong))}"
                    + (f"; the digest says {expected}" if expected else "")
                ),
            )
        )

    return Grounding(grounded=not violations, violations=tuple(violations))


def _expected_verdict(digest_text: str) -> str | None:
    """The one verdict word the digest carries, if it carries one.

    Read back out of the rendered text rather than passed in, so the checker cannot be
    handed a different verdict from the one the model was shown — which is the whole
    failure mode `score/verdict.py` exists to prevent.
    """
    match = re.search(rf"\b({'|'.join(VERDICTS)})\b", digest_text)
    return match.group(1) if match else None


def _sort_key(value: str) -> tuple[float, str]:
    try:
        return (float(value), value)
    except ValueError:  # pragma: no cover - the extractor only yields parseable numbers
        return (0.0, value)


__all__ = ["Grounding", "Violation", "check", "numbers", "permitted"]
