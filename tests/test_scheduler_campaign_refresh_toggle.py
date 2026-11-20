"""Offline scheduler transition checks with a disposable persistent jobstore."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler

from campaign_manager.services import scheduler
import campaign_manager


def _record_stale_job(path: str) -> None:
    Path(path).write_text("fired")


def test_app_passes_campaign_only_toggle_without_disabling_scheduler(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(campaign_manager, "_SCHEDULER_LOCK_PATH", str(tmp_path / "owner.lock"))
    monkeypatch.setattr(campaign_manager.db, "is_active", lambda: True)
    monkeypatch.setattr(campaign_manager.db, "completion_status_repair_ok", lambda: True)
    monkeypatch.setattr(scheduler, "init_scheduler", lambda **kwargs: captured.append(kwargs))
    app = SimpleNamespace(config={
        "SCHEDULER_ENABLED": True, "DATABASE_URL": "sqlite:///disposable",
        "CAMPAIGN_REFRESH_SCHEDULER_ENABLED": False,
    })
    try:
        assert campaign_manager._maybe_start_scheduler(app) is True
        assert captured[0]["campaign_refresh_enabled"] is False
    finally:
        if getattr(app, "_scheduler_lock", None):
            app._scheduler_lock.close()


def test_persisted_job_removal_failure_never_resumes_or_pins_singleton(monkeypatch):
    calls = []

    class FailingScheduler:
        running = False

        def __init__(self, **_kwargs):
            pass

        def add_job(self, *_args, **_kwargs):
            pass

        def start(self, *, paused=False):
            calls.append(("start", paused))
            self.running = True

        def get_job(self, _job_id):
            return object()

        def remove_job(self, _job_id):
            raise RuntimeError("test-owned removal failure")

        def resume(self):
            calls.append(("resume", False))

        def shutdown(self, *, wait):
            calls.append(("shutdown", wait))
            self.running = False

    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "BackgroundScheduler", FailingScheduler)
    monkeypatch.setattr(scheduler, "SQLAlchemyJobStore", lambda **_kwargs: object())
    with pytest.raises(RuntimeError, match="test-owned removal failure"):
        scheduler.init_scheduler("sqlite://", campaign_refresh_enabled=False)
    assert calls == [("start", True), ("shutdown", False)]
    assert scheduler._scheduler is None


def test_disabled_campaign_refresh_removes_persisted_due_job_before_resume(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'scheduler.sqlite'}"
    fired = tmp_path / "stale-fired"
    old = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=database_url)}, timezone=scheduler.EST,
    )
    old.add_job(
        _record_stale_job, "date",
        run_date=datetime.now(scheduler.EST) + timedelta(seconds=1),
        kwargs={"path": str(fired)}, id="campaign_refresh", misfire_grace_time=3600,
    )
    old.start(paused=True)
    assert old.get_job("campaign_refresh") is not None
    old.shutdown(wait=True)
    time.sleep(1.1)

    monkeypatch.setattr(scheduler, "_scheduler", None)
    try:
        scheduler.init_scheduler(database_url, campaign_refresh_enabled=False)
        assert scheduler._scheduler.running
        assert scheduler._scheduler.get_job("campaign_refresh") is None
        for retained in ("internal_scrape", "notion_sync", "crm_sync", "campaign_niche_refresh",
                         "tides_tracker_pull", "library_stats", "cron_log_janitor"):
            assert scheduler._scheduler.get_job(retained) is not None
        time.sleep(0.15)
        assert not fired.exists()
    finally:
        if scheduler._scheduler and scheduler._scheduler.running:
            scheduler._scheduler.shutdown(wait=True)
        monkeypatch.setattr(scheduler, "_scheduler", None)

    # Turning the knob back on restores only the scheduled campaign job.
    try:
        scheduler.init_scheduler(database_url, campaign_refresh_enabled=True)
        assert scheduler._scheduler.get_job("campaign_refresh") is not None
        assert scheduler._scheduler.get_job("internal_scrape") is not None
    finally:
        if scheduler._scheduler and scheduler._scheduler.running:
            scheduler._scheduler.shutdown(wait=True)
        monkeypatch.setattr(scheduler, "_scheduler", None)
