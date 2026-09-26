"""The vocabulary of things worth noting about a day.

Deliberately a **closed list**, for the same reason silver has a canonical metric
vocabulary: free text cannot be correlated against anything. "Had a few beers",
"drinks with J", and "🍺🍺" are one fact to a human and three to a statistic, and an
app that collects the first and promises the second is lying about what it can do.

Two rules shaped what is on the list.

**It must be something you can answer without thinking.** This gets filled in at
11pm or not at all, so every tag is a yes/no a person already knows the answer to.
Nothing here asks you to rate, estimate or remember a number — except alcohol, where
one drink and six are different enough to be different facts.

**It must plausibly move something the watch measures.** Alcohol, illness, travel and
stress all have well-documented effects on heart-rate variability, resting heart rate
and sleep architecture. A tag that cannot move a metric would produce nothing but
false positives once phase 8 starts testing them in bulk, and every tag on the list
costs a multiple-comparisons correction against every other.

**Context is never scored.** Tagging a day as drinking does not lower your Vitals
Score. The score reads the body; this reads the day, and its whole job is to explain
what the score already found. An app that docked you points for telling it the truth
would stop being told the truth.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tag:
    name: str
    label: str
    # What it is for, shown once so nobody has to guess what counts.
    hint: str
    # Alcohol is the one thing here where the amount is the fact. Everything else is
    # a yes/no, because a five-point stress scale collected at bedtime is noise.
    magnitude: str | None = None
    # Which icon the UI reaches for. A name from the design system's set.
    icon: str = "sparkle"


TAGS: tuple[Tag, ...] = (
    Tag(
        name="alcohol",
        label="Alcohol",
        hint="Roughly how many drinks — one and six are different facts.",
        magnitude="drinks",
        icon="drop",
    ),
    Tag(
        name="late_meal",
        label="Late meal",
        hint="Ate within about three hours of going to bed.",
        icon="flame",
    ),
    Tag(
        name="late_caffeine",
        label="Late caffeine",
        hint="Coffee, tea or an energy drink after mid-afternoon.",
        icon="bolt",
    ),
    Tag(
        name="stress",
        label="Stressful day",
        hint="Work, family, money — whatever made it one.",
        icon="pulse",
    ),
    Tag(
        name="poor_environment",
        label="Bad sleep setup",
        hint="Too hot, too bright, too loud, or not your own bed.",
        icon="moon",
    ),
    Tag(
        name="travel",
        label="Travel",
        hint="A flight, a long drive, or a change of time zone.",
        icon="map",
    ),
    Tag(
        name="illness",
        label="Unwell",
        hint="Anything from a cold to a fever.",
        icon="lungs",
    ),
    Tag(
        name="injury",
        label="Injury or pain",
        hint="Something that changed how you moved or slept.",
        icon="heart",
    ),
    Tag(
        name="menstruation",
        label="Period",
        hint="One of the strongest cyclical effects on the numbers above.",
        icon="calendar",
    ),
)

BY_NAME: dict[str, Tag] = {tag.name: tag for tag in TAGS}


class UnknownTag(KeyError):
    """Something outside the vocabulary. Rejected rather than stored."""


def tag_for(name: str) -> Tag:
    try:
        return BY_NAME[name]
    except KeyError as exc:
        raise UnknownTag(name) from exc
