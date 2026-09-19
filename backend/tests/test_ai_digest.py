"""The digest is what the model is allowed to know, so what it leaves out is a test."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from vitals.ai import digest as ai
from vitals.ai import grounding
from vitals.analytics import canonical as gold
from vitals.db.models import ScoreContribution, ScorePillar, VitalsScore

DAY = date(2026, 9, 19)
USER = uuid.uuid4()


def score_row(value: float = 78.0, coverage: float = 0.94, trusted: bool = True) -> VitalsScore:
    return VitalsScore(
        id=uuid.uuid4(),
        user_id=USER,
        calendar_date=DAY,
        score=value,
        coverage=coverage,
        trusted=trusted,
    )


def pillar(name: str, value: float, weight: float = 30.0, coverage: float = 1.0) -> ScorePillar:
    return ScorePillar(
        id=uuid.uuid4(),
        user_id=USER,
        calendar_date=DAY,
        pillar=name,
        score=value,
        coverage=coverage,
        weight=weight,
    )


def contribution(metric: str, value: float, points: float, effect: float) -> ScoreContribution:
    return ScoreContribution(
        id=uuid.uuid4(),
        user_id=USER,
        calendar_date=DAY,
        pillar="sleep",
        metric=metric,
        value=value,
        points=points,
        weight=40.0,
        coverage=1.0,
        effect=effect,
    )


def build(**kwargs) -> ai.Digest:
    defaults = {
        "row": score_row(),
        "pillars": [pillar("recovery", 71.0), pillar("sleep", 73.0)],
        "contributions": [contribution(gold.SLEEP_DURATION_7D, 26160.0, 76.0, 6.6)],
        "history": [81.0] * 14,
        "context": {},
    }
    defaults.update(kwargs)
    row = defaults.pop("row")
    return ai.build(
        row,
        defaults.pop("pillars"),
        defaults.pop("contributions"),
        history=defaults.pop("history"),
        context=defaults.pop("context"),
    )


def test_the_rendered_digest_carries_the_formatted_value_not_the_raw_one() -> None:
    """26160 seconds must reach the model as `7h 16m`, or it will convert it itself."""
    text = build().render()
    assert "7h 16m" in text
    assert "26160" not in text


def test_every_number_in_the_digest_is_permitted_to_itself() -> None:
    """The rendered text and the permitted set are the same string, by construction."""
    digest = build()
    text = digest.render()
    assert grounding.check(text, text).grounded


def test_the_verdict_word_comes_from_the_same_place_the_screen_reads() -> None:
    assert "Balanced" in build(row=score_row(78.0)).render()
    assert "Strained" in build(row=score_row(41.0)).render()


def test_weight_and_body_composition_never_reach_the_model() -> None:
    """`pillars.py` refuses to score them; the digest refuses to mention them.

    A prompt asking a model not to comment on someone's weight is a request. Leaving
    the number out of what it can see is a guarantee.
    """
    text = build().render().lower()
    for word in ("weight", "body fat", "kg"):
        assert word not in text


def test_a_deviation_carries_its_unit_and_its_sign() -> None:
    """A bare `0.05` on an HRV line is an invitation to write that the HRV was 0.05."""
    digest = build(contributions=[contribution(gold.HRV_DEVIATION, 0.05, 82.0, 9.8)])
    assert "+0.05 SD from your own baseline" in digest.render()


def test_effects_are_unsigned_because_no_line_subtracts() -> None:
    """They sum to the score; a `+` would imply some could be negative."""
    assert "effect 6.6 pts" in build().render()


def test_the_fingerprint_is_stable_across_identical_days() -> None:
    assert build().fingerprint == build().fingerprint


def test_the_fingerprint_moves_when_a_number_does() -> None:
    """This is what decides whether a re-run is free or billable."""
    assert build().fingerprint != build(row=score_row(79.0)).fingerprint


@pytest.mark.parametrize("scores", [[], [81.0]])
def test_a_comparison_needs_history_and_survives_having_almost_none(scores: list[float]) -> None:
    digest = build(history=scores)
    assert (digest.comparison is None) is (not scores)


def test_the_comparison_says_which_way_in_words() -> None:
    """A signed number leaves the model to decide whether −2 is a fall or a wobble."""
    assert "2 below it" in build(row=score_row(79.0), history=[81.0] * 14).render()
    assert "level with it" in build(row=score_row(81.0), history=[81.0] * 14).render()


def test_the_contribution_list_is_truncated() -> None:
    """A two-sentence note does not need the tail of a waterfall, and it costs tokens."""
    many = [
        contribution(gold.SLEEP_DURATION_7D, 26160.0, 76.0, float(n))
        for n in range(ai.MAX_CONTRIBUTIONS + 5)
    ]
    assert len(build(contributions=many).contributions) == ai.MAX_CONTRIBUTIONS


def test_no_timeseries_reaches_the_model() -> None:
    """The architecture's gold-to-AI boundary: a compact digest, never raw history."""
    text = build(history=[float(70 + n) for n in range(14)]).render()
    # The fortnight is summarised to one mean, so no individual day appears.
    assert "70" not in text and "72" not in text
