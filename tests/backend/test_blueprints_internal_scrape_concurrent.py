"""Concurrent-scrape isolation tests for the internal scrape endpoints (RTA-45).

Background
----------
RTA-16 introduced ``POST /api/internal/scrape/start`` which lets the UI
trigger per-group scrapes independently. The module-level
``_internal_scrape_status`` dict was previously reset on entry to
``_run_internal_scrape``, which meant two concurrent group scrapes would
overwrite each other's view of the legacy global status. Per-job
snapshots in ``_jobs`` were correct, but the legacy
``GET /api/internal/scrape/status`` (no ``job_id``) returned a clobbered
mix.

RTA-45 routes ALL status state through ``_jobs[job_id]``:
- Each job entry carries a ``legacy_status`` sub-dict in the
  legacy wire shape.
- ``GET /scrape/status`` with no job_id returns the most-recent job's
  ``legacy_status`` (or the empty default if no jobs have ever run).
- The legacy ``POST /api/internal/scrape`` route also creates a
  ``_jobs`` entry, tagged ``kind="legacy"``. Its single-flight guard
  checks only legacy-kind running jobs, so per-group scrapes triggered
  via ``/scrape/start`` don't block it and vice versa.

These tests cover:
- Concurrent isolation: two in-flight group scrapes don't overwrite
  each other's per-job legacy_status.
- Legacy fallback: ``/scrape/status`` with no job_id returns the
  most-recent job's snapshot.
- Per-job snapshot integrity under concurrent writes.
- The legacy entrypoint creates a ``kind="legacy"`` job and its guard
  only blocks on other legacy-kind running jobs (group jobs do not
  trip the guard).
"""
from __future__ import annotations

import threading
import time

import pytest

from campaign_manager.blueprints import internal as internal_bp


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_job_registry():
    """Clear in-memory job state between tests so they don't bleed.

    Mirrors the autouse fixture used in test_blueprints_internal_scrape_start.py
    so this file can be run in isolation and still get a clean registry.
    """
    with internal_bp._jobs_lock:
        internal_bp._jobs.clear()
        internal_bp._current_job_by_group.clear()
    internal_bp._internal_scrape_status = dict(internal_bp._INTERNAL_SCRAPE_STATUS_EMPTY)
    yield
    with internal_bp._jobs_lock:
        internal_bp._jobs.clear()
        internal_bp._current_job_by_group.clear()


def _seed_group(db, slug: str, members):
    group = db.create_internal_group(slug=slug, title=slug.title(), kind="label")
    assert group is not None
    db.save_internal_creators(list(members))
    if members:
        db.add_group_members(group["id"], list(members))
    return group


@pytest.fixture
def multi_fake_worker(monkeypatch):
    """Per-job-controllable worker. Tests release individual jobs by id.

    Yields:
      released[job_id] -> Event the test sets to let that worker finish.
      started[job_id]  -> Event the worker sets when it has begun.
    """
    released: dict = {}
    started: dict = {}
    state_lock = threading.Lock()

    def _event(d, jid):
        with state_lock:
            ev = d.get(jid)
            if ev is None:
                ev = threading.Event()
                d[jid] = ev
            return ev

    def fake(hours, creators, *, start_date_str="", end_date_str="",
             job_id=None, group_slug=None):
        if not job_id:
            # New contract: every worker invocation has a job_id.
            return
        ev_started = _event(started, job_id)
        ev_released = _event(released, job_id)
        ev_started.set()
        # Wait for the test to let us finish. Long timeout so a missed
        # release doesn't hang the suite forever.
        ev_released.wait(timeout=10)
        # Mark the job done, propagate to both shapes.
        internal_bp._update_job(
            job_id,
            state="done",
            progress={"n": len(creators), "m": len(creators)},
            last_log="fake-done",
        )
        internal_bp._patch_legacy_status(
            job_id,
            running=False,
            done=True,
            progress="fake-done",
            accounts_completed=len(creators),
            accounts_failed=0,
        )
        if group_slug and job_id:
            internal_bp._clear_current_job(group_slug, job_id)

    monkeypatch.setattr(internal_bp, "_run_internal_scrape", fake)
    return {"released": released, "started": started, "_event": _event}


# ---------------------------------------------------------------------------
# 1. Two concurrent group scrapes have isolated per-job state.
# ---------------------------------------------------------------------------

class TestConcurrentGroupScrapeIsolation:
    """The core RTA-45 invariant: concurrent group scrapes don't clobber
    each other's legacy_status snapshot inside ``_jobs``."""

    def test_two_concurrent_group_scrapes_have_distinct_jobs(self, client, db, multi_fake_worker):
        _seed_group(db, "warner", ["w1", "w2"])
        _seed_group(db, "atlantic", ["a1", "a2", "a3"])

        warner = client.post(
            "/api/internal/scrape/start",
            json={"group": "warner", "hours": 24},
        ).get_json()
        atlantic = client.post(
            "/api/internal/scrape/start",
            json={"group": "atlantic", "hours": 24},
        ).get_json()

        # Both workers must have entered _run_internal_scrape before we
        # can meaningfully compare their state. The fake worker sets
        # started[job_id] on entry.
        assert multi_fake_worker["_event"](multi_fake_worker["started"], warner["job_id"]).wait(timeout=2)
        assert multi_fake_worker["_event"](multi_fake_worker["started"], atlantic["job_id"]).wait(timeout=2)

        with internal_bp._jobs_lock:
            warner_job = internal_bp._jobs[warner["job_id"]]
            atlantic_job = internal_bp._jobs[atlantic["job_id"]]

            # Distinct job ids and group tags.
            assert warner["job_id"] != atlantic["job_id"]
            assert warner_job["group"] == "warner"
            assert atlantic_job["group"] == "atlantic"

            # Each carries its OWN legacy_status with the correct headcount.
            assert warner_job["legacy_status"]["accounts_total"] == 2
            assert atlantic_job["legacy_status"]["accounts_total"] == 3

            # Both are "running" in the legacy shape.
            assert warner_job["legacy_status"]["running"] is True
            assert atlantic_job["legacy_status"]["running"] is True

            # Both are tagged as group-kind jobs.
            assert warner_job["kind"] == "group"
            assert atlantic_job["kind"] == "group"

            # _current_job_by_group has separate pointers.
            assert internal_bp._current_job_by_group["warner"] == warner["job_id"]
            assert internal_bp._current_job_by_group["atlantic"] == atlantic["job_id"]

        # Release both so the test cleans up.
        multi_fake_worker["released"].setdefault(warner["job_id"], threading.Event()).set()
        multi_fake_worker["released"].setdefault(atlantic["job_id"], threading.Event()).set()

    def test_writes_to_one_jobs_legacy_status_dont_leak_to_the_other(
        self, client, db, multi_fake_worker,
    ):
        """The original bug: worker A's reset-on-entry overwrote worker B's
        view. Now each worker writes only to its own _jobs[job_id]
        ['legacy_status']. Simulate that directly."""
        _seed_group(db, "labelA", ["a1", "a2"])
        _seed_group(db, "labelB", ["b1", "b2", "b3", "b4"])

        a = client.post(
            "/api/internal/scrape/start",
            json={"group": "labelA", "hours": 24},
        ).get_json()
        b = client.post(
            "/api/internal/scrape/start",
            json={"group": "labelB", "hours": 24},
        ).get_json()
        assert multi_fake_worker["_event"](multi_fake_worker["started"], a["job_id"]).wait(timeout=2)
        assert multi_fake_worker["_event"](multi_fake_worker["started"], b["job_id"]).wait(timeout=2)

        # Write distinct progress markers via the same helper the worker
        # uses. If the production code is correct (per-job slot), these
        # writes can't bleed across jobs.
        internal_bp._patch_legacy_status(
            a["job_id"],
            progress="A is on account 1/2",
            accounts_completed=1,
            videos_so_far=10,
        )
        internal_bp._patch_legacy_status(
            b["job_id"],
            progress="B is on account 3/4",
            accounts_completed=3,
            videos_so_far=42,
        )

        snap_a = internal_bp._legacy_status_from_job(internal_bp._jobs[a["job_id"]])
        snap_b = internal_bp._legacy_status_from_job(internal_bp._jobs[b["job_id"]])

        assert snap_a["progress"] == "A is on account 1/2"
        assert snap_a["accounts_total"] == 2
        assert snap_a["accounts_completed"] == 1
        assert snap_a["videos_so_far"] == 10

        assert snap_b["progress"] == "B is on account 3/4"
        assert snap_b["accounts_total"] == 4
        assert snap_b["accounts_completed"] == 3
        assert snap_b["videos_so_far"] == 42

        multi_fake_worker["released"].setdefault(a["job_id"], threading.Event()).set()
        multi_fake_worker["released"].setdefault(b["job_id"], threading.Event()).set()

    def test_append_legacy_log_only_touches_target_job(
        self, client, db, multi_fake_worker,
    ):
        """Log appends were the most frequent legacy writes per account.
        They must not touch any other job's log list."""
        _seed_group(db, "g1", ["one"])
        _seed_group(db, "g2", ["two"])

        j1 = client.post(
            "/api/internal/scrape/start",
            json={"group": "g1", "hours": 24},
        ).get_json()
        j2 = client.post(
            "/api/internal/scrape/start",
            json={"group": "g2", "hours": 24},
        ).get_json()
        assert multi_fake_worker["_event"](multi_fake_worker["started"], j1["job_id"]).wait(timeout=2)
        assert multi_fake_worker["_event"](multi_fake_worker["started"], j2["job_id"]).wait(timeout=2)

        internal_bp._append_legacy_log(j1["job_id"], {"username": "one", "status": "ok", "video_count": 5})
        internal_bp._append_legacy_log(j2["job_id"], {"username": "two", "status": "failed", "video_count": 0, "error": "boom"})
        internal_bp._append_legacy_log(j1["job_id"], {"username": "one-extra", "status": "ok", "video_count": 7})

        snap_1 = internal_bp._legacy_status_from_job(internal_bp._jobs[j1["job_id"]])
        snap_2 = internal_bp._legacy_status_from_job(internal_bp._jobs[j2["job_id"]])

        assert [entry["username"] for entry in snap_1["log"]] == ["one", "one-extra"]
        assert [entry["username"] for entry in snap_2["log"]] == ["two"]
        assert snap_2["log"][0]["status"] == "failed"

        multi_fake_worker["released"].setdefault(j1["job_id"], threading.Event()).set()
        multi_fake_worker["released"].setdefault(j2["job_id"], threading.Event()).set()


# ---------------------------------------------------------------------------
# 2. Legacy GET /api/internal/scrape/status falls back to the most-recent job.
# ---------------------------------------------------------------------------

class TestLegacyStatusFallback:
    def test_empty_registry_returns_empty_default(self, client, db):
        """With no jobs ever inserted, the legacy shape collapses to the
        empty default. Wire format must still expose every legacy key so
        any existing UI consumer doesn't choke on missing fields."""
        resp = client.get("/api/internal/scrape/status")
        assert resp.status_code == 200
        body = resp.get_json()
        for key in (
            "running", "done", "progress",
            "accounts_total", "accounts_completed", "accounts_failed",
            "videos_so_far", "current_accounts", "log",
        ):
            assert key in body, f"legacy key '{key}' missing from empty default"
        assert body["running"] is False
        assert body["done"] is False
        assert body["accounts_total"] == 0
        assert body["log"] == []

    def test_returns_most_recent_jobs_legacy_status(self, client, db, multi_fake_worker):
        """Two concurrent jobs in flight; legacy poll returns the
        most-recently-started one's snapshot, not a blended mess."""
        _seed_group(db, "first", ["f1"])
        _seed_group(db, "second", ["s1", "s2"])

        first = client.post(
            "/api/internal/scrape/start",
            json={"group": "first", "hours": 24},
        ).get_json()
        # Tiny pause guarantees a distinct started_at on second job. The
        # comparison is string-lexicographic on ISO timestamps with same
        # timezone, which is monotonic in time; without a delay both
        # jobs could share a started_at and ordering would tie.
        time.sleep(0.01)
        second = client.post(
            "/api/internal/scrape/start",
            json={"group": "second", "hours": 24},
        ).get_json()
        assert multi_fake_worker["_event"](multi_fake_worker["started"], first["job_id"]).wait(timeout=2)
        assert multi_fake_worker["_event"](multi_fake_worker["started"], second["job_id"]).wait(timeout=2)

        # Distinguish the two by accounts_total.
        body = client.get("/api/internal/scrape/status").get_json()
        assert body["accounts_total"] == 2  # second was the more recent
        assert body["running"] is True

        multi_fake_worker["released"].setdefault(first["job_id"], threading.Event()).set()
        multi_fake_worker["released"].setdefault(second["job_id"], threading.Event()).set()

    def test_status_reflects_terminal_state_after_workers_finish(
        self, client, db, multi_fake_worker,
    ):
        """Once both workers finish, the legacy status still returns the
        most-recent job's terminal state (not a stale 'running' from
        somewhere else)."""
        _seed_group(db, "alpha", ["x"])
        _seed_group(db, "beta", ["y"])

        alpha = client.post(
            "/api/internal/scrape/start",
            json={"group": "alpha", "hours": 24},
        ).get_json()
        time.sleep(0.01)
        beta = client.post(
            "/api/internal/scrape/start",
            json={"group": "beta", "hours": 24},
        ).get_json()
        assert multi_fake_worker["_event"](multi_fake_worker["started"], alpha["job_id"]).wait(timeout=2)
        assert multi_fake_worker["_event"](multi_fake_worker["started"], beta["job_id"]).wait(timeout=2)

        multi_fake_worker["released"].setdefault(alpha["job_id"], threading.Event()).set()
        multi_fake_worker["released"].setdefault(beta["job_id"], threading.Event()).set()

        # Wait for both jobs to flip terminal via the fake worker.
        def _both_done():
            for jid in (alpha["job_id"], beta["job_id"]):
                snap = internal_bp._job_snapshot(jid)
                if not snap or snap["state"] != "done":
                    return False
            return True

        for _ in range(50):
            if _both_done():
                break
            time.sleep(0.05)
        else:
            pytest.fail("workers never finished")

        body = client.get("/api/internal/scrape/status").get_json()
        # The most-recent job is `beta`. Its terminal legacy shape has
        # running=False, done=True.
        assert body["running"] is False
        assert body["done"] is True
        assert body["accounts_total"] == 1  # beta has 1 member
        assert body["accounts_completed"] == 1


# ---------------------------------------------------------------------------
# 3. Per-job snapshot stays consistent under concurrent writes.
# ---------------------------------------------------------------------------

class TestPerJobSnapshotConsistency:
    def test_concurrent_legacy_status_writes_dont_lose_or_corrupt_entries(
        self, client, db, multi_fake_worker,
    ):
        """Hammer a single job with many small writes from several threads
        while the worker is parked. Lock discipline must produce exactly
        N log entries with no torn writes."""
        _seed_group(db, "hammer", ["h"])

        started = client.post(
            "/api/internal/scrape/start",
            json={"group": "hammer", "hours": 24},
        ).get_json()
        assert multi_fake_worker["_event"](multi_fake_worker["started"], started["job_id"]).wait(timeout=2)

        N_THREADS = 8
        WRITES_PER_THREAD = 25

        def _writer(tid: int):
            for i in range(WRITES_PER_THREAD):
                internal_bp._append_legacy_log(
                    started["job_id"],
                    {"username": f"t{tid}-{i}", "status": "ok", "video_count": i},
                )

        threads = [threading.Thread(target=_writer, args=(t,)) for t in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        snap = internal_bp._legacy_status_from_job(internal_bp._jobs[started["job_id"]])
        assert len(snap["log"]) == N_THREADS * WRITES_PER_THREAD

        # Every entry must be well-formed (no half-written dicts).
        for entry in snap["log"]:
            assert set(entry.keys()) == {"username", "status", "video_count"}
            assert entry["status"] == "ok"
            assert isinstance(entry["video_count"], int)

        # Each writer thread's entries are all present.
        seen_writers = {entry["username"].split("-")[0] for entry in snap["log"]}
        assert seen_writers == {f"t{i}" for i in range(N_THREADS)}

        multi_fake_worker["released"].setdefault(started["job_id"], threading.Event()).set()


# ---------------------------------------------------------------------------
# 4. Legacy entrypoint: kind=legacy + guard isolation from group jobs.
# ---------------------------------------------------------------------------

class TestLegacyEndpointKindIsolation:
    """The legacy ``POST /api/internal/scrape`` route was the only
    trigger before RTA-16. Its single-flight guard previously read
    ``_internal_scrape_status.get("running")`` — RTA-45 narrows that to
    'is a kind="legacy" job running?' so per-group concurrency (RTA-16)
    doesn't break it and vice versa."""

    def test_running_group_job_does_not_block_legacy_endpoint(
        self, client, db, multi_fake_worker,
    ):
        """If a group scrape is in flight, the legacy entrypoint must
        still accept a new request. They have independent in-flight
        semantics."""
        _seed_group(db, "warner_iso", ["w"])
        # Need at least one creator on the flat list too, so the legacy
        # "scrape all" branch has work to do.
        db.save_internal_creators(["w"])

        group_job = client.post(
            "/api/internal/scrape/start",
            json={"group": "warner_iso", "hours": 24},
        ).get_json()
        assert multi_fake_worker["_event"](multi_fake_worker["started"], group_job["job_id"]).wait(timeout=2)

        # Legacy endpoint should NOT be blocked by the running group job.
        resp = client.post("/api/internal/scrape", json={"hours": 24})
        assert resp.status_code == 200, resp.get_json()

        # And the new job is tagged kind="legacy".
        # Find it by scanning for the legacy-kind running entry.
        with internal_bp._jobs_lock:
            legacy_ids = [
                jid for jid, j in internal_bp._jobs.items()
                if j.get("kind") == "legacy" and j.get("state") == "running"
            ]
        assert len(legacy_ids) == 1
        legacy_id = legacy_ids[0]

        # Release everything.
        multi_fake_worker["released"].setdefault(group_job["job_id"], threading.Event()).set()
        multi_fake_worker["released"].setdefault(legacy_id, threading.Event()).set()

    def test_running_legacy_job_blocks_new_legacy_call(
        self, client, db, multi_fake_worker,
    ):
        """Single-flight semantics for the legacy endpoint are preserved:
        two legacy POSTs in a row → second gets 409."""
        db.save_internal_creators(["solo"])

        first = client.post("/api/internal/scrape", json={"hours": 24})
        assert first.status_code == 200

        # Identify the legacy job that was just inserted.
        with internal_bp._jobs_lock:
            legacy_ids = [
                jid for jid, j in internal_bp._jobs.items()
                if j.get("kind") == "legacy" and j.get("state") == "running"
            ]
        assert len(legacy_ids) == 1
        legacy_id = legacy_ids[0]
        assert multi_fake_worker["_event"](multi_fake_worker["started"], legacy_id).wait(timeout=2)

        # Second legacy call while the first is running → 409.
        second = client.post("/api/internal/scrape", json={"hours": 24})
        assert second.status_code == 409
        body = second.get_json()
        assert "already running" in (body.get("error") or "").lower()

        multi_fake_worker["released"].setdefault(legacy_id, threading.Event()).set()

    def test_legacy_endpoint_seeds_legacy_status_immediately(
        self, client, db, multi_fake_worker,
    ):
        """After POST /api/internal/scrape returns, a same-tick GET
        /api/internal/scrape/status (no job_id) reflects the new scrape
        — the route inserts the _jobs entry with running=True before
        spawning the worker thread, so polling can't race ahead of the
        worker and see the previous job's terminal state."""
        db.save_internal_creators(["one", "two", "three"])

        resp = client.post("/api/internal/scrape", json={"hours": 24})
        assert resp.status_code == 200

        body = client.get("/api/internal/scrape/status").get_json()
        assert body["running"] is True
        assert body["accounts_total"] == 3

        # Find the job id we just created so we can release the worker.
        with internal_bp._jobs_lock:
            legacy_ids = [
                jid for jid, j in internal_bp._jobs.items()
                if j.get("kind") == "legacy" and j.get("state") == "running"
            ]
        for jid in legacy_ids:
            multi_fake_worker["released"].setdefault(jid, threading.Event()).set()
