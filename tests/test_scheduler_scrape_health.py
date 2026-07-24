from __future__ import annotations

import random

import pytest

from campaign_manager.services import scheduler
from campaign_manager.services.scheduler import (
    _scrape_creator_accounts_v2,
    _scrape_run_is_degraded,
)
from src.scrapers.yt_dlp_runner import NativeSubprocessCrash


def _degraded(outcomes: dict, **overrides) -> bool:
    values = {
        "total_creators": 10,
        "campaigns_refreshed": 10,
        "total_new_matches": 3,
        "total_videos_checked": 100,
    }
    values.update(overrides)
    return _scrape_run_is_degraded(outcomes, **values)


def test_ordinary_creator_error_does_not_trigger_global_anomaly():
    assert _degraded({"ok": 9, "empty": 0, "error": 1}) is False


def test_healthy_creator_distribution_is_not_degraded():
    assert _degraded({"ok": 9, "empty": 1, "error": 0}) is False


def test_high_empty_rate_remains_degraded():
    assert _degraded({"ok": 2, "empty": 8, "error": 0}) is True


def test_zero_work_anomaly_remains_degraded():
    assert _degraded(
        {"ok": 10, "empty": 0, "error": 0},
        total_new_matches=0,
        total_videos_checked=0,
    ) is True


def test_native_crash_is_not_retried_or_converted_to_creator_error(monkeypatch):
    calls = []

    def crash(*_args, **_kwargs):
        calls.append("called")
        raise NativeSubprocessCrash("yt-dlp for @creator", -6)

    monkeypatch.setattr(scheduler, "_import_scraper", lambda: (crash, None))
    monkeypatch.setattr(random, "uniform", lambda *_args: 0.0)

    with pytest.raises(NativeSubprocessCrash):
        _scrape_creator_accounts_v2(["creator"], max_workers=1)

    assert calls == ["called"]
