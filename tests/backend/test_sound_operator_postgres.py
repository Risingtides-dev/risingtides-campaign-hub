"""Disposable PostgreSQL coverage for the cross-worker operator login limit.

Set TEST_POSTGRES_DATABASE_URL to a disposable database. Every run creates and
removes its own schema; it never writes into the URL's default schema.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import Event, local
import os
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from campaign_manager import db
from campaign_manager.models import SoundOperatorLoginState
from campaign_manager.blueprints.sound_assignments import prune_sound_operator_login_state


@pytest.fixture
def postgres_login_state(app, monkeypatch):
    url = os.environ.get("TEST_POSTGRES_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_POSTGRES_DATABASE_URL for PostgreSQL login concurrency")

    schema = f"sound_operator_{uuid.uuid4().hex[:16]}"
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, pool_size=4, max_overflow=0)

    @event.listens_for(engine, "checkout")
    def set_test_search_path(connection, _record, _proxy):
        cursor = connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()

    old_engine, old_session = db._engine, db._SessionLocal
    try:
        # This is the same first-run additive table creation used at startup.
        SoundOperatorLoginState.__table__.create(engine, checkfirst=True)
        db._engine = engine
        db._SessionLocal = sessionmaker(bind=engine)
        monkeypatch.setenv("HUB_WRITE_KEY", "synthetic-hub-key")
        monkeypatch.setenv("SOUND_ASSIGNMENTS_OPERATOR_PASSWORD", "synthetic-operator-password-0123456789")
        app.config["CONTENT_LAB_HUB_API_KEY"] = "synthetic-lab-key"
        yield engine
    finally:
        db._engine, db._SessionLocal = old_engine, old_session
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_concurrent_workers_share_limit_without_lost_attempts(app, postgres_login_state, monkeypatch):
    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.time.time", lambda: 1000)

    def attempt(password="wrong", source="198.51.100.10"):
        with app.test_client() as client:
            return client.post("/api/sound-assignments/login", json={"password": password},
                               headers={"Origin": "http://localhost"},
                               environ_overrides={"REMOTE_ADDR": source}).status_code

    for _ in range(8):
        assert attempt() == 401

    # Pause the first worker only after PostgreSQL has granted its row lock.
    # The second worker must reach SELECT FOR UPDATE and remain blocked until
    # the first transaction is allowed to commit; an HTTP start barrier alone
    # can accidentally serialize even when the implementation has no lock.
    role = local()
    first_has_lock = Event()
    second_select_started = Event()
    release_first = Event()

    def is_lock_select(statement):
        return "sound_operator_login_state" in statement and "FOR UPDATE" in statement.upper()

    def before_execute(_conn, _cursor, statement, _params, _context, _many):
        if getattr(role, "name", None) == "second" and is_lock_select(statement):
            second_select_started.set()

    def after_execute(_conn, _cursor, statement, _params, _context, _many):
        if getattr(role, "name", None) == "first" and is_lock_select(statement):
            first_has_lock.set()
            if not release_first.wait(timeout=10):
                raise AssertionError("first PostgreSQL lock was not released")

    event.listen(postgres_login_state, "before_cursor_execute", before_execute)
    event.listen(postgres_login_state, "after_cursor_execute", after_execute)
    try:
        def worker(name):
            role.name = name
            return attempt()

        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(worker, "first")
            try:
                assert first_has_lock.wait(timeout=10), "first worker never acquired the row lock"
                second = workers.submit(worker, "second")
                assert second_select_started.wait(timeout=10), "second worker never reached the locked row"
                with pytest.raises(FutureTimeout):
                    second.result(timeout=0.3)
            finally:
                release_first.set()
            assert first.result(timeout=10) == 401
            assert second.result(timeout=10) == 429
    finally:
        event.remove(postgres_login_state, "before_cursor_execute", before_execute)
        event.remove(postgres_login_state, "after_cursor_execute", after_execute)

    with postgres_login_state.connect() as conn:
        assert conn.execute(text("SELECT max(failed_count) FROM sound_operator_login_state")).scalar_one() == 10
    assert attempt("synthetic-operator-password-0123456789") == 429
    # A hostile source's concurrent failures never block a different verified source.
    assert attempt("synthetic-operator-password-0123456789", source="203.0.113.20") == 200
    with postgres_login_state.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sound_operator_login_state")).scalar_one() == 2

    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.time.time", lambda: 1301)
    assert attempt("synthetic-operator-password-0123456789") == 200
    with postgres_login_state.connect() as conn:
        assert conn.execute(text("SELECT max(failed_count) FROM sound_operator_login_state")).scalar_one() == 0


def test_login_janitor_prunes_only_inactive_rows_in_bounded_batches(postgres_login_state):
    now = 100_000
    with db._SessionLocal.begin() as transaction:
        transaction.add_all([
            SoundOperatorLoginState(source_key=f"stale-{i:04}", window_started_at=now - 90_000,
                                    failed_count=1, locked_until=0)
            for i in range(501)
        ])
        transaction.add_all([
            SoundOperatorLoginState(source_key="recent", window_started_at=now - 60,
                                    failed_count=1, locked_until=0),
            SoundOperatorLoginState(source_key="active-lock", window_started_at=now - 90_000,
                                    failed_count=10, locked_until=now + 60),
        ])
    assert prune_sound_operator_login_state(now=now) == 501
    with db._SessionLocal.begin() as transaction:
        assert {row.source_key for row in transaction.query(SoundOperatorLoginState).all()} == {
            "recent", "active-lock"
        }
    assert prune_sound_operator_login_state(now=now + 61) == 1
    assert prune_sound_operator_login_state(now=now + 86_400) == 1


def test_login_janitor_skips_row_locked_by_another_worker(postgres_login_state):
    now = 100_000
    with db._SessionLocal.begin() as transaction:
        transaction.add(SoundOperatorLoginState(source_key="locked-by-login",
                                                window_started_at=now - 90_000,
                                                failed_count=1, locked_until=0))
        transaction.add(SoundOperatorLoginState(source_key="free-stale",
                                                window_started_at=now - 90_000,
                                                failed_count=1, locked_until=0))
    with db._SessionLocal.begin() as login_transaction:
        state = login_transaction.get(SoundOperatorLoginState, "locked-by-login", with_for_update=True)
        assert state is not None
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(prune_sound_operator_login_state, now=now)
            assert future.result(timeout=5) == 1
        # A concurrent login refresh remains safe while cleanup skips its row.
        state.window_started_at = now
        state.failed_count += 1
    with db._SessionLocal.begin() as transaction:
        assert transaction.get(SoundOperatorLoginState, "locked-by-login").failed_count == 2
        assert transaction.get(SoundOperatorLoginState, "free-stale") is None
    assert prune_sound_operator_login_state(now=now) == 0
