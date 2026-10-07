from __future__ import annotations

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from campaign_manager import db
from campaign_manager.services import scheduler


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _FakeConnection:
    def __init__(self, shared, pid):
        self.shared = shared
        self.pid = pid
        self.invalidated = False
        self.closed = False

    def execute(self, sql, params=None):
        statement = str(sql)
        if "pg_backend_pid()" in statement:
            return _Result(self.pid)
        if "FROM pg_locks" in statement:
            key = (params["high"] << 32) | params["low"]
            owner = self.shared["owners"].get(key)
            return _Result(owner is not None and (
                params["pid"] is None or owner == params["pid"]
            ))
        key = params["key"]
        with self.shared["mutex"]:
            if "pg_try_advisory_lock" in statement:
                owner = self.shared["owners"].get(key)
                if owner is None or owner == self.pid:
                    self.shared["owners"][key] = self.pid
                    return _Result(True)
                return _Result(False)
            if "pg_advisory_unlock" in statement:
                owned = self.shared["owners"].get(key) == self.pid
                if owned:
                    del self.shared["owners"][key]
                return _Result(owned)
        raise AssertionError(statement)

    def commit(self):
        pass

    def invalidate(self):
        self.invalidated = True

    def close(self):
        self.closed = True


class _FakePostgresEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self):
        self.shared = {"mutex": threading.Lock(), "owners": {}}
        self.connections = []

    def connect(self):
        connection = _FakeConnection(self.shared, 1000 + len(self.connections))
        self.connections.append(connection)
        return connection


def test_postgres_job_lease_rejects_duplicate_across_connections(monkeypatch):
    engine = _FakePostgresEngine()
    monkeypatch.setattr(db, "_engine", engine)

    with db.scrape_job_lease("campaign_refresh") as first:
        assert first is not None
        first.assert_held()
        with db.scrape_job_lease("campaign_refresh") as duplicate:
            assert duplicate is None
        # Different scheduled work is retained; no shared proxy gate drops it.
        with db.scrape_job_lease("internal_scrape") as independent:
            assert independent is not None
            independent.assert_held()

    assert engine.shared["owners"] == {}
    assert all(connection.closed for connection in engine.connections)


def test_postgres_job_lease_releases_after_exception(monkeypatch):
    engine = _FakePostgresEngine()
    monkeypatch.setattr(db, "_engine", engine)

    with pytest.raises(ValueError):
        with db.scrape_job_lease("campaign_refresh"):
            raise ValueError("scrape failed")
    with db.scrape_job_lease("campaign_refresh") as retry:
        assert retry is not None


def test_postgres_lock_session_change_fails_closed(monkeypatch):
    engine = _FakePostgresEngine()
    monkeypatch.setattr(db, "_engine", engine)

    with db.scrape_job_lease("campaign_refresh") as lease:
        lease.connection.pid = 9999
        with pytest.raises(db.ScrapeJobLockLost, match="session changed"):
            lease.assert_held()


def test_local_file_lock_rejects_second_process(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db.tempfile, "tempdir", str(tmp_path))
    code = (
        "from campaign_manager import db; "
        "ctx = db.scrape_job_lease('campaign_refresh'); "
        "lease = ctx.__enter__(); "
        "print('busy' if lease is None else 'acquired'); "
        "ctx.__exit__(None, None, None)"
    )
    env = dict(os.environ, TMPDIR=str(tmp_path))
    with db.scrape_job_lease("campaign_refresh") as lease:
        assert lease is not None
        other = subprocess.run(
            [sys.executable, "-c", code], cwd=os.getcwd(), env=env,
            capture_output=True, text=True, timeout=10, check=True,
        )
        assert other.stdout.strip() == "busy"
    after = subprocess.run(
        [sys.executable, "-c", code], cwd=os.getcwd(), env=env,
        capture_output=True, text=True, timeout=10, check=True,
    )
    assert after.stdout.strip() == "acquired"


def test_all_job_entrypoints_share_body_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db.tempfile, "tempdir", str(tmp_path))
    entered = threading.Event()
    release = threading.Event()
    calls = []
    monkeypatch.setattr(db, "create_cron_log", lambda _job, status: 70)
    monkeypatch.setattr(db, "transition_cron_log", lambda *_args: True)

    def refresh(_slugs, _progress, lease, request_log_id=None):
        calls.append("campaign_refresh")
        entered.set()
        assert release.wait(5)
        lease.assert_held()
        return {"status": "completed"}

    monkeypatch.setattr(scheduler, "_run_campaign_refresh", refresh)
    monkeypatch.setattr(
        scheduler, "_run_internal_scrape",
        lambda lease, request_log_id=None: {"status": "completed"},
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(scheduler.run_campaign_refresh)
        assert entered.wait(5)
        assert scheduler.trigger_job("campaign_refresh") == {
            "status": "skipped", "summary": {"reason": "already_running"}
        }
        assert scheduler.run_campaign_refresh(only_slugs=["one"]) == {
            "status": "skipped", "summary": {"reason": "already_running"}
        }
        other = pool.submit(scheduler.run_internal_scrape)
        release.set()
        assert first.result(timeout=5) == {"status": "completed"}
        assert other.result(timeout=5) == {"status": "completed"}
    assert calls == ["campaign_refresh"]


def test_campaign_lock_service_failure_never_runs_body(monkeypatch):
    class BrokenEngine(_FakePostgresEngine):
        def connect(self):
            raise ConnectionError("database unavailable")

    monkeypatch.setattr(db, "_engine", BrokenEngine())
    monkeypatch.setattr(
        scheduler, "_run_campaign_refresh",
        lambda *_args: pytest.fail("job body must not run without lock"),
    )
    result = scheduler.run_campaign_refresh()
    assert result["status"] == "failed"
    assert result["summary"]["error"] == "scrape job lock unavailable"

def test_duplicate_manual_receipt_links_active_run(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(db, "active_cron_log_id", lambda _job: 91)
    transitions = []
    monkeypatch.setattr(
        db, "transition_cron_log",
        lambda *args: transitions.append(args) or True,
    )
    monkeypatch.setattr(
        scheduler, "_run_campaign_refresh",
        lambda *_args: pytest.fail("duplicate must not enter job body"),
    )
    with db.scrape_job_lease("campaign_refresh"):
        result = scheduler.trigger_job("campaign_refresh", 42)
    assert result == {
        "status": "skipped",
        "summary": {"reason": "already_running", "active_log_id": 91},
    }
    assert transitions == [(
        42, "queued", "skipped",
        {"reason": "already_running", "active_log_id": 91},
    )]


def test_lock_outage_marks_accepted_request_failed(monkeypatch):
    class BrokenEngine(_FakePostgresEngine):
        def connect(self):
            raise ConnectionError("database unavailable")

    monkeypatch.setattr(db, "_engine", BrokenEngine())
    transitions = []
    monkeypatch.setattr(
        db, "transition_cron_log",
        lambda *args: transitions.append(args) or True,
    )
    monkeypatch.setattr(
        scheduler, "_run_campaign_refresh",
        lambda *_args: pytest.fail("job body must not run"),
    )
    result = scheduler.trigger_job("campaign_refresh", 42)
    assert result["status"] == "failed"
    assert transitions == [
        (42, "queued", "failed", {"error": "scrape job lock unavailable"})
    ]


def test_on_demand_trigger_distinguishes_duplicate_from_completed(monkeypatch):
    from campaign_manager.services import scrape_trigger

    job_id = "duplicate-job"
    with scrape_trigger._jobs_lock:
        scrape_trigger._jobs.clear()
        scrape_trigger._jobs[job_id] = {
            "state": "running", "scope": "all_active", "started_at": "2026-10-07T12:00:00"
        }
    monkeypatch.setattr(
        scheduler, "run_campaign_refresh",
        lambda **_kwargs: {
            "status": "skipped", "summary": {"reason": "already_running"}
        },
    )
    scrape_trigger._run(job_id, None)
    status = scrape_trigger.job_status(job_id)
    assert status["state"] == "skipped"
    assert status["result"]["status"] == "skipped"
    assert scrape_trigger.active_job() is None
    with scrape_trigger._jobs_lock:
        scrape_trigger._jobs.clear()


def test_cron_api_returns_accepted_receipt_not_execution_claim(monkeypatch):
    from flask import Flask
    from campaign_manager.blueprints import cron
    from campaign_manager.services import local_agent

    app = Flask(__name__)
    app.register_blueprint(cron.cron_bp)
    monkeypatch.setattr(local_agent, "is_configured", lambda: False)
    monkeypatch.setattr(db, "create_cron_log", lambda _job, status: 71 if status == "queued" else None)
    monkeypatch.setattr(
        db, "get_cron_log_by_id",
        lambda log_id: {"id": log_id, "status": "queued"},
    )
    launched = []

    class Thread:
        def __init__(self, *, target, args, daemon):
            launched.append((target, args, daemon))

        def start(self):
            pass

    monkeypatch.setattr(cron.threading, "Thread", Thread)
    client = app.test_client()
    response = client.post("/api/cron/trigger", json={"job_type": "internal_scrape"})
    assert response.status_code == 202
    assert response.get_json() == {
        "status": "accepted", "job_type": "internal_scrape", "log_id": 71
    }
    assert launched == [(cron.trigger_job, ("internal_scrape", 71), True)]
    assert client.get("/api/cron/logs/71").get_json()["status"] == "queued"


def test_cron_api_thread_start_failure_closes_receipt(monkeypatch):
    from flask import Flask
    from campaign_manager.blueprints import cron
    from campaign_manager.services import local_agent

    app = Flask(__name__)
    app.register_blueprint(cron.cron_bp)
    monkeypatch.setattr(local_agent, "is_configured", lambda: False)
    monkeypatch.setattr(db, "create_cron_log", lambda _job, status: 72)
    transitions = []
    monkeypatch.setattr(
        db, "transition_cron_log",
        lambda *args: transitions.append(args) or True,
    )

    class Thread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(cron.threading, "Thread", Thread)
    response = app.test_client().post(
        "/api/cron/trigger", json={"job_type": "internal_scrape"}
    )
    assert response.status_code == 503
    assert response.get_json()["log_id"] == 72
    assert transitions == [(
        72, "queued", "failed", {"error": "Could not start cron worker"}
    )]


def test_distinct_job_waits_for_shared_capacity(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(db, "create_cron_log", lambda _job, status: 80)
    monkeypatch.setattr(db, "transition_cron_log", lambda *_args: True)
    monkeypatch.setattr(scheduler, "CAPACITY_WAIT_SECONDS", 3)
    entered = threading.Event()
    release = threading.Event()
    internal_entered = threading.Event()

    def refresh(_slugs, _progress, lease, request_log_id=None):
        entered.set()
        assert release.wait(5)
        lease.assert_held()
        return {"status": "completed"}

    def internal(lease, request_log_id=None):
        internal_entered.set()
        lease.assert_held()
        return {"status": "completed"}

    monkeypatch.setattr(scheduler, "_run_campaign_refresh", refresh)
    monkeypatch.setattr(scheduler, "_run_internal_scrape", internal)
    with ThreadPoolExecutor(max_workers=2) as pool:
        campaign = pool.submit(scheduler.run_campaign_refresh)
        assert entered.wait(5)
        other = pool.submit(scheduler.run_internal_scrape)
        assert not internal_entered.wait(0.2)
        release.set()
        assert campaign.result(timeout=5)["status"] == "completed"
        assert other.result(timeout=5)["status"] == "completed"
    assert internal_entered.is_set()


def test_capacity_timeout_fails_queued_receipt_without_running(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(scheduler, "CAPACITY_WAIT_SECONDS", 0.05)
    transitions = []
    monkeypatch.setattr(db, "transition_cron_log",
                        lambda *args: transitions.append(args) or True)
    monkeypatch.setattr(scheduler, "_run_internal_scrape",
                        lambda *_args: pytest.fail("capacity wait must not run body"))
    with db.scrape_job_lease("scrape_capacity"):
        result = scheduler.run_internal_scrape(request_log_id=84)
    assert result["status"] == "failed"
    assert "capacity wait expired" in result["summary"]["error"]
    assert transitions == [(84, "queued", "failed", {
        "error": "shared scrape capacity wait expired"
    })]


@pytest.mark.parametrize("dispatch,state,code", [
    ({"ok": True, "node": {"started": True}}, "delegated", 202),
    ({"ok": True, "node": {"started": False, "note": "scrape already running"}}, "skipped", 200),
    ({"ok": False, "outcome": "unknown", "error": "reconcile"}, "unknown", 502),
    ({"ok": False, "error": "refused"}, "failed", 502),
])
def test_local_delegation_has_durable_receipt(monkeypatch, dispatch, state, code):
    from flask import Flask
    from campaign_manager.blueprints import cron
    from campaign_manager.services import local_agent

    app = Flask(__name__)
    app.register_blueprint(cron.cron_bp)
    monkeypatch.setattr(local_agent, "is_configured", lambda: True)
    monkeypatch.setattr(local_agent, "dispatch_scrape", lambda _scope: dispatch)
    monkeypatch.setattr(db, "create_cron_log",
                        lambda _job, status: 91 if status == "queued" else None)
    transitions = []
    monkeypatch.setattr(db, "transition_cron_log",
                        lambda *args: transitions.append(args) or True)
    response = app.test_client().post(
        "/api/cron/trigger", json={"job_type": "campaign_refresh"}
    )
    assert response.status_code == code
    assert response.get_json()["log_id"] == 91
    assert transitions[0][:3] == (91, "queued", state)


def test_local_delegation_refuses_post_without_receipt(monkeypatch):
    from flask import Flask
    from campaign_manager.blueprints import cron
    from campaign_manager.services import local_agent

    app = Flask(__name__)
    app.register_blueprint(cron.cron_bp)
    monkeypatch.setattr(local_agent, "is_configured", lambda: True)
    monkeypatch.setattr(db, "create_cron_log",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("DB down")))
    monkeypatch.setattr(local_agent, "dispatch_scrape",
                        lambda *_args: pytest.fail("must not send POST"))
    response = app.test_client().post(
        "/api/cron/trigger", json={"job_type": "campaign_refresh"}
    )
    assert response.status_code == 503


def test_real_postgres_shared_capacity_across_connections(monkeypatch):
    """Opt-in integration check against a disposable PostgreSQL instance."""
    url = os.environ.get("TEST_POSTGRES_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_POSTGRES_DATABASE_URL for real PostgreSQL lock test")
    from sqlalchemy import create_engine

    engine = create_engine(url, pool_size=3)
    monkeypatch.setattr(db, "_engine", engine)
    try:
        with db.scrape_job_lease("campaign_refresh") as campaign:
            assert campaign is not None
            with db.scrape_job_lease("scrape_capacity") as capacity:
                assert capacity is not None
                assert db.scrape_job_lock_held("scrape_capacity")
                with db.scrape_job_lease("internal_scrape") as internal:
                    assert internal is not None
                    with db.scrape_job_lease("scrape_capacity") as busy:
                        assert busy is None
                    internal.assert_held()
                capacity.assert_held()
        assert not db.scrape_job_lock_held("scrape_capacity")
    finally:
        engine.dispose()
