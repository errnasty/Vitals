"""SQLAlchemy models.

Every model imported here so Alembic's autogenerate sees the full metadata.
"""

from vitals.db.base import Base
from vitals.db.models.app_user import AppUser
from vitals.db.models.credential import GARMIN_PASSWORD, GARMIN_TOKENS, Credential
from vitals.db.models.raw_payload import RawPayload
from vitals.db.models.source_connection import SourceConnection
from vitals.db.models.sync_run import SyncRun

__all__ = [
    "GARMIN_PASSWORD",
    "GARMIN_TOKENS",
    "AppUser",
    "Base",
    "Credential",
    "RawPayload",
    "SourceConnection",
    "SyncRun",
]
