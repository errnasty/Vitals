"""Gold: what the observations mean.

Five modules, each a pure function of a window of silver: training load, recovery,
sleep, body and longevity. They compute; they do not fetch, store or explain. The
engine loads once, walks the days, and upserts — so a recompute is idempotent and gold
is disposable in exactly the way silver is.

This is where the root README's rule is enforced rather than stated. Every number the
app ever shows or the model ever talks about is computed here, in Python, from data
with a recorded coverage. The LLM's job starts after this package has finished.
"""

from vitals.analytics.canonical import REGISTRY, DerivedDef
from vitals.analytics.engine import MODULES, RecomputeResult, recompute, silver_span
from vitals.analytics.model import Derived
from vitals.analytics.series import Inputs, Night, Series, load_inputs, trimp

__all__ = [
    "MODULES",
    "REGISTRY",
    "Derived",
    "DerivedDef",
    "Inputs",
    "Night",
    "RecomputeResult",
    "Series",
    "load_inputs",
    "recompute",
    "silver_span",
    "trimp",
]
