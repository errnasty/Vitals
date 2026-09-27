"""Turning a stored finding into a sentence.

Here rather than in the API router because the coach needs the same sentence. A
finding that appears as "On days after alcohol, your overnight HRV is 25% lower the
next day" on the Patterns screen has to read identically when it is the reason an
intervention was ranked first — two phrasings of one statistic is how an app comes to
appear to disagree with itself.

Python owns it for the usual reason: the difference between "23% lower" and "12%
lower" is the whole finding.
"""

from __future__ import annotations

from vitals.analytics import canonical as gold
from vitals.api import format as fmt
from vitals.context import canonical as tags
from vitals.db.models import Insight
from vitals.normalize import canonical as silver

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


def unit_for(metric: str) -> str:
    try:
        return gold.unit_for(metric)
    except KeyError:
        return silver.unit_for(metric)


def change(row: Insight) -> str:
    """The size of the difference, as a percentage of the untagged baseline.

    A percentage rather than the raw difference because "8ms lower" means nothing
    without knowing your HRV runs at 45 or 120, and this sentence has to work for
    someone who does not know their own baselines by heart.
    """
    if row.mean_without == 0:
        return fmt.metric(abs(row.delta), unit_for(row.metric))
    return fmt.percent(abs(row.delta / row.mean_without))


def confidence(row: Insight) -> str:
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


def tag_label(name: str) -> str:
    return tags.BY_NAME[name].label if name in tags.BY_NAME else name


def sentence(row: Insight) -> str:
    phrase = PHRASE.get(row.metric, row.metric)
    label = tags.BY_NAME[row.tag].reads_as() if row.tag in tags.BY_NAME else row.tag
    if row.lag:
        return f"On days after {label}, {phrase} is {change(row)} {row.direction} the next day."
    return f"On days with {label}, {phrase} is {change(row)} {row.direction}."
