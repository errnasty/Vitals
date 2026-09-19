"""What Python decides is worth saying — which is what makes the brief quiet."""

from __future__ import annotations

import uuid
from datetime import date

from vitals.ai import signals
from vitals.analytics import canonical as gold
from vitals.db.models import ScoreContribution, ScorePillar

DAY = date(2026, 9, 19)
USER = uuid.uuid4()


def pillar(name: str, value: float, coverage: float = 1.0) -> ScorePillar:
    return ScorePillar(
        id=uuid.uuid4(),
        user_id=USER,
        calendar_date=DAY,
        pillar=name,
        score=value,
        coverage=coverage,
        weight=30.0,
    )


def contribution(metric: str, points: float, effect: float = 5.0) -> ScoreContribution:
    return ScoreContribution(
        id=uuid.uuid4(),
        user_id=USER,
        calendar_date=DAY,
        pillar="sleep",
        metric=metric,
        value=1.0,
        points=points,
        weight=40.0,
        coverage=1.0,
        effect=effect,
    )


def detect(**kwargs) -> tuple[signals.Signal, ...]:
    defaults = {
        "score": 78.0,
        "coverage": 0.94,
        "trusted": True,
        "pillars": [pillar("recovery", 71.0), pillar("sleep", 73.0)],
        "contributions": [contribution(gold.SLEEP_DURATION_7D, 76.0)],
        "history": [78.0] * 14,
        "context": {},
    }
    defaults.update(kwargs)
    return signals.detect(**defaults)


def kinds(found: tuple[signals.Signal, ...]) -> set[str]:
    return {signal.kind for signal in found}


def test_an_ordinary_day_raises_nothing() -> None:
    """The whole point. A model asked to write about this day would find something."""
    assert detect() == ()


def test_a_good_day_may_note_one_thing_going_well() -> None:
    """Only when nothing is wrong — on a bad day this reads as consolation."""
    found = detect(contributions=[contribution(gold.SLEEP_DURATION_7D, 92.0)])
    assert kinds(found) == {"lift"}


def test_a_lift_is_suppressed_when_something_is_wrong() -> None:
    found = detect(
        contributions=[contribution(gold.SLEEP_DURATION_7D, 92.0)],
        context={gold.SLEEP_DEBT: 5 * 3600.0},
    )
    assert "lift" not in kinds(found)


def test_thin_data_is_said_first_because_it_qualifies_everything_else() -> None:
    found = detect(trusted=False, coverage=0.31, score=55.0, history=[78.0] * 14)
    assert found[0].kind == "thin_data"
    assert "31%" in found[0].sentence


def test_a_score_move_is_measured_against_the_fortnight() -> None:
    found = detect(score=60.0, history=[78.0] * 14)
    assert "score_moved" in kinds(found)


def test_a_point_of_movement_is_not_news() -> None:
    assert "score_moved" not in kinds(detect(score=79.0, history=[78.0] * 14))


def test_load_balance_fires_outside_the_settled_range() -> None:
    assert "load_balance" in kinds(detect(context={gold.ACWR: 1.6}))
    assert "load_balance" in kinds(detect(context={gold.ACWR: 0.5}))
    assert "load_balance" not in kinds(detect(context={gold.ACWR: 1.1}))


def test_a_spike_outranks_a_lull() -> None:
    """Both are worth saying; only one of them is an injury risk."""
    spike = next(s for s in detect(context={gold.ACWR: 1.6}) if s.kind == "load_balance")
    lull = next(s for s in detect(context={gold.ACWR: 0.5}) if s.kind == "load_balance")
    assert spike.severity > lull.severity


def test_sleep_debt_fires_past_the_threshold() -> None:
    assert "sleep_debt" in kinds(detect(context={gold.SLEEP_DEBT: 4 * 3600.0}))
    assert "sleep_debt" not in kinds(detect(context={gold.SLEEP_DEBT: 1 * 3600.0}))


def test_a_weak_pillar_is_named() -> None:
    found = detect(pillars=[pillar("recovery", 38.0), pillar("sleep", 73.0)])
    assert "low_pillar" in kinds(found)
    assert "Recovery" in next(s for s in found if s.kind == "low_pillar").sentence


def test_at_most_three_survive_and_the_worst_come_first() -> None:
    found = detect(
        trusted=False,
        coverage=0.2,
        score=50.0,
        history=[78.0] * 14,
        pillars=[pillar("recovery", 20.0)],
        contributions=[contribution(gold.SLEEP_DURATION_7D, 12.0)],
        context={gold.ACWR: 1.9, gold.SLEEP_DEBT: 6 * 3600.0, gold.MONOTONY: 2.6},
    )
    assert len(found) == signals.MAX_SIGNALS
    assert [s.severity for s in found] == sorted((s.severity for s in found), reverse=True)


def test_every_sentence_arrives_finished() -> None:
    """The model quotes these; Python never hands it a template to fill in."""
    for signal in detect(context={gold.SLEEP_DEBT: 5 * 3600.0}):
        assert signal.sentence.endswith(".")
        assert "{" not in signal.sentence
