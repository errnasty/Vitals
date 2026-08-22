from __future__ import annotations

import os

import pytest

# Keep the settings singleton away from any real .env values during tests.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://vitals:vitals@localhost:5432/vitals_test"
)
os.environ.setdefault("ENVIRONMENT", "local")


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from vitals.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
