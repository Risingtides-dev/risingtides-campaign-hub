"""Unit tests for the RTA-46 `_jobs` registry pruning behavior.

The `_jobs` dict in `campaign_manager.blueprints.internal` is in-memory and
shared by route handlers + worker threads. Without bounded retention it
grows one entry per scrape for the lifetime of the dyno. These tests
exercise the prune-on-insert sweep added by RTA-46.

All tests call `_prune_jobs` directly (under the lock, matching how the
production caller in `scrape_start` invokes it) so they don't depend on
the HTTP route or a fake worker thread. The route-level integration is
covered by `test_blueprints_internal_scrape_start.py`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from campaign_manager.blueprints import internal as internal_bp
from campaign_manager.blueprints.internal import (
    EST,
    INTERNAL_JOBS_DEFAULT_TTL_HOURS,
    INTERNAL_JOBS_MAX_TTL_HOURS,
    INTERNAL_JOBS_MIN_TTL_HOURS,
    _prune_jobs,
    get_internal_jobs_ttl_hours,
)


@pytest.fixture(autouse=True)
def _reset_job_registry():
    """Clear in-memory job state between tests so they don't bleed."""
    with internal_bp._jobs_lock:
        internal_bp._jobs.clear()
        internal_bp._current_job_by_group.clear()
    yield
    with internal_bp._jobs_lock:
        internal_bp._jobs.clear()
        internal_bp._current_job_by_group.clear()


def _seed_job(job_id: str, *, state: str, age_hours: float, group: str = "warner") -> None:
    """Insert a fake job entry with a backdated `started_at`. Caller need
    not hold the lock — used only from single-threaded test setup."""
    started = (datetime.now(EST) - timedelta(hours=age_hours)).isoformat()
    internal_bp._jobs[job_id] = {
        "group": group,
        "started_at": started,
        "state": state,
        "progress": {"n": 0, "m": 1},
        "last_log": "",
        "error": None,
    }


class TestPruneOnInsert:
    """Stale terminal entries get swept; fresh terminal + in-flight survive."""

    def test_sweeps_stale_done_and_error_entries(self):
        # Default TTL is 24h, so anything older than 24h is sweep-eligible.
        _seed_job("stale-done", state="done", age_hours=25)
        _seed_job("stale-error", state="error", age_hours=30)
        _seed_job("fresh-done", state="done", age_hours=1)
        _seed_job("fresh-error", state="error", age_hours=23)

        with internal_bp._jobs_lock:
            pruned = _prune_jobs()

        assert pruned == 2
        assert "stale-done" not in internal_bp._jobs
        assert "stale-error" not in internal_bp._jobs
        assert "fresh-done" in internal_bp._jobs
        assert "fresh-error" in internal_bp._jobs

    def test_idempotent_when_nothing_to_prune(self):
        _seed_job("fresh", state="done", age_hours=1)

        with internal_bp._jobs_lock:
            first = _prune_jobs()
            second = _prune_jobs()

        assert first == 0
        assert second == 0
        assert "fresh" in internal_bp._jobs

    def test_drops_terminal_entries_with_unparseable_started_at(self):
        """Defensive: a done/error entry with a corrupt started_at is treated
        as ancient. Should never happen in production (insert path always
        writes an ISO string), but we don't want a single bad entry to
        anchor the dict and defeat pruning."""
        internal_bp._jobs["bad-ts"] = {
            "group": "warner",
            "started_at": "not-a-timestamp",
            "state": "done",
            "progress": {"n": 0, "m": 0},
            "last_log": "",
            "error": None,
        }
        internal_bp._jobs["missing-ts"] = {
            "group": "warner",
            "started_at": None,
            "state": "error",
            "progress": {"n": 0, "m": 0},
            "last_log": "",
            "error": None,
        }

        with internal_bp._jobs_lock:
            pruned = _prune_jobs()

        assert pruned == 2
        assert "bad-ts" not in internal_bp._jobs
        assert "missing-ts" not in internal_bp._jobs

    def test_clears_stale_current_job_pointer_for_pruned_jobs(self):
        """If a worker dies mid-flight, _clear_current_job may never run,
        leaving _current_job_by_group pointing at a terminal entry. Prune
        should clean both sides so the pointer can't outlive the dict
        entry it references."""
        _seed_job("stale", state="done", age_hours=100)
        internal_bp._current_job_by_group["warner"] = "stale"

        with internal_bp._jobs_lock:
            pruned = _prune_jobs()

        assert pruned == 1
        assert "stale" not in internal_bp._jobs
        assert "warner" not in internal_bp._current_job_by_group


class TestNoPruneInFlight:
    """Running jobs are never pruned, regardless of age."""

    def test_running_job_older_than_ttl_survives(self):
        # 100 hours > default 24-hour TTL. Should still survive because
        # the worker thread is presumed to be still writing to it.
        _seed_job("long-runner", state="running", age_hours=100)

        with internal_bp._jobs_lock:
            pruned = _prune_jobs()

        assert pruned == 0
        assert "long-runner" in internal_bp._jobs

    def test_running_pointer_preserved(self):
        """The _current_job_by_group entry for a running job must also
        survive — debounce reads from it."""
        _seed_job("active", state="running", age_hours=50)
        internal_bp._current_job_by_group["warner"] = "active"

        with internal_bp._jobs_lock:
            _prune_jobs()

        assert internal_bp._current_job_by_group.get("warner") == "active"

    def test_mixed_run_keeps_running_drops_stale_terminal(self):
        _seed_job("active", state="running", age_hours=72)
        _seed_job("done-stale", state="done", age_hours=72)
        _seed_job("done-fresh", state="done", age_hours=2)

        with internal_bp._jobs_lock:
            pruned = _prune_jobs()

        assert pruned == 1
        assert "active" in internal_bp._jobs
        assert "done-fresh" in internal_bp._jobs
        assert "done-stale" not in internal_bp._jobs


class TestEnvOverride:
    """INTERNAL_JOBS_TTL_HOURS shortens or lengthens retention."""

    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("INTERNAL_JOBS_TTL_HOURS", raising=False)
        assert get_internal_jobs_ttl_hours() == INTERNAL_JOBS_DEFAULT_TTL_HOURS

    def test_env_override_shortens_ttl(self, monkeypatch):
        """A 2-hour-old done job survives at the default TTL but is pruned
        once the env var lowers the TTL to 1 hour."""
        monkeypatch.delenv("INTERNAL_JOBS_TTL_HOURS", raising=False)
        _seed_job("two-hour-old", state="done", age_hours=2)

        # Default TTL (24h): two-hour-old job survives.
        with internal_bp._jobs_lock:
            pruned_default = _prune_jobs()
        assert pruned_default == 0
        assert "two-hour-old" in internal_bp._jobs

        # Env override (1h): same job now gets swept.
        monkeypatch.setenv("INTERNAL_JOBS_TTL_HOURS", "1")
        assert get_internal_jobs_ttl_hours() == 1
        with internal_bp._jobs_lock:
            pruned_override = _prune_jobs()
        assert pruned_override == 1
        assert "two-hour-old" not in internal_bp._jobs

    def test_env_override_lengthens_ttl(self, monkeypatch):
        """A 48-hour-old done job gets pruned at the default TTL but
        survives when the env raises the retention window past it."""
        _seed_job("two-day-old", state="done", age_hours=48)

        monkeypatch.setenv("INTERNAL_JOBS_TTL_HOURS", "168")  # 7 days
        assert get_internal_jobs_ttl_hours() == 168
        with internal_bp._jobs_lock:
            pruned = _prune_jobs()

        assert pruned == 0
        assert "two-day-old" in internal_bp._jobs

    def test_unparseable_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("INTERNAL_JOBS_TTL_HOURS", "not-a-number")
        assert get_internal_jobs_ttl_hours() == INTERNAL_JOBS_DEFAULT_TTL_HOURS

    def test_out_of_bounds_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(
            "INTERNAL_JOBS_TTL_HOURS",
            str(INTERNAL_JOBS_MAX_TTL_HOURS + 1),
        )
        assert get_internal_jobs_ttl_hours() == INTERNAL_JOBS_DEFAULT_TTL_HOURS

        monkeypatch.setenv(
            "INTERNAL_JOBS_TTL_HOURS",
            str(INTERNAL_JOBS_MIN_TTL_HOURS - 1),
        )
        assert get_internal_jobs_ttl_hours() == INTERNAL_JOBS_DEFAULT_TTL_HOURS

    def test_empty_string_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("INTERNAL_JOBS_TTL_HOURS", "")
        assert get_internal_jobs_ttl_hours() == INTERNAL_JOBS_DEFAULT_TTL_HOURS
