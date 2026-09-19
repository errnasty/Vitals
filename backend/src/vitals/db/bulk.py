"""Splitting a bulk insert so it fits inside Postgres's bind-parameter ceiling.

The wire protocol allows 32767 parameters in one statement, and a multi-row INSERT
spends one per column per row. So the limit is not on data size but on rows × columns,
which makes it easy to write a loader that works on a week of test data and fails on
the first real backfill — a day of Garmin stress samples alone is several hundred rows.

Every bulk writer in this codebase goes through here for that reason.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

# asyncpg raises `the number of query arguments cannot exceed 32767` above this.
MAX_BIND_PARAMS = 32767


def chunked(rows: Sequence[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    """Yield row groups small enough for one statement each."""
    if not rows:
        return
    columns = max(1, len(rows[0]))
    per_statement = max(1, MAX_BIND_PARAMS // columns)
    for start in range(0, len(rows), per_statement):
        yield list(rows[start : start + per_statement])
