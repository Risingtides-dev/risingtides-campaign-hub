"""Pytest fixtures for the backend test suite.

Provides:
  - A per-test in-memory SQLite engine wired into ``campaign_manager.db``.
  - A Flask test client built from the full ``create_app`` factory.

JSONB → JSON translation for SQLite is handled by the outer
``tests/conftest.py`` (registered there as a SQLAlchemy compile hook),
which pytest loads before this file.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Make sure the app factory doesn't try to talk to a real database.
os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("CORS_ORIGINS", "http://localhost")

from campaign_manager import create_app, db as _db  # noqa: E402
from campaign_manager.models import Base  # noqa: E402


@pytest.fixture
def engine():
    """A fresh in-memory SQLite engine for each test."""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine):
    """Wire the campaign_manager.db module to use the test engine."""
    prev_engine = _db._engine
    prev_session = _db._SessionLocal
    _db._engine = engine
    _db._SessionLocal = sessionmaker(bind=engine)
    yield _db
    _db._engine = prev_engine
    _db._SessionLocal = prev_session


@pytest.fixture
def app(db):
    """Build a Flask app pointed at the in-memory database.

    ``create_app`` will try to init the DB itself; we pass an empty
    DATABASE_URL so it no-ops, then keep our pre-wired session.
    """
    app = create_app({
        "DATABASE_URL": "",
        "CORS_ORIGINS": ["http://localhost"],
        "SCHEDULER_ENABLED": False,
        "TESTING": True,
    })
    # create_app may have nulled _engine via its init() call — re-wire.
    _db._engine = db._engine
    _db._SessionLocal = db._SessionLocal
    return app


@pytest.fixture
def client(app):
    return app.test_client()
