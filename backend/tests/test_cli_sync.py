"""How `vitals sync` behaves when the deployment is not set up yet.

This is the cron's entry point, and it ran every six hours against a database with no
account in it — crashing each time with a rich-formatted traceback and marking the
Railway deployment CRASHED. Nothing was actually wrong: nobody had signed in yet.

An alarm that fires on a to-do is worse than useless, because it is the same alarm a
real failure would raise.
"""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from vitals.cli import app
from vitals.ingest.pipeline import NoSuchUser
from vitals.sources.base import FAILED, SUCCESS, SyncOutcome

runner = CliRunner()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    """Swap out the job itself; what is under test is the CLI's handling of it."""

    def _set(result: Any) -> None:
        async def fake_run_sync(*args: Any, **kwargs: Any) -> SyncOutcome:
            if isinstance(result, Exception):
                raise result
            return result

        async def fake_shutdown() -> None:
            return None

        monkeypatch.setattr("vitals.workers.jobs.run_sync", fake_run_sync)
        monkeypatch.setattr("vitals.workers.jobs.shutdown", fake_shutdown)

    return _set


def test_an_unconfigured_deployment_exits_clean(no_network) -> None:
    """Pending setup is not a crash, and the cron must not report it as one."""
    no_network(NoSuchUser("no accounts exist yet; sign in once before syncing"))

    result = runner.invoke(app, ["sync"])

    assert result.exit_code == 0
    assert "nothing to sync" in result.stdout
    assert "garmin login" in result.stdout


def test_a_successful_sync_still_exits_zero(no_network) -> None:
    no_network(SyncOutcome(status=SUCCESS, requests=29, stored=12))

    result = runner.invoke(app, ["sync"])

    assert result.exit_code == 0
    assert "12 new payload(s)" in result.stdout


def test_a_real_failure_still_exits_non_zero(no_network) -> None:
    """The point of quietening the setup case is that this one stays loud."""
    no_network(SyncOutcome(status=FAILED, detail="rate limited"))

    result = runner.invoke(app, ["sync"])

    assert result.exit_code == 1
    assert "rate limited" in result.stdout


def test_an_unknown_source_is_rejected_before_anything_runs() -> None:
    result = runner.invoke(app, ["sync", "--source", "fitbit"])

    assert result.exit_code == 1
