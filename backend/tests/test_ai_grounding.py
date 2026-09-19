"""The validator is the promise at the top of the README, enforced.

Most of these cases are conversions — the failure worth catching is not a model
inventing a number from nothing, it is a model doing a small, plausible, unverifiable
piece of arithmetic on a number it was given.
"""

from __future__ import annotations

import pytest

from vitals.ai import grounding

DIGEST = """DATE: 2026-09-19
SCORE: 78 out of 100 — Balanced
COVERAGE: 94%
VERSUS THE LAST 14 DAYS: mean 81, and today is 2 below it

WHAT MOVED THE SCORE:
- Sleep duration [sleep]: 7h 16m, scored 76, effect 6.6 pts
- Overnight HRV [recovery]: +0.05 SD from your own baseline, scored 82, effect 9.8 pts
- Daily movement [longevity]: 9,689, scored 100, effect 6.2 pts

WHAT PYTHON NOTICED:
- Sleep debt has reached 7h 51m against your nightly need.
"""


def check(text: str) -> grounding.Grounding:
    return grounding.check(text, DIGEST)


@pytest.mark.parametrize(
    "text",
    [
        "Balanced today at 78, 2 below your 14-day mean of 81.",
        "Sleep came in at 7h 16m and scored 76.",
        "Sleep debt has reached 7h 51m — an earlier night would help.",
        "Your HRV sat at +0.05 SD from your own baseline.",
        "You took 9,689 steps.",
        # The same number said without its thousands separator.
        "You took 9689 steps.",
        # No numbers at all is always grounded.
        "Sleep is the thing to look at this week.",
        "Overnight HRV carried 9.8 pts of the score.",
    ],
)
def test_grounded(text: str) -> None:
    assert check(text).grounded, check(text).summary


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The headline failure: a unit conversion the reader cannot verify.
        ("You slept 7.3 hours.", "7.3"),
        # Arithmetic on two numbers that were both given.
        ("You are 3 points below your mean.", "3"),
        # A number from nowhere.
        ("Your sleep debt is about 8 hours.", "8"),
        # Rounding a score.
        ("A score of 80 today.", "80"),
        # Spelled out, but quantifying — the obvious way round the digit check.
        ("You slept eight hours.", "8"),
    ],
)
def test_ungrounded(text: str, expected: str) -> None:
    result = check(text)
    assert not result.grounded
    assert expected in result.summary


def test_spelled_out_numbers_are_only_checked_when_they_quantify() -> None:
    """ "one of the four pillars" is prose, not a claim about the data."""
    assert check("Sleep is one of the four pillars, and it is the weak one.").grounded


def test_incidental_digits_in_the_digest_are_permitted() -> None:
    """The documented hole in the rule, asserted rather than left to be discovered.

    The permitted set is *every* number in the rendered digest, including digits that
    are part of a formatted value rather than a fact in their own right — `7h 16m`
    makes `7` sayable. The alternative is a curated whitelist of "the numbers that
    count", which is a second thing to keep in step with the digest and would be wrong
    the first time a contribution was added. See `grounding.py`.
    """
    assert check("You slept seven hours.").grounded


def test_verdict_must_match_the_screen() -> None:
    """Two surfaces disagreeing about the same day is what `verdict.py` exists to stop."""
    result = check("A Strong day at 78.")
    assert not result.grounded
    assert "Balanced" in result.summary


def test_the_digest_s_own_verdict_is_allowed() -> None:
    assert check("Balanced at 78.").grounded


def test_a_minus_sign_is_not_a_different_number() -> None:
    """`format.py` emits U+2212; a model writing prose reaches for a hyphen."""
    digest = "effect −4.2 pts"
    assert grounding.check("It cost 4.2 points.", digest).grounded
    assert grounding.check("It cost -4.2 points.", digest).grounded


def test_a_flipped_sign_is_not_grounded() -> None:
    """Direction is the whole meaning of a deviation; reversing it is not a rounding."""
    assert not grounding.check("HRV was −0.05 SD.", "HRV +0.05 SD").grounded


def test_trailing_zeros_are_the_same_number() -> None:
    assert grounding.check("scored 7", "scored 7.0").grounded


def test_numbers_extracts_normalised_values() -> None:
    assert grounding.numbers("1,250 and −4.20 and +3") == {"1250", "-4.2", "3"}


def test_permitted_allows_the_unsigned_reading_of_a_signed_fact() -> None:
    """The digest carries the sign; the brief usually carries the direction in words."""
    allowed = grounding.permitted("effect −4.2 pts")
    assert "4.2" in allowed
    assert "-4.2" in allowed


def test_violations_name_the_offending_numbers() -> None:
    """The retry can only comply if it is told what it got wrong."""
    result = check("You slept 7.3 hours and scored 80.")
    assert "7.3" in result.summary
    assert "80" in result.summary
