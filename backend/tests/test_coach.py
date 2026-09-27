"""Ranking what to do, and refusing to rank what cannot be done.

The vetoes are the tests worth having. Any app can sort by worst number; the value
here is in what never reaches the list — a line you cannot act on, a gap too small to
matter, and advice that this person's own data says does not work for them.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import EMAIL, USER_ID
from vitals.analytics import canonical as gold
from vitals.coach import interventions
from vitals.db.models import AppUser, Insight, ScoreContribution, VitalsScore

DAY = date(2026, 9, 1)


@pytest.fixture
async def user(pg_session: AsyncSession) -> AppUser:
    row = AppUser(id=USER_ID, email=EMAIL)
    pg_session.add(row)
    await pg_session.commit()
    return row


async def _score(session: AsyncSession, lines: list[tuple[str, str, float, float]]) -> None:
    """`lines` is (pillar, metric, points, headroom)."""
    session.add(
        VitalsScore(
            user_id=USER_ID,
            calendar_date=DAY,
            score=70.0,
            coverage=0.9,
            trusted=True,
        )
    )
    for pillar, metric, points, headroom in lines:
        session.add(
            ScoreContribution(
                user_id=USER_ID,
                calendar_date=DAY,
                pillar=pillar,
                metric=metric,
                value=1.0,
                points=points,
                weight=30.0,
                coverage=1.0,
                effect=points / 10,
                headroom=headroom,
            )
        )
    await session.commit()


async def _finding(session: AsyncSession, tag: str, metric: str, p_value: float = 0.001) -> None:
    session.add(
        Insight(
            id=uuid.uuid4(),
            user_id=USER_ID,
            tag=tag,
            metric=metric,
            lag=1,
            n_with=12,
            n_without=40,
            mean_with=42.0,
            mean_without=56.0,
            delta=-14.0,
            effect=-0.9,
            p_value=p_value,
            significant=p_value <= 0.01,
            tested=180,
            window_start=DAY - timedelta(days=400),
            window_end=DAY,
        )
    )
    await session.commit()


async def test_nothing_to_say_before_there_is_a_score(
    pg_session: AsyncSession, user: AppUser
) -> None:
    assert await interventions.rank(pg_session, user_id=USER_ID) == []


async def test_ranked_by_points_available_not_by_worst_number(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """The whole difference between this and every other coaching screen.

    Sleep regularity scores far worse, and load balance has more of the final score
    riding on it. Ranking by how bad the number looks puts the same line on top every
    day; ranking by what is actually recoverable does not.
    """
    await _score(
        pg_session,
        [
            ("sleep", gold.SLEEP_CONSISTENCY, 20.0, 3.0),
            ("training", gold.ACWR, 75.0, 9.0),
        ],
    )

    ranked = await interventions.rank(pg_session, user_id=USER_ID)

    assert [item.metric for item in ranked] == [gold.ACWR, gold.SLEEP_CONSISTENCY]


async def test_a_line_you_cannot_act_on_never_appears(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """ "Get your overnight HRV to +0.5 SD" is not advice; it is a target someone will
    chase by sleeping badly and worrying about it."""
    await _score(
        pg_session,
        [
            ("recovery", gold.HRV_DEVIATION, 10.0, 40.0),
            ("sleep", gold.SLEEP_CONSISTENCY, 60.0, 5.0),
        ],
    )

    ranked = await interventions.rank(pg_session, user_id=USER_ID)

    assert [item.metric for item in ranked] == [gold.SLEEP_CONSISTENCY]


async def test_a_gap_too_small_to_matter_is_not_mentioned(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """Two points of a hundred is inside the noise of the inputs the score is built
    from, and an app that suggests changing your life over it gets ignored."""
    await _score(pg_session, [("sleep", gold.SLEEP_CONSISTENCY, 98.0, 0.5)])

    assert await interventions.rank(pg_session, user_id=USER_ID) == []


async def test_a_proven_personal_effect_promotes_its_pillar(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """Evidence from this person's own days is what makes the ranking theirs."""
    await _score(
        pg_session,
        [
            ("sleep", gold.SLEEP_CONSISTENCY, 60.0, 6.0),
            ("training", gold.ACWR, 60.0, 7.0),
        ],
    )
    await _finding(pg_session, "alcohol", gold.HRV_DEVIATION)

    ranked = await interventions.rank(pg_session, user_id=USER_ID)

    # 6 x 1.5 = 9 beats 7, so sleep overtakes training on the strength of the finding.
    assert ranked[0].metric == gold.SLEEP_CONSISTENCY
    assert ranked[0].evidence is not None
    assert "alcohol" in ranked[0].evidence


async def test_the_evidence_is_the_finding_s_own_sentence(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """Two phrasings of one statistic is how an app comes to appear to disagree with
    itself."""
    from vitals.insights import prose

    await _score(pg_session, [("sleep", gold.SLEEP_CONSISTENCY, 60.0, 6.0)])
    await _finding(pg_session, "alcohol", gold.HRV_DEVIATION)

    ranked = await interventions.rank(pg_session, user_id=USER_ID)
    stored = await pg_session.scalar(
        __import__("sqlalchemy").select(Insight).where(Insight.user_id == USER_ID)
    )

    assert ranked[0].evidence == prose.sentence(stored)


async def test_a_finding_that_did_not_survive_the_correction_never_promotes_anything(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """It is not weaker evidence — it is the engine saying it could not tell, and
    letting it tip a ranking smuggles back the false positives the correction removed.
    """
    await _score(
        pg_session,
        [
            ("sleep", gold.SLEEP_CONSISTENCY, 60.0, 6.0),
            ("training", gold.ACWR, 60.0, 7.0),
        ],
    )
    await _finding(pg_session, "alcohol", gold.HRV_DEVIATION, p_value=0.20)

    ranked = await interventions.rank(pg_session, user_id=USER_ID)

    assert ranked[0].metric == gold.ACWR
    assert all(item.evidence is None for item in ranked)


async def test_at_most_three_things_are_ever_put_in_front_of_someone(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """A ranked list of eleven things to fix is a list nobody starts."""
    await _score(
        pg_session,
        [
            ("sleep", gold.SLEEP_CONSISTENCY, 40.0, 9.0),
            ("sleep", gold.SLEEP_DURATION_7D, 40.0, 8.0),
            ("sleep", gold.SLEEP_DEBT, 40.0, 7.0),
            ("training", gold.ACWR, 40.0, 6.0),
            ("training", gold.MONOTONY, 40.0, 5.0),
        ],
    )

    ranked = await interventions.rank(pg_session, user_id=USER_ID)

    assert len(ranked) == interventions.MAX_INTERVENTIONS


async def test_the_words_come_from_the_pillar_definitions(
    pg_session: AsyncSession, user: AppUser
) -> None:
    """A score row carries numbers; duplicating the labels into it would give them two
    homes and one would go stale."""
    await _score(pg_session, [("sleep", gold.SLEEP_CONSISTENCY, 40.0, 9.0)])

    (item,) = await interventions.rank(pg_session, user_id=USER_ID)

    assert item.label == "Sleep regularity"
    assert item.pillar_label == "Sleep"
    assert "same bedtime" in item.lever
