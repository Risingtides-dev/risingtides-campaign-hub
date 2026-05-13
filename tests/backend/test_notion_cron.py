"""Tests for the Notion sync cron tick (RTA-10).

We test the callable + its in-flight guard + the interval env-var resolver
in `campaign_manager.services.notion_sync`. The actual APScheduler wiring
in `scheduler.py` is not exercised here — that module requires apscheduler
+ a job-store database, and the value of testing the wiring beyond
"it calls add_job" is low compared to the brittleness it would introduce.
"""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from campaign_manager.services import notion_sync
from campaign_manager.services.notion_sync import (
    NOTION_SYNC_DEFAULT_INTERVAL_MINUTES,
    NOTION_SYNC_MAX_INTERVAL_MINUTES,
    get_notion_sync_interval_minutes,
    run_notion_sync,
)


@pytest.fixture(autouse=True)
def reset_inflight_guard():
    """Make sure each test starts with the global guard cleared. The
    callable resets it in `finally`, but a test that asserts raise-handling
    needs the post-test invariant verified."""
    notion_sync._notion_sync_in_progress = False
    yield
    notion_sync._notion_sync_in_progress = False


@pytest.fixture
def mocks():
    """Patch both stages. Default behavior: sync returns a happy result with
    a non-zero log id, resolve returns an empty happy result."""
    sync_default = notion_sync.SyncResult(
        pages_fetched=5, pages_added=5, pages_updated=0, pages_deleted=0,
        errors=[], sync_log_id=42,
    )
    resolve_default = notion_sync.ResolveResult(
        rows_processed=5, memberships_added=10, memberships_removed=0,
        groups_created=0, errors=[], sync_log_id=42,
    )
    with patch.object(notion_sync, "sync_master_pages", return_value=sync_default) as sync_mock, \
         patch.object(notion_sync, "resolve_memberships", return_value=resolve_default) as resolve_mock:
        yield sync_mock, resolve_mock


# ---------------------------------------------------------------------------
# Happy path / chaining
# ---------------------------------------------------------------------------

class TestChaining:
    def test_tick_calls_sync_then_resolve_in_order(self, mocks):
        sync_mock, resolve_mock = mocks
        run_notion_sync()
        sync_mock.assert_called_once_with(triggered_by="cron")
        resolve_mock.assert_called_once_with(triggered_by="cron", sync_log_id=42)

    def test_resolve_chains_onto_sync_log_id(self, mocks):
        sync_mock, resolve_mock = mocks
        sync_mock.return_value = notion_sync.SyncResult(
            pages_fetched=3, pages_added=0, sync_log_id=999,
        )
        run_notion_sync()
        assert resolve_mock.call_args.kwargs["sync_log_id"] == 999


# ---------------------------------------------------------------------------
# Error isolation
# ---------------------------------------------------------------------------

class TestErrorIsolation:
    def test_sync_raises_resolve_does_not_run(self, mocks):
        sync_mock, resolve_mock = mocks
        sync_mock.side_effect = RuntimeError("simulated sync explosion")

        # Must not raise — the scheduler thread depends on this.
        run_notion_sync()

        sync_mock.assert_called_once()
        resolve_mock.assert_not_called()

    def test_resolve_raises_is_caught(self, mocks):
        sync_mock, resolve_mock = mocks
        resolve_mock.side_effect = RuntimeError("simulated resolve explosion")

        # Should not raise.
        run_notion_sync()

        sync_mock.assert_called_once()
        resolve_mock.assert_called_once()

    def test_sync_per_row_errors_still_trigger_resolve(self, mocks):
        # Per-row errors are normal traffic (e.g. missing_account_username).
        # They live inside the returned SyncResult, not as exceptions, so
        # resolve must run.
        sync_mock, resolve_mock = mocks
        sync_mock.return_value = notion_sync.SyncResult(
            pages_fetched=5, pages_added=5,
            errors=[{"row_id": "x", "error_kind": "missing_account_username", "detail": "..."}],
            sync_log_id=42,
        )
        run_notion_sync()
        resolve_mock.assert_called_once()

    def test_sync_zero_pages_fetched_skips_resolve(self, mocks):
        # Fetch failed; no point reconciling against an unchanged mirror.
        sync_mock, resolve_mock = mocks
        sync_mock.return_value = notion_sync.SyncResult(
            pages_fetched=0, pages_added=0,
            errors=[{"row_id": "", "error_kind": "fetch_failed", "detail": "HTTP 503"}],
            sync_log_id=42,
        )
        run_notion_sync()
        resolve_mock.assert_not_called()


# ---------------------------------------------------------------------------
# In-flight guard
# ---------------------------------------------------------------------------

class TestInFlightGuard:
    def test_second_call_during_first_is_noop(self):
        # Use a barrier inside the mocked sync to hold the first invocation
        # open while we fire a second one from another thread.
        started = threading.Event()
        release = threading.Event()

        def slow_sync(**_):
            started.set()
            assert release.wait(timeout=5), "test setup deadlock"
            return notion_sync.SyncResult(
                pages_fetched=1, pages_added=0, sync_log_id=1,
            )

        with patch.object(notion_sync, "sync_master_pages", side_effect=slow_sync) as sync_mock, \
             patch.object(notion_sync, "resolve_memberships") as resolve_mock:
            t = threading.Thread(target=run_notion_sync)
            t.start()
            assert started.wait(timeout=5), "first tick never started"

            # Second invocation should see the guard set and bail.
            run_notion_sync()

            release.set()
            t.join(timeout=5)

            assert sync_mock.call_count == 1
            assert resolve_mock.call_count == 1

    def test_guard_releases_after_success(self, mocks):
        run_notion_sync()
        assert notion_sync._notion_sync_in_progress is False

    def test_guard_releases_after_sync_raises(self, mocks):
        sync_mock, _ = mocks
        sync_mock.side_effect = RuntimeError("boom")
        run_notion_sync()
        assert notion_sync._notion_sync_in_progress is False

    def test_guard_releases_after_resolve_raises(self, mocks):
        _, resolve_mock = mocks
        resolve_mock.side_effect = RuntimeError("boom")
        run_notion_sync()
        assert notion_sync._notion_sync_in_progress is False


# ---------------------------------------------------------------------------
# Interval env var
# ---------------------------------------------------------------------------

class TestInterval:
    def test_default_is_15(self, monkeypatch):
        monkeypatch.delenv("NOTION_SYNC_INTERVAL_MINUTES", raising=False)
        assert get_notion_sync_interval_minutes() == NOTION_SYNC_DEFAULT_INTERVAL_MINUTES == 15

    def test_override_to_30(self, monkeypatch):
        monkeypatch.setenv("NOTION_SYNC_INTERVAL_MINUTES", "30")
        assert get_notion_sync_interval_minutes() == 30

    def test_override_to_1_min(self, monkeypatch):
        monkeypatch.setenv("NOTION_SYNC_INTERVAL_MINUTES", "1")
        assert get_notion_sync_interval_minutes() == 1

    def test_override_to_max(self, monkeypatch):
        monkeypatch.setenv(
            "NOTION_SYNC_INTERVAL_MINUTES", str(NOTION_SYNC_MAX_INTERVAL_MINUTES),
        )
        assert get_notion_sync_interval_minutes() == NOTION_SYNC_MAX_INTERVAL_MINUTES

    def test_zero_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NOTION_SYNC_INTERVAL_MINUTES", "0")
        assert get_notion_sync_interval_minutes() == NOTION_SYNC_DEFAULT_INTERVAL_MINUTES

    def test_negative_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NOTION_SYNC_INTERVAL_MINUTES", "-5")
        assert get_notion_sync_interval_minutes() == NOTION_SYNC_DEFAULT_INTERVAL_MINUTES

    def test_above_max_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(
            "NOTION_SYNC_INTERVAL_MINUTES",
            str(NOTION_SYNC_MAX_INTERVAL_MINUTES + 1),
        )
        assert get_notion_sync_interval_minutes() == NOTION_SYNC_DEFAULT_INTERVAL_MINUTES

    def test_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NOTION_SYNC_INTERVAL_MINUTES", "not-an-int")
        assert get_notion_sync_interval_minutes() == NOTION_SYNC_DEFAULT_INTERVAL_MINUTES

    def test_empty_string_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("NOTION_SYNC_INTERVAL_MINUTES", "")
        assert get_notion_sync_interval_minutes() == NOTION_SYNC_DEFAULT_INTERVAL_MINUTES
