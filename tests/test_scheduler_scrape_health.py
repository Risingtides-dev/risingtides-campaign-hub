from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from campaign_manager.services import scheduler, scrape_trigger
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


def test_native_crash_is_not_retried_and_stays_creator_scoped(monkeypatch):
    """One bad subprocess must not cancel the other 215 creators."""
    calls = []

    def scrape(handle, *_args, **_kwargs):
        calls.append(handle)
        if handle == "@crasher":
            raise NativeSubprocessCrash("yt-dlp for @crasher", -6)
        return [{"id": handle}]

    monkeypatch.setattr(scheduler, "_import_scraper", lambda: (scrape, None))
    monkeypatch.setattr(random, "uniform", lambda *_args: 0.0)

    videos, scraped, errors, outcomes = _scrape_creator_accounts_v2(
        ["crasher", "healthy_a", "healthy_b"], max_workers=1
    )

    # not retried — one attempt only for the crashing creator
    assert calls.count("@crasher") == 1
    # the rest of the fleet still ran and still returned data
    assert scraped == 2
    assert len(videos) == 2
    assert outcomes["crasher"]["status"] == "native_crash"
    assert outcomes["healthy_a"]["status"] == "ok"
    assert outcomes["healthy_b"]["status"] == "ok"
    assert len(errors) == 1


def test_fleet_wide_native_crash_still_fails_the_run(monkeypatch):
    """Isolated crashes are noise; a fleet-wide crash rate is real corruption."""
    def crash(*_args, **_kwargs):
        raise NativeSubprocessCrash("yt-dlp crash", -6)

    monkeypatch.setattr(scheduler, "_import_scraper", lambda: (crash, None))
    monkeypatch.setattr(random, "uniform", lambda *_args: 0.0)

    with pytest.raises(NativeSubprocessCrash):
        _scrape_creator_accounts_v2([f"c{i}" for i in range(10)], max_workers=1)


def test_high_native_crash_rate_marks_run_degraded():
    assert _degraded({"ok": 6, "empty": 0, "native_crash": 4}) is True


def test_single_native_crash_does_not_mark_run_degraded():
    assert _degraded({"ok": 9, "empty": 0, "native_crash": 1}) is False


def test_complete_instagram_failure_degrades_without_changing_tiktok_thresholds():
    assert _degraded({"ok": 9, "empty": 1}, instagram_complete_failure=True) is True
    assert _degraded({"ok": 9, "empty": 1}, instagram_complete_failure=False) is False


def test_instagram_outcome_accounting_normalizes_requested_names_only():
    assert scheduler._instagram_outcome_counts(
        {"@Artist", "https://www.instagram.com/second/"},
        {"artist": {"status": "ok"}, "@SECOND": {"status": "error"},
         "unrequested": {"status": "ok"}},
    ) == {"ok": 1, "empty": 0, "error": 1, "missing": 0}


@pytest.mark.parametrize("outcome_mode, expected_degraded, expected_counts", [
    ("all_errors", True, {"ok": 0, "empty": 0, "error": 18, "missing": 0}),
    ("partial", False, {"ok": 0, "empty": 1, "error": 17, "missing": 0}),
    ("empty_map", True, {"ok": 0, "empty": 0, "error": 0, "missing": 18}),
    ("extraneous_ok", True, {"ok": 0, "empty": 0, "error": 17, "missing": 1}),
])
def test_instagram_only_apify_failure_persists_degraded_and_notifies_truthfully(
    monkeypatch, outcome_mode, expected_degraded, expected_counts,
):
    campaign = {"slug": "ig-only", "completion_status": "none", "start_date": "2026-10-01"}
    saved = {}
    notices = []
    monkeypatch.setattr(scheduler._db, "list_campaigns", lambda **_kwargs: [campaign])
    monkeypatch.setattr(scheduler._db, "get_creators", lambda _slug: [
        {"username": f"ig{n}", "platform": "instagram", "status": "active"}
        for n in range(18)
    ])
    def instagram_result(names, _start):
        ordered = sorted(names)
        if outcome_mode == "empty_map":
            outcomes = {}
        elif outcome_mode == "extraneous_ok":
            outcomes = {name: {"status": "error"} for name in ordered[:-1]}
            outcomes["unrequested"] = {"status": "ok"}
        else:
            outcomes = {
                name: {"status": "empty" if outcome_mode == "partial" and index == 17 else "error"}
                for index, name in enumerate(ordered)
            }
        return SimpleNamespace(
            videos=[], errors=["instagram scrape failed: APIFY_API_TOKEN is not set"],
            outcomes=outcomes,
        )

    monkeypatch.setattr(scheduler, "_scrape_instagram", instagram_result)
    monkeypatch.setattr(scheduler, "_refresh_single_campaign", lambda *_args, **_kwargs: {
        "new_matches": 0, "total_matches": 0, "videos_checked": 0,
    })
    monkeypatch.setattr(scheduler._db, "finish_cron_log", lambda _id, state, summary: saved.update(
        status=state, summary=summary,
    ))
    monkeypatch.setattr(scheduler._db, "get_cron_log_by_id", lambda _id: None)
    monkeypatch.setattr(scheduler, "_post_campaign_refresh_slack", lambda summary: notices.append(summary))
    monkeypatch.setattr(scheduler, "_post_new_matches_digest_slack", lambda *_args: None)
    monkeypatch.setattr(scheduler, "_post_active_sounds_slack", lambda: None)
    monkeypatch.setattr(
        "campaign_manager.services.tides_tracker.auto_track_submitted_videos",
        lambda **_kwargs: SimpleNamespace(trackers_polled=0, trackers_failed=0,
                                         submission_ids_found=0, queue_rows_auto_tracked=0),
    )
    result = scheduler._run_campaign_refresh(None, None, SimpleNamespace(assert_held=lambda: None), 982)
    assert result["status"] == saved["status"] == "completed"
    assert result["summary"]["degraded"] is expected_degraded
    assert result["summary"]["instagram_complete_failure"] is expected_degraded
    assert result["summary"]["instagram_outcome_counts"] == expected_counts
    assert result["summary"]["scrape_outcome_counts"] == {"ok": 0, "empty": 0, "error": 0}
    assert notices == [result["summary"]]


def test_instagram_notification_names_failure_without_tiktok_diagnosis(monkeypatch):
    sent = []
    monkeypatch.setattr(scheduler, "_get_slack_client", lambda: SimpleNamespace(
        chat_postMessage=lambda **kwargs: sent.append(kwargs["text"]),
    ))
    monkeypatch.setattr(scheduler, "_get_cron_channel", lambda: "test-channel")
    scheduler._post_campaign_refresh_slack({
        "campaigns_refreshed": 1, "campaigns_total": 1, "degraded": True,
        "instagram_creators_total": 18,
        "instagram_outcome_counts": {"ok": 0, "empty": 0, "error": 0, "missing": 18},
        "instagram_complete_failure": True,
    })
    assert "DEGRADED" in sent[0]
    assert "0 errored, 18 missing outcomes" in sent[0]
    assert "All Instagram creator scrapes failed" in sent[0]
    assert "TikTok rate-limited" not in sent[0]


def test_on_demand_trigger_surfaces_failed_refresh(monkeypatch):
    job_id = "native-crash-job"
    with scrape_trigger._jobs_lock:
        scrape_trigger._jobs.clear()
        scrape_trigger._jobs[job_id] = {
            "state": "running",
            "scope": "all_active",
            "started_at": "2026-07-24T17:00:00",
        }

    monkeypatch.setattr(
        scheduler,
        "run_campaign_refresh",
        lambda **_kwargs: {
            "id": 420,
            "status": "failed",
            "summary": {"error": "yt-dlp terminated by native signal SIGABRT"},
        },
    )

    scrape_trigger._run(job_id, None)
    status = scrape_trigger.job_status(job_id)

    assert status["state"] == "error"
    assert status["error"] == "yt-dlp terminated by native signal SIGABRT"
    assert status["result"]["id"] == 420

    with scrape_trigger._jobs_lock:
        scrape_trigger._jobs.clear()
