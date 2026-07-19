"""Integration tests for POST /api/internal/scrape/start (RTA-16).

The endpoint kicks off `_run_internal_scrape` in a background thread.
Tests patch the worker so it doesn't reach out to TikTok and so we can
drive job state deterministically.
"""
from __future__ import annotations

import threading
import time

import pytest

from campaign_manager.blueprints import internal as internal_bp


pytestmark = pytest.mark.integration


def _seed_group(db, slug: str, members):
    """Create a group with the given slug and add member usernames."""
    group = db.create_internal_group(slug=slug, title=slug.title(), kind="label")
    assert group is not None
    # Members must exist as internal creators before being added to a group.
    db.save_internal_creators(list(members))
    db.add_group_members(group["id"], list(members))
    return group


@pytest.fixture(autouse=True)
def _reset_job_registry():
    """Clear in-memory job state between tests so they don't bleed."""
    with internal_bp._jobs_lock:
        internal_bp._jobs.clear()
        internal_bp._current_job_by_group.clear()
    internal_bp._internal_scrape_status = {
        "running": False, "done": False, "progress": "",
        "accounts_total": 0, "accounts_completed": 0, "accounts_failed": 0,
        "videos_so_far": 0, "current_accounts": [], "log": [],
    }
    yield
    with internal_bp._jobs_lock:
        internal_bp._jobs.clear()
        internal_bp._current_job_by_group.clear()


@pytest.fixture
def fake_worker(monkeypatch):
    """Replace the scrape worker with a controllable fake.

    Yields a dict with two threading.Events:
      - 'released' -- when set, the worker finishes and writes "done"
      - 'started'  -- the worker sets this once it has begun
    """
    released = threading.Event()
    started = threading.Event()

    def fake(hours, creators, *, start_date_str="", end_date_str="",
            job_id=None, group_slug=None, **_kwargs):
        started.set()
        # Mid-run progress update so polling tests see partial state.
        if job_id:
            with internal_bp._jobs_lock:
                job = internal_bp._jobs.get(job_id)
                if job:
                    job["progress"] = {"n": 1, "m": len(creators)}
                    job["last_log"] = "mid-run"
        released.wait(timeout=5)
        if job_id:
            internal_bp._update_job(
                job_id,
                state="done",
                progress={"n": len(creators), "m": len(creators)},
                last_log="fake-done",
            )
        if group_slug and job_id:
            internal_bp._clear_current_job(group_slug, job_id)

    monkeypatch.setattr(internal_bp, "_run_internal_scrape", fake)
    return {"released": released, "started": started}


class TestScrapeStartHappyPath:
    def test_returns_job_id_and_started_at(self, client, db, fake_worker):
        _seed_group(db, "warner", ["alice", "bob"])

        resp = client.post(
            "/api/internal/scrape/start",
            json={"group": "warner", "hours": 168},
        )
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["job_id"]
        assert body["started_at"]
        # ISO timestamp shape
        assert "T" in body["started_at"]

        fake_worker["released"].set()


class TestScrapeStartDebounce:
    def test_second_start_returns_existing_job(self, client, db, fake_worker):
        _seed_group(db, "atlantic", ["c1", "c2"])

        first = client.post(
            "/api/internal/scrape/start",
            json={"group": "atlantic", "hours": 168},
        ).get_json()
        # Make sure the worker thread has actually started before debounce check.
        assert fake_worker["started"].wait(timeout=2)

        second = client.post(
            "/api/internal/scrape/start",
            json={"group": "atlantic", "hours": 168},
        )
        assert second.status_code == 200
        body = second.get_json()
        assert body["job_id"] == first["job_id"]
        assert body.get("debounced") is True

        fake_worker["released"].set()

    def test_new_job_allowed_after_previous_finishes(self, client, db, fake_worker):
        _seed_group(db, "seeno", ["x", "y"])

        first = client.post(
            "/api/internal/scrape/start",
            json={"group": "seeno", "hours": 24},
        ).get_json()
        assert fake_worker["started"].wait(timeout=2)
        fake_worker["released"].set()

        # Wait for the first job to flip to "done".
        for _ in range(50):
            snap = internal_bp._job_snapshot(first["job_id"])
            if snap and snap["state"] == "done":
                break
            time.sleep(0.05)
        else:
            pytest.fail("first job never reached 'done' state")

        # Reset the events for the next worker invocation.
        fake_worker["released"].clear()
        fake_worker["started"].clear()

        second = client.post(
            "/api/internal/scrape/start",
            json={"group": "seeno", "hours": 24},
        ).get_json()
        assert second["job_id"] != first["job_id"]
        assert "debounced" not in second

        fake_worker["released"].set()


class TestScrapeStatusPolling:
    def test_status_reflects_progress(self, client, db, fake_worker):
        _seed_group(db, "warner_test", ["a", "b", "c"])

        started = client.post(
            "/api/internal/scrape/start",
            json={"group": "warner_test", "hours": 24},
        ).get_json()
        job_id = started["job_id"]

        # Wait for mid-run state to land.
        assert fake_worker["started"].wait(timeout=2)
        for _ in range(50):
            snap = client.get(
                f"/api/internal/scrape/status?job_id={job_id}"
            ).get_json()
            if snap and snap["progress"]["n"] >= 1:
                break
            time.sleep(0.05)
        else:
            pytest.fail("status never reflected mid-run progress")

        assert snap["state"] == "running"
        assert snap["progress"]["m"] == 3
        assert snap["last_log"] == "mid-run"

        fake_worker["released"].set()

        # Eventually status flips to done.
        for _ in range(50):
            snap = client.get(
                f"/api/internal/scrape/status?job_id={job_id}"
            ).get_json()
            if snap["state"] == "done":
                break
            time.sleep(0.05)
        else:
            pytest.fail("status never flipped to done")

        assert snap["progress"] == {"n": 3, "m": 3}
        assert snap["last_log"] == "fake-done"

    def test_status_for_unknown_job_id_returns_404(self, client, db):
        resp = client.get("/api/internal/scrape/status?job_id=does-not-exist")
        assert resp.status_code == 404

    def test_status_without_job_id_returns_legacy_shape(self, client, db):
        resp = client.get("/api/internal/scrape/status")
        assert resp.status_code == 200
        body = resp.get_json()
        # Legacy shape has these keys, not the per-job shape.
        assert "running" in body
        assert "accounts_total" in body


class TestScrapeStartErrors:
    def test_missing_group_returns_400(self, client, db):
        resp = client.post("/api/internal/scrape/start", json={"hours": 24})
        assert resp.status_code == 400
        assert "group" in (resp.get_json().get("error") or "").lower()

    def test_unknown_group_returns_404(self, client, db):
        resp = client.post(
            "/api/internal/scrape/start",
            json={"group": "no-such-group", "hours": 24},
        )
        assert resp.status_code == 404

    def test_empty_group_returns_400(self, client, db):
        _seed_group(db, "empty_label", [])
        # The seed fn won't add zero members; verify by querying.
        group = db.get_internal_group("empty_label")
        assert group is not None
        members = db.get_group_members(group["id"])
        assert members == []

        resp = client.post(
            "/api/internal/scrape/start",
            json={"group": "empty_label", "hours": 24},
        )
        assert resp.status_code == 400
        assert "no members" in (resp.get_json().get("error") or "").lower()

    def test_bad_hours_returns_400(self, client, db, fake_worker):
        _seed_group(db, "warner2", ["alice"])
        resp = client.post(
            "/api/internal/scrape/start",
            json={"group": "warner2", "hours": "not-a-number"},
        )
        assert resp.status_code == 400
