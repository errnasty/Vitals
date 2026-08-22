"""Liveness and health endpoints.

`/livez` answers "is the process up" and is what Railway's healthcheck should poll —
it must never depend on the database, or a Supabase blip cycles the deploy.
`/healthz` answers "is the whole path wired up", including the database, and is what
phase 0 verification curls from outside.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from vitals import __version__
from vitals.api.deps import SessionDep, SettingsDep

router = APIRouter(tags=["health"])


@router.get("/livez")
async def livez() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


@router.get("/healthz")
async def healthz(session: SessionDep, settings: SettingsDep, response: Response) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    started = time.perf_counter()

    try:
        await session.execute(text("select 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001 - health endpoint reports, never raises
        checks["database"] = {"ok": False, "error": type(exc).__name__}

    if checks["database"]["ok"]:
        try:
            row = await session.execute(
                text("select extversion from pg_extension where extname = 'vector'")
            )
            version = row.scalar_one_or_none()
            checks["pgvector"] = {"ok": version is not None, "version": version}
        except Exception as exc:  # noqa: BLE001
            checks["pgvector"] = {"ok": False, "error": type(exc).__name__}

    ok = checks["database"]["ok"]
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if ok else "unhealthy",
        "version": __version__,
        "environment": settings.environment,
        "service": settings.railway_service,
        "git_sha": settings.git_sha,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "checks": checks,
    }
