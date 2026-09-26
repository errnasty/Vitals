"""What the analysis found — and what it is honest about not finding.

Every sentence on this screen is written here, in Python, for the same reason every
other number is: the difference between "23% lower" and "12% lower" is the whole
finding, and a UI computing percentages is a UI that can disagree with the statistics
that produced them.

The screen this feeds is designed around the empty case, because the empty case is
the normal one. Most people, most of the time, have no detectable effects — either
because there genuinely are none, or because eleven tagged days cannot show one. An
insights screen that always has something to say is one that is making things up.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from vitals.analytics import canonical as gold
from vitals.api import format as fmt
from vitals.api.deps import CurrentUserDep, SessionDep
from vitals.context import canonical as tags
from vitals.db.models import DayContext, Insight
from vitals.insights import engine
from vitals.normalize import canonical as silver

router = APIRouter(prefix="/insights", tags=["insights"])

# How a metric reads in a sentence. Not the same as its dashboard label — "your
# overnight HRV" belongs in prose where "Overnight HRV" belongs in a column.
PHRASE: dict[str, str] = {
    silver.HRV_OVERNIGHT_AVG: "your overnight HRV",
    silver.RESTING_HR: "your resting heart rate",
    silver.SLEEP_DURATION: "how long you sleep",
    silver.SLEEP_SCORE: "your Garmin sleep score",
    silver.SLEEP_DEEP: "your deep sleep",
    silver.SLEEP_REM: "your REM sleep",
    silver.STRESS_AVG: "your average stress",
    silver.BODY_BATTERY_HIGH: "your peak Body Battery",
    silver.STEPS: "your step count",
    gold.HRV_DEVIATION: "your HRV against its baseline",
    gold.RHR_DEVIATION: "your resting heart rate against its baseline",
    gold.SLEEP_EFFICIENCY: "your sleep efficiency",
}


class FindingView(BaseModel):
    tag: str
    tag_label: str
    metric: str
    # The whole finding as one sentence, numbers included, written in Python.
    sentence: str
    # "the same day" | "the next day"
    when: str
    # `23% lower`, for a screen that wants the headline apart from the prose.
    change: str
    direction: str
    # "n days with, n without" — the evidence, in the open.
    sample: str
    confidence: str


class InsightsResponse(BaseModel):
    findings: list[FindingView]
    tested: int
    tagged_days: int
    window_start: date | None = None
    window_end: date | None = None
    # Why there is nothing to show, when there is nothing to show. The empty state
    # is the normal one and it deserves a real explanation rather than a blank page.
    empty_reason: str | None = None


def _unit_for(metric: str) -> str:
    try:
        return gold.unit_for(metric)
    except KeyError:
        return silver.unit_for(metric)


def _change(row: Insight) -> str:
    """The size of the difference, as a percentage of the untagged baseline.

    A percentage rather than the raw difference because "8ms lower" means nothing
    without knowing your HRV runs at 45 or 120, and this sentence has to work for
    someone who does not know their own baselines by heart.
    """
    if row.mean_without == 0:
        return fmt.metric(abs(row.delta), _unit_for(row.metric))
    return fmt.percent(abs(row.delta / row.mean_without))


def _confidence(row: Insight) -> str:
    """How strong the evidence is, in words rather than a p-value.

    A p-value on a health screen is either ignored or misread, usually as "the
    chance this is wrong". These are deliberately modest: the strongest thing this
    engine can say about a single person's data is "consistent", never "proven".
    """
    if not row.significant:
        return "not strong enough to rely on"
    if row.p_value <= 0.001:
        return "very consistent"
    if row.p_value <= 0.01:
        return "consistent"
    return "fairly consistent"


def _sentence(row: Insight) -> str:
    phrase = PHRASE.get(row.metric, row.metric)
    label = tags.BY_NAME[row.tag].label.lower() if row.tag in tags.BY_NAME else row.tag
    when = "the next day" if row.lag else "on the same day"
    return (
        f"On days after {label}, {phrase} is {_change(row)} {row.direction} {when}."
        if row.lag
        else f"On days with {label}, {phrase} is {_change(row)} {row.direction}."
    )


def _view(row: Insight) -> FindingView:
    return FindingView(
        tag=row.tag,
        tag_label=tags.BY_NAME[row.tag].label if row.tag in tags.BY_NAME else row.tag,
        metric=row.metric,
        sentence=_sentence(row),
        when="the next day" if row.lag else "the same day",
        change=f"{_change(row)} {row.direction}",
        direction=row.direction,
        sample=f"{row.n_with} days with, {row.n_without} without",
        confidence=_confidence(row),
    )


@router.get("", response_model=InsightsResponse)
async def read(user: CurrentUserDep, session: SessionDep) -> InsightsResponse:
    """Everything that survived the correction, strongest first."""
    rows = list(
        (
            await session.execute(
                select(Insight)
                .where(Insight.user_id == user.id, Insight.significant.is_(True))
                .order_by(Insight.p_value)
            )
        )
        .scalars()
        .all()
    )

    any_row = (
        rows[0]
        if rows
        else await session.scalar(select(Insight).where(Insight.user_id == user.id).limit(1))
    )

    tagged_days = len(
        set(
            (
                await session.execute(
                    select(DayContext.calendar_date).where(DayContext.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
    )

    empty_reason = None
    if not rows:
        if tagged_days < engine.MIN_TAGGED_DAYS:
            empty_reason = (
                f"You have tagged {tagged_days} day"
                f"{'' if tagged_days == 1 else 's'}. This needs about "
                f"{engine.MIN_TAGGED_DAYS} before it can test anything, and a few weeks "
                "before it can say much."
            )
        else:
            empty_reason = (
                "Nothing stood out. That is the usual answer, and a more useful one "
                "than a list of coincidences — this only reports an effect that holds "
                "up once every test it ran is accounted for."
            )

    return InsightsResponse(
        findings=[_view(row) for row in rows],
        tested=any_row.tested if any_row is not None else 0,
        tagged_days=tagged_days,
        window_start=any_row.window_start if any_row is not None else None,
        window_end=any_row.window_end if any_row is not None else None,
        empty_reason=empty_reason,
    )
