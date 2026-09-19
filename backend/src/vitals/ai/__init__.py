"""Phase 7: the layer that turns finished arithmetic into a sentence.

Everything below this package computes numbers; nothing in it does. The digest is
built by Python, the ranking is decided by Python, the formatting is done by Python,
and what the model contributes is the wording. `grounding.py` is what keeps that
division honest rather than aspirational.
"""

from vitals.ai.brief import BriefResult, compose, generate, latest
from vitals.ai.digest import Digest, load
from vitals.ai.grounding import Grounding, check
from vitals.ai.signals import Signal, detect

__all__ = [
    "BriefResult",
    "Digest",
    "Grounding",
    "Signal",
    "check",
    "compose",
    "detect",
    "generate",
    "latest",
    "load",
]
