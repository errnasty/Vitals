"""SQLAlchemy models.

Every model imported here so Alembic's autogenerate sees the full metadata.
"""

from vitals.db.base import Base
from vitals.db.models.sync_run import SyncRun

__all__ = ["Base", "SyncRun"]
