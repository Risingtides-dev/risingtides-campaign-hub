"""Test fixtures.

Spins up the Flask app against an in-memory SQLite DB. Production runs
on Postgres — the manual ALTER TABLE migrations in `db.init` are
Postgres-only, so tests bypass `db.init` entirely and use
`Base.metadata.create_all` directly. JSONB columns from the
`sqlalchemy.dialects.postgresql` import are compiled to JSON for SQLite
via a dialect-specific compile rule registered before any engine is
created.
"""
from __future__ import annotations

import os

# Ensure the app factory doesn't try to talk to a real database when
# imported. Set before importing campaign_manager.
os.environ.setdefault("DATABASE_URL", "")

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    # JSONB is Postgres-only; SQLite gets the generic JSON column type.
    # Bind/value handling still works because SQLAlchemy serializes
    # Python lists/dicts to JSON text for either backend.
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(_type, _compiler, **_kw):
    # SQLite only auto-increments columns typed exactly "INTEGER PRIMARY
    # KEY" (rowid alias). BIGINT primary keys silently break autoincrement
    # and surface as "NOT NULL constraint failed: <table>.id". Map
    # BigInteger -> INTEGER for SQLite so models that use BigInteger PKs
    # (e.g. NotionSyncLog, InternalVideoGroupAttribution) work in tests.
    return "INTEGER"


@compiles(UUID, "sqlite")
def _uuid_as_char_on_sqlite(_type, _compiler, **_kw):
    # The Postgres UUID dialect type relies on libpq's binary UUID binding.
    # On SQLite the round-trip surfaces as 'AttributeError: float object
    # has no attribute replace' when SQLAlchemy tries to reconstruct a
    # uuid.UUID from the returned cell. Mapping UUID -> CHAR(36) lets
    # values round-trip as hyphenated strings; as_uuid=True still coerces
    # back to UUID on read. Needed for NotionMasterPage tests (RTA-8).
    return "CHAR(36)"


from flask import Flask  # noqa: E402

from campaign_manager import db  # noqa: E402
from campaign_manager.models import Base, Campaign, MatchedVideo  # noqa: E402


def _build_test_app():
    """Minimal Flask app for smoke tests.

    The full `create_app` factory imports the entire blueprint surface,
    which transitively requires apscheduler/yt-dlp/slack-bolt/anthropic
    and friends. Smoke tests only need the scrape_tasks endpoints, so
    we register that blueprint directly and skip the rest.
    """
    from campaign_manager.blueprints.scrape_tasks import scrape_tasks_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(scrape_tasks_bp)
    return app


@pytest.fixture
def app():
    flask_app = _build_test_app()

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db._engine = engine
    db._SessionLocal = sessionmaker(bind=engine)

    yield flask_app

    db._engine = None
    db._SessionLocal = None


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_campaign(app):
    """Seed an active campaign with three untracked matched videos.

    Returns the slug + ordered list of MatchedVideo ids so individual
    tests can dismiss/track specific rows.
    """
    with db.get_session() as s:
        camp = Campaign(
            slug="test-campaign",
            title="Test Campaign",
            artist="Test Artist",
            song="Test Song",
        )
        s.add(camp)
        s.commit()
        camp_id = camp.id

        for i in range(3):
            s.add(
                MatchedVideo(
                    campaign_id=camp_id,
                    url=f"https://www.tiktok.com/@user{i}/video/{i}",
                    account=f"@user{i}",
                    views=1000 * (i + 1),
                    likes=100 * (i + 1),
                    match_strategy="sound_id",
                )
            )
        s.commit()

        ids = [
            v.id
            for v in s.query(MatchedVideo)
            .filter_by(campaign_id=camp_id)
            .order_by(MatchedVideo.id)
            .all()
        ]

    return {"slug": "test-campaign", "campaign_id": camp_id, "video_ids": ids}
