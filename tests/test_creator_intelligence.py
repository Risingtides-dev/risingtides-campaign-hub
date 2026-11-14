"""Regression tests for Creator Intelligence — CAMP-285.

Covers:
  - shared-sound campaign rounds (list_sounds returns one entry per campaign slug)
  - exact campaign selection via sound_fit(campaign_slug=...) and backward compat
  - creator identity normalization (@Handle / handle / HANDLE → one row)
  - dismissed row exclusion
  - no-data / empty-DB behaviour
  - API endpoint smoke (breakers, sounds, sound-fit, creator drilldown)

All tests run against in-memory SQLite; no live scraping, Cobrand, or production writes.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "")

import pytest
from flask import Flask
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from campaign_manager import db as _db
from campaign_manager.models import Base, Campaign, MatchedVideo


# ---------------------------------------------------------------------------
# SQLite compat shims (mirror conftest.py)
# ---------------------------------------------------------------------------

@compiles(JSONB, "sqlite")
def _jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


@compiles(UUID, "sqlite")
def _uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(36)"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_intel_app():
    from campaign_manager.blueprints.creator_intelligence import creator_intelligence_bp
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(creator_intelligence_bp)
    return app


@pytest.fixture()
def intel_app():
    flask_app = _make_intel_app()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    _db._engine = engine
    _db._SessionLocal = sessionmaker(bind=engine)
    yield flask_app
    _db._engine = None
    _db._SessionLocal = None


@pytest.fixture()
def intel_client(intel_app):
    return intel_app.test_client()


@pytest.fixture()
def session(intel_app):
    with _db.get_session() as s:
        yield s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _campaign(slug, sound_id="sid1", artist="Artist", song="Song", title=None):
    return Campaign(
        slug=slug,
        title=title or slug,
        artist=artist,
        song=song,
        sound_id=sound_id,
        start_date="2026-01-01",
    )


def _video(campaign_id, account, views, extracted_sound_id="sid1", dismissed=False):
    from datetime import datetime
    return MatchedVideo(
        campaign_id=campaign_id,
        url=f"https://tiktok.com/@x/video/{account}-{views}",
        account=account,
        views=views,
        extracted_sound_id=extracted_sound_id,
        dismissed_at=datetime(2026, 1, 1) if dismissed else None,
    )


# ---------------------------------------------------------------------------
# list_sounds — shared-sound rounds
# ---------------------------------------------------------------------------

class TestListSounds:
    def test_single_campaign(self, session):
        from campaign_manager.services.creator_intelligence import list_sounds
        session.add(_campaign("camp-a", sound_id="s1"))
        session.commit()

        sounds = list_sounds(session)
        assert len(sounds) == 1
        assert sounds[0]["campaign_slug"] == "camp-a"
        assert sounds[0]["sound_id"] == "s1"

    def test_two_rounds_same_sound_both_appear(self, session):
        """Campaigns that share a sound_id must each appear as a distinct entry."""
        from campaign_manager.services.creator_intelligence import list_sounds
        session.add(_campaign("round-1", sound_id="shared", title="Round 1"))
        session.add(_campaign("round-2", sound_id="shared", title="Round 2"))
        session.commit()

        sounds = list_sounds(session)
        slugs = {s["campaign_slug"] for s in sounds}
        assert "round-1" in slugs
        assert "round-2" in slugs
        assert len(sounds) == 2

    def test_includes_campaign_title(self, session):
        from campaign_manager.services.creator_intelligence import list_sounds
        session.add(_campaign("camp-b", sound_id="s2", title="My Campaign"))
        session.commit()

        sounds = list_sounds(session)
        assert sounds[0]["campaign_title"] == "My Campaign"

    def test_empty_sound_id_excluded(self, session):
        from campaign_manager.services.creator_intelligence import list_sounds
        session.add(Campaign(slug="no-sound", title="No Sound", sound_id=""))
        session.commit()

        assert list_sounds(session) == []

    def test_post_count_from_dismissed_rows_excluded(self, session):
        """Dismissed MatchedVideo rows must not inflate post_count."""
        from campaign_manager.services.creator_intelligence import list_sounds
        camp = _campaign("camp-c", sound_id="s3")
        session.add(camp)
        session.commit()

        # 2 valid, 1 dismissed
        session.add(_video(camp.id, "@creator", 100_000, extracted_sound_id="s3"))
        session.add(_video(camp.id, "@creator2", 200_000, extracted_sound_id="s3"))
        session.add(_video(camp.id, "@creator3", 50_000, extracted_sound_id="s3", dismissed=True))
        session.commit()

        sounds = list_sounds(session)
        assert sounds[0]["post_count"] == 2


# ---------------------------------------------------------------------------
# sound_fit — campaign_slug selection
# ---------------------------------------------------------------------------

class TestSoundFit:
    def test_no_slug_returns_first_matching(self, session):
        from campaign_manager.services.creator_intelligence import sound_fit
        session.add(_campaign("camp-a", sound_id="s1"))
        session.commit()

        result = sound_fit(session, "s1")
        assert result is not None
        assert result["campaign_slug"] == "camp-a"

    def test_specific_slug_returns_that_campaign(self, session):
        """With campaign_slug, must return that specific round."""
        from campaign_manager.services.creator_intelligence import sound_fit
        session.add(_campaign("round-1", sound_id="shared", title="Round One"))
        session.add(_campaign("round-2", sound_id="shared", title="Round Two"))
        session.commit()

        r1 = sound_fit(session, "shared", campaign_slug="round-1")
        assert r1 is not None
        assert r1["campaign_slug"] == "round-1"

        r2 = sound_fit(session, "shared", campaign_slug="round-2")
        assert r2 is not None
        assert r2["campaign_slug"] == "round-2"

    def test_wrong_campaign_slug_returns_none(self, session):
        """campaign_slug that doesn't own the sound_id → None (404 signal)."""
        from campaign_manager.services.creator_intelligence import sound_fit
        session.add(_campaign("camp-a", sound_id="s1"))
        session.add(_campaign("camp-b", sound_id="s2"))
        session.commit()

        # camp-b exists but owns s2, not s1.
        assert sound_fit(session, "s1", campaign_slug="camp-b") is None

    def test_nonexistent_sound_returns_none(self, session):
        from campaign_manager.services.creator_intelligence import sound_fit
        assert sound_fit(session, "nope") is None

    def test_includes_campaign_title(self, session):
        from campaign_manager.services.creator_intelligence import sound_fit
        session.add(_campaign("camp-t", sound_id="s1", title="My Round"))
        session.commit()

        result = sound_fit(session, "s1")
        assert result["campaign_title"] == "My Round"

    def test_backward_compat_no_slug(self, session):
        """Existing callers that omit campaign_slug still get a result."""
        from campaign_manager.services.creator_intelligence import sound_fit
        session.add(_campaign("camp-compat", sound_id="sX"))
        session.commit()

        result = sound_fit(session, "sX")
        assert result is not None


# ---------------------------------------------------------------------------
# Creator identity normalization
# ---------------------------------------------------------------------------

class TestIdentityNormalization:
    def _seed_variants(self, session, views_by_variant: dict[str, int], sound_id="s1"):
        """Seed one campaign and videos for multiple account-name variants."""
        camp = _campaign("camp-norm", sound_id=sound_id)
        session.add(camp)
        session.commit()
        for acct, views in views_by_variant.items():
            session.add(_video(camp.id, acct, views, extracted_sound_id=sound_id))
        session.commit()

    def test_at_handle_and_bare_handle_merge(self, session):
        """@Handle and handle must count as one creator in the leaderboard."""
        from campaign_manager.services.creator_intelligence import breaker_leaderboard
        # 6 posts total (>= MIN_POSTS=5), split across two name variants
        self._seed_variants(session, {
            "@creator": 600_000,
            "@creator": 600_001,  # duplicate key; Python dict keeps last
        })
        # Use distinct URL-based inserts
        camp_id = session.query(Campaign).filter_by(slug="camp-norm").first().id
        from datetime import datetime
        for i, (acct, views) in enumerate([
            ("@Creator", 700_000),
            ("creator", 500_000),
            ("CREATOR", 600_000),
            ("  @creator  ", 400_000),
            ("@creator", 1_100_000),
        ]):
            session.add(MatchedVideo(
                campaign_id=camp_id,
                url=f"https://tiktok.com/@x/video/norm-{i}",
                account=acct,
                views=views,
                extracted_sound_id="s1",
            ))
        session.commit()

        rows = breaker_leaderboard(session, lens="balanced", min_posts=1)
        # Must collapse to one row regardless of case/@ variants
        accounts = [r["account"] for r in rows]
        # Only one unique normalized creator
        assert len(accounts) == 1
        assert accounts[0] == "@creator"

    def test_case_normalization_post_count(self, session):
        """Posts from all case variants are counted together."""
        from campaign_manager.services.creator_intelligence import breaker_leaderboard
        camp = _campaign("camp-case", sound_id="s2")
        session.add(camp)
        session.commit()
        camp_id = camp.id
        variants = ["@Alice", "alice", "ALICE", "@ALICE", "Alice"]
        for i, acct in enumerate(variants):
            session.add(MatchedVideo(
                campaign_id=camp_id,
                url=f"https://tiktok.com/@x/video/case-{i}",
                account=acct,
                views=100_000,
                extracted_sound_id="s2",
            ))
        session.commit()

        rows = breaker_leaderboard(session, lens="balanced", min_posts=1)
        assert len(rows) == 1
        assert rows[0]["posts"] == 5
        assert rows[0]["account"] == "@alice"

    def test_drilldown_case_insensitive(self, session):
        """creator_drilldown resolves @Handle == handle == HANDLE."""
        from campaign_manager.services.creator_intelligence import creator_drilldown
        camp = _campaign("camp-dd", sound_id="s3")
        session.add(camp)
        session.commit()
        camp_id = camp.id
        # Store as uppercase with @
        session.add(MatchedVideo(
            campaign_id=camp_id,
            url="https://tiktok.com/@x/video/dd-1",
            account="@DRILLDOWN",
            views=800_000,
            extracted_sound_id="s3",
        ))
        session.commit()

        # Lookup with lowercase, no @
        result = creator_drilldown(session, "drilldown")
        assert result is not None
        assert result["account"] == "@drilldown"
        assert result["posts"] == 1

    def test_drilldown_missing_creator_returns_none(self, session):
        from campaign_manager.services.creator_intelligence import creator_drilldown
        # No data seeded
        assert creator_drilldown(session, "nobody") is None

    def test_dismissed_rows_excluded_from_leaderboard(self, session):
        """Dismissed videos must not count toward the leaderboard."""
        from campaign_manager.services.creator_intelligence import breaker_leaderboard
        camp = _campaign("camp-dis", sound_id="s4")
        session.add(camp)
        session.commit()
        camp_id = camp.id
        from datetime import datetime
        # 3 valid + 10 dismissed (would qualify if dismissed counted)
        for i in range(3):
            session.add(MatchedVideo(
                campaign_id=camp_id,
                url=f"https://tiktok.com/@x/video/valid-{i}",
                account="@creator",
                views=600_000,
                extracted_sound_id="s4",
            ))
        for i in range(10):
            session.add(MatchedVideo(
                campaign_id=camp_id,
                url=f"https://tiktok.com/@x/video/dis-{i}",
                account="@creator",
                views=1_200_000,
                dismissed_at=datetime(2026, 1, 1),
                extracted_sound_id="s4",
            ))
        session.commit()

        rows = breaker_leaderboard(session, lens="balanced", min_posts=5)
        # Only 3 valid posts < min_posts=5 → no results
        assert rows == []

        rows = breaker_leaderboard(session, lens="balanced", min_posts=1)
        assert rows[0]["posts"] == 3


# ---------------------------------------------------------------------------
# Empty / no-data safety
# ---------------------------------------------------------------------------

class TestNoData:
    def test_leaderboard_empty_db(self, session):
        from campaign_manager.services.creator_intelligence import breaker_leaderboard
        assert breaker_leaderboard(session) == []

    def test_sounds_empty_db(self, session):
        from campaign_manager.services.creator_intelligence import list_sounds
        assert list_sounds(session) == []

    def test_rebook_empty_db(self, session):
        from campaign_manager.services.creator_intelligence import rebook_suggestions
        assert rebook_suggestions(session) == []


# ---------------------------------------------------------------------------
# API endpoint smoke tests
# ---------------------------------------------------------------------------

class TestAPIEndpoints:
    def test_breakers_200_empty(self, intel_client):
        resp = intel_client.get("/api/intelligence/breakers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["breakers"] == []
        assert data["lens"] == "balanced"

    def test_sounds_200_empty(self, intel_client):
        resp = intel_client.get("/api/intelligence/sounds")
        assert resp.status_code == 200
        assert resp.get_json()["sounds"] == []

    def test_sound_fit_404_on_missing(self, intel_client):
        resp = intel_client.get("/api/intelligence/sound-fit/does-not-exist")
        assert resp.status_code == 404

    def test_sound_fit_404_wrong_campaign(self, intel_client, intel_app):
        # Seed one campaign with sound s1
        engine = _db._engine
        with _db.get_session() as s:
            s.add(_campaign("real-camp", sound_id="s1"))
            s.commit()

        # Request sound s1 but restricted to a non-owning campaign slug → 404
        resp = intel_client.get("/api/intelligence/sound-fit/s1?campaign=other-camp")
        assert resp.status_code == 404

    def test_sound_fit_200_with_matching_campaign(self, intel_client):
        with _db.get_session() as s:
            s.add(_campaign("fit-camp", sound_id="s_fit"))
            s.commit()

        resp = intel_client.get("/api/intelligence/sound-fit/s_fit?campaign=fit-camp")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["campaign_slug"] == "fit-camp"
        assert data["campaign_title"] == "fit-camp"

    def test_sounds_includes_both_rounds(self, intel_client):
        """Two campaigns sharing a sound → two entries in /sounds."""
        with _db.get_session() as s:
            s.add(_campaign("r1", sound_id="shared_s"))
            s.add(_campaign("r2", sound_id="shared_s"))
            s.commit()

        resp = intel_client.get("/api/intelligence/sounds")
        assert resp.status_code == 200
        slugs = {item["campaign_slug"] for item in resp.get_json()["sounds"]}
        assert "r1" in slugs
        assert "r2" in slugs

    def test_creator_drilldown_404(self, intel_client):
        resp = intel_client.get("/api/intelligence/creator/unknown_ghost")
        assert resp.status_code == 404

    def test_creator_drilldown_case_insensitive(self, intel_client):
        """Drilldown by lowercase name must find a creator stored as @UPPER."""
        with _db.get_session() as s:
            camp = _campaign("dd-camp", sound_id="s_dd")
            s.add(camp)
            s.commit()
            for i in range(1):
                s.add(MatchedVideo(
                    campaign_id=camp.id,
                    url=f"https://tiktok.com/@x/video/dd-api-{i}",
                    account="@UPPERCASE",
                    views=1_000_000,
                    extracted_sound_id="s_dd",
                ))
            s.commit()

        resp = intel_client.get("/api/intelligence/creator/uppercase")
        assert resp.status_code == 200
        assert resp.get_json()["account"] == "@uppercase"

    def test_rebook_suggestions_200(self, intel_client):
        resp = intel_client.get("/api/intelligence/rebook-suggestions")
        assert resp.status_code == 200
        assert "suggestions" in resp.get_json()
