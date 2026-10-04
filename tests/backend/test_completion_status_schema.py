"""PostgreSQL regression coverage for the active-campaign schema repair.

Set TEST_POSTGRES_DATABASE_URL to a disposable PostgreSQL database to run the
DDL/data tests. They isolate all objects in a unique schema and always remove
it; no shared or production rows are touched.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
from flask import Flask
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from campaign_manager import db


@pytest.fixture
def postgres_schema(monkeypatch):
    url = os.environ.get("TEST_POSTGRES_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_POSTGRES_DATABASE_URL for PostgreSQL DDL regression tests")
    schema = f"completion_repair_{uuid.uuid4().hex[:16]}"
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_engine(url, pool_size=2, max_overflow=0)

    @event.listens_for(engine, "checkout")
    def set_test_search_path(connection, _record, _proxy):
        cursor = connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()

    old_state = (
        db._engine, db._SessionLocal, db._completion_status_repair_ok,
        db._completion_status_retry_count, db._completion_status_retry_after,
        db._completion_status_verify_after,
    )
    db._engine = engine
    db._SessionLocal = sessionmaker(bind=engine)
    db._completion_status_repair_ok = None
    db._completion_status_retry_count = 0
    db._completion_status_retry_after = 0.0
    db._completion_status_verify_after = 0.0
    try:
        yield engine
    finally:
        (db._engine, db._SessionLocal, db._completion_status_repair_ok,
         db._completion_status_retry_count, db._completion_status_retry_after,
         db._completion_status_verify_after) = old_state
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("preexisting_column", [False, True])
def test_postgres_repair_backfills_rows_and_restores_default(postgres_schema, preexisting_column):
    with postgres_schema.begin() as conn:
        conn.execute(text(
            "CREATE TABLE campaigns (id SERIAL PRIMARY KEY, slug TEXT NOT NULL UNIQUE)"
        ))
        if preexisting_column:
            conn.execute(text("ALTER TABLE campaigns ADD COLUMN completion_status VARCHAR(20)"))
        conn.execute(text("INSERT INTO campaigns (slug) VALUES ('active-a'), ('active-b')"))
        if preexisting_column:
            conn.execute(text(
                "INSERT INTO campaigns (slug, completion_status) "
                "VALUES ('finished', 'completed')"
            ))

    assert db._self_heal_completion_status() is True
    with postgres_schema.connect() as conn:
        rows = conn.execute(text(
            "SELECT slug, completion_status FROM campaigns ORDER BY slug"
        )).all()
        active = conn.execute(text(
            "SELECT slug FROM campaigns WHERE completion_status != 'completed' ORDER BY slug"
        )).scalars().all()
        default = conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'campaigns' "
            "AND column_name = 'completion_status'"
        )).scalar_one()
        version_count = conn.execute(text(
            "SELECT count(*) FROM campaign_schema_migrations "
            "WHERE version = '2026_10_04_campaign_completion_status_v1'"
        )).scalar_one()
    assert {row[0]: row[1] for row in rows} == {
        "active-a": "none", "active-b": "none",
        **({"finished": "completed"} if preexisting_column else {}),
    }
    assert active == ["active-a", "active-b"]
    assert "'none'" in default
    assert version_count == 1


def test_postgres_ddl_failure_marks_health_unready(postgres_schema, monkeypatch):
    with postgres_schema.begin() as conn:
        conn.execute(text("CREATE TABLE campaigns (id SERIAL PRIMARY KEY, slug TEXT NOT NULL)"))

    def fail_repair_ddl(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS completion_status"):
            raise RuntimeError("synthetic DDL failure")

    event.listen(postgres_schema, "before_cursor_execute", fail_repair_ddl)
    try:
        assert db._self_heal_completion_status() is False
    finally:
        event.remove(postgres_schema, "before_cursor_execute", fail_repair_ddl)

    from campaign_manager.blueprints import health
    monkeypatch.setattr(health._db, "is_active", lambda: True)
    app = Flask(__name__)
    with app.app_context():
        response, status = health.health()
    assert status == 503
    assert response.get_json()["ok"] is False
    assert response.get_json()["schema_repair"] == "failed"


def test_transient_postgres_lock_timeout_recovers_readiness_without_restart(
    postgres_schema, monkeypatch,
):
    from campaign_manager.blueprints import health

    with postgres_schema.begin() as conn:
        conn.execute(text("CREATE TABLE campaigns (id SERIAL PRIMARY KEY, slug TEXT NOT NULL)"))
    monkeypatch.setattr(db, "_COMPLETION_STATUS_LOCK_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(db, "_COMPLETION_STATUS_LOCK_POLL_SECONDS", 0.01)
    monkeypatch.setattr(db, "_COMPLETION_STATUS_RETRY_BASE_SECONDS", 0.01)
    monkeypatch.setattr(health._db, "is_active", lambda: True)

    lock_key = 1685289074
    with postgres_schema.connect() as lock_conn:
        lock_conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_key})
        assert db._self_heal_completion_status() is False
        app = Flask(__name__)
        with app.app_context():
            failed_response, failed_status = health.health()
        assert failed_status == 503
        assert failed_response.get_json()["schema_repair"] == "failed"
        lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})

    time.sleep(0.02)
    app = Flask(__name__)
    with app.app_context():
        recovered_response, recovered_status = health.health()
    assert recovered_status == 200
    assert recovered_response.get_json()["schema_repair"] == "ok"
    with postgres_schema.connect() as conn:
        assert conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'campaigns' "
            "AND column_name = 'completion_status'"
        )).scalar_one() is not None


def test_post_success_schema_drift_is_repaired_on_periodic_health_verification(
    postgres_schema, monkeypatch,
):
    from campaign_manager.blueprints import health

    with postgres_schema.begin() as conn:
        conn.execute(text("CREATE TABLE campaigns (id SERIAL PRIMARY KEY, slug TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO campaigns (slug) VALUES ('active')"))
    monkeypatch.setattr(db, "_COMPLETION_STATUS_VERIFY_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(health._db, "is_active", lambda: True)
    assert db._self_heal_completion_status() is True
    with postgres_schema.begin() as conn:
        conn.execute(text("ALTER TABLE campaigns ALTER COLUMN completion_status DROP DEFAULT"))
        conn.execute(text("UPDATE campaigns SET completion_status = NULL"))

    app = Flask(__name__)
    with app.app_context():
        response, status = health.health()
    assert status == 200
    assert response.get_json()["schema_repair"] == "ok"
    with postgres_schema.connect() as conn:
        assert conn.execute(text(
            "SELECT completion_status FROM campaigns WHERE slug = 'active'"
        )).scalar_one() == "none"
        assert "'none'" in conn.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'campaigns' "
            "AND column_name = 'completion_status'"
        )).scalar_one()


def test_scheduler_starts_once_after_schema_repair_recovers(monkeypatch, tmp_path):
    import campaign_manager
    from campaign_manager import create_app
    from campaign_manager import db as app_db
    from campaign_manager.services import scheduler

    starts = []
    lock_path = tmp_path / "scheduler.lock"
    monkeypatch.setattr(campaign_manager, "_SCHEDULER_LOCK_PATH", str(lock_path))
    monkeypatch.setattr(app_db, "init", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(app_db, "is_active", lambda: True)
    ready = {"value": False}
    monkeypatch.setattr(app_db, "completion_status_repair_ok", lambda: ready["value"])
    monkeypatch.setattr(scheduler, "init_scheduler", lambda **kwargs: starts.append(kwargs))
    app = create_app({
        "DATABASE_URL": "postgresql://synthetic.invalid/campaigns",
        "SCHEDULER_ENABLED": True,
        "TESTING": True,
        "SECRET_KEY": "test-secret",
    })
    assert app is not None
    assert starts == []

    ready["value"] = True
    client = app.test_client()
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    assert starts == [{
        "database_url": "postgresql://synthetic.invalid/campaigns",
        "hour": 6,
        "minute": 0,
    }]


def test_readiness_fails_closed_while_expired_schema_verification_is_running():
    old = (db._completion_status_repair_ok, db._completion_status_verify_after)
    try:
        db._completion_status_repair_ok = True
        db._completion_status_verify_after = 0.0
        assert db._completion_status_retry_lock.acquire(blocking=False)
        try:
            assert db.completion_status_repair_ok() is False
        finally:
            db._completion_status_retry_lock.release()
    finally:
        db._completion_status_repair_ok, db._completion_status_verify_after = old
