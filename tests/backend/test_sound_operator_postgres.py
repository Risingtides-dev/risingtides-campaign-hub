"""Disposable PostgreSQL coverage for the cross-worker operator login limit.

Set TEST_POSTGRES_DATABASE_URL to a disposable database. Every run creates and
removes its own schema; it never writes into the URL's default schema.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os
import uuid

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from campaign_manager import db
from campaign_manager.models import SoundOperatorLoginState


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

    def attempt(password="wrong"):
        with app.test_client() as client:
            return client.post("/api/sound-assignments/login", json={"password": password},
                               headers={"Origin": "http://localhost"}).status_code

    for _ in range(8):
        assert attempt() == 401

    start = Barrier(3)

    def concurrent_attempt():
        start.wait(timeout=10)
        return attempt()

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(concurrent_attempt)
        second = workers.submit(concurrent_attempt)
        start.wait(timeout=10)
        assert sorted((first.result(timeout=10), second.result(timeout=10))) == [401, 429]

    with postgres_login_state.connect() as conn:
        assert conn.execute(text("SELECT failed_count FROM sound_operator_login_state WHERE id = 1")).scalar_one() == 10
    assert attempt("synthetic-operator-password-0123456789") == 429

    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.time.time", lambda: 1301)
    assert attempt("synthetic-operator-password-0123456789") == 200
    with postgres_login_state.connect() as conn:
        assert conn.execute(text("SELECT failed_count FROM sound_operator_login_state WHERE id = 1")).scalar_one() == 0
