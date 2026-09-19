"""SQLAlchemy models.

Every model imported here so Alembic's autogenerate sees the full metadata.
"""

from vitals.db.base import Base
from vitals.db.models.activity import Activity
from vitals.db.models.app_user import AppUser
from vitals.db.models.credential import GARMIN_PASSWORD, GARMIN_TOKENS, Credential
from vitals.db.models.derived import DerivedDaily
from vitals.db.models.metric import MetricDaily, MetricSample
from vitals.db.models.raw_payload import RawPayload
from vitals.db.models.score import ScoreContribution, ScorePillar, VitalsScore
from vitals.db.models.sleep import SleepSession
from vitals.db.models.source_connection import SourceConnection
from vitals.db.models.sync_run import SyncRun

__all__ = [
    "GARMIN_PASSWORD",
    "GARMIN_TOKENS",
    "Activity",
    "AppUser",
    "Base",
    "Credential",
    "DerivedDaily",
    "MetricDaily",
    "MetricSample",
    "RawPayload",
    "ScoreContribution",
    "ScorePillar",
    "SleepSession",
    "SourceConnection",
    "SyncRun",
    "VitalsScore",
]
