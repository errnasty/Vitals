"""What actually moves your numbers — and, far more often, what does not.

This is the part Garmin structurally cannot build: it does not know you drank last
night, and it will not run statistics on a single person. N-of-1 analysis is the whole
reason to keep your own data rather than rent a view of it.

It is also the easiest thing in this app to get wrong in a way that looks convincing.
`analysis.py` says what each guard costs and why it is there.
"""

from vitals.insights.analysis import Finding, analyse
from vitals.insights.engine import refresh

__all__ = ["Finding", "analyse", "refresh"]
