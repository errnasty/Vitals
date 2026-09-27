"""The local mirror of an authenticated identity.

Deliberately *not* a foreign key into Supabase's `auth.users`. Two reasons, both
about not painting the schema into a corner:

* every later table hangs off `app_user.id`, and phase 12 (multi-user) or a move off
  Supabase Auth should not mean rewriting those constraints;
* `id` is the Supabase `sub` claim, so the mirror is exact today and swappable later.

The row is created on first authenticated request rather than by a webhook, which
means there is no provisioning path that can silently fail behind your back.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Uuid, false, func, true
from sqlalchemy.orm import Mapped, mapped_column

from vitals.db.base import Base


class AppUser(Base):
    __tablename__ = "app_user"

    # The Supabase `sub` claim, verbatim.
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Load-bearing from silver on: Garmin timestamps are stored in UTC and the
    # calendar date is derived, never taken from the provider's *Local fields.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    # A local kill switch that does not depend on reaching Supabase.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    # Whether a day's free-text note may be given to the model when answering a
    # question. **Off by default, and it must stay that way.**
    #
    # Phase 3's Log screen promised, in as many words, that the note is "never
    # analysed and never shown to a model". Phase 9 wants to use it. A promise made
    # on the screen where someone typed the text is not one a later phase gets to
    # quietly withdraw, so this is opt-in, the default preserves exactly what was
    # promised, and the screen's wording changes with the setting rather than
    # staying reassuring while the behaviour moves underneath it.
    share_notes_with_ai: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
