"""What an analytics module returns.

Each module is a pure function of `(Inputs, day)`, so the sports science is testable
without a database: hand it a fortnight of numbers and check the answer by hand.

`inputs` is the count of observations behind the value. The engine turns it into
`coverage` using the window the metric declares, which is how a fitness figure built
from six days is distinguishable from one built from six weeks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from vitals.analytics.series import Inputs


@dataclass(frozen=True, slots=True)
class Derived:
    metric: str
    calendar_date: date
    value: float
    inputs: int


Module = Callable[[Inputs, date], list[Derived]]
