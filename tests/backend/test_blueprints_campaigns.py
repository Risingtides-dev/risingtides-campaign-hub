"""Integration tests for the /api/campaign(s) endpoints."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def _create(client, **overrides):
    body = {"title": "Sam Barber - Fever Dream", "budget": 1000}
    body.update(overrides)
    return client.post("/api/campaign/create", json=body)


class TestListCampaigns:
    def test_empty_list(self, client):
        resp = client.get("/api/campaigns")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_lists_created_campaigns_in_summary_shape(self, client):
        _create(client)
        resp = client.get("/api/campaigns")
        assert resp.status_code == 200
        items = resp.get_json()
        assert len(items) == 1
        item = items[0]
        assert item["slug"] == "sam_barber_fever_dream"
        assert item["artist"] == "Sam Barber"
        assert item["song"] == "Fever Dream"
        assert "budget" in item
        assert "stats" in item
        assert "creator_count" in item

    def test_search_filters_by_artist(self, client):
        _create(client, title="Sam Barber - Fever Dream")
        _create(client, title="Other Artist - Other Song")
        items = client.get("/api/campaigns?search=sam").get_json()
        assert [i["slug"] for i in items] == ["sam_barber_fever_dream"]

    def test_search_returns_empty_when_nothing_matches(self, client):
        _create(client)
        items = client.get("/api/campaigns?search=zzzzz").get_json()
        assert items == []


class TestCampaignCreateSaveOutcomes:
    def test_does_not_report_conflicted_save_as_created(self, client, monkeypatch):
        from campaign_manager import db

        creator_writes = []
        resolve_requests = []
        monkeypatch.setattr(db, "save_campaign", lambda *args, **kwargs: "conflict")
        monkeypatch.setattr(db, "save_creators", lambda *args, **kwargs: creator_writes.append(args))
        monkeypatch.setattr(
            "campaign_manager.services.chartmetric_autolink.request_immediate_resolve",
            lambda slug: resolve_requests.append(slug),
        )

        response = _create(
            client,
            title="Concurrent Artist - Track",
            official_sound="https://www.tiktok.com/music/track-1234567890123456789",
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "conflict"
        assert creator_writes == []
        assert resolve_requests == []

    def test_unexpected_save_result_fails_closed(self, client, monkeypatch):
        from campaign_manager import db

        creator_writes = []
        monkeypatch.setattr(db, "save_campaign", lambda *args, **kwargs: "unexpected")
        monkeypatch.setattr(db, "save_creators", lambda *args, **kwargs: creator_writes.append(args))

        response = _create(client, title="Unexpected Save Result")

        assert response.status_code == 500
        assert response.get_json()["code"] == "save_failed"
        assert creator_writes == []

    def test_summary_exposes_active_boolean_not_dead_status(self, client):
        _create(client)
        item = client.get("/api/campaigns").get_json()[0]
        assert item["active"] is True          # live until checked off completed
        assert "status" not in item            # dead field removed

    def test_active_filter_excludes_completed(self, client):
        _create(client, title="Live Artist - Live Song")
        _create(client, title="Done Artist - Done Song")
        client.post("/api/campaign/done_artist_done_song/edit",
                    json={"completion_status": "completed"})

        active = client.get("/api/campaigns?active=true").get_json()
        assert [i["slug"] for i in active] == ["live_artist_live_song"]

        finished = client.get("/api/campaigns?active=false").get_json()
        assert [i["slug"] for i in finished] == ["done_artist_done_song"]

        # DEFAULT is active-only, so an agent can't accidentally scrape finished
        # campaigns. Both sets require an explicit ?include_finished=true.
        default = client.get("/api/campaigns").get_json()
        assert [i["slug"] for i in default] == ["live_artist_live_song"]
        assert len(client.get("/api/campaigns?include_finished=true").get_json()) == 2


class TestCreateCampaign:
    def test_creates_campaign_and_parses_title(self, client):
        resp = _create(client)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["ok"] is True
        assert body["slug"] == "sam_barber_fever_dream"

    def test_rejects_missing_title(self, client):
        resp = client.post("/api/campaign/create", json={"title": ""})
        assert resp.status_code == 400
        assert "Title" in resp.get_json()["error"]

    def test_rejects_non_numeric_budget(self, client):
        resp = client.post(
            "/api/campaign/create",
            json={"title": "X - Y", "budget": "not a number"},
        )
        assert resp.status_code == 400

    def test_rejects_duplicate_slug(self, client):
        _create(client)
        resp = _create(client)
        assert resp.status_code == 409

    def test_rejects_duplicate_official_sound_url_on_create(self, client):
        url = "https://www.tiktok.com/music/song-1234567890123456789"
        first = _create(client, title="First Artist - Track", official_sound=url)
        assert first.status_code == 201
        duplicate = _create(
            client,
            title="Second Artist - Track",
            official_sound="HTTPS://WWW.TIKTOK.COM:443/music/song-1234567890123456789#share",
        )
        assert duplicate.status_code == 409
        assert duplicate.get_json()["code"] == "duplicate"

    def test_concurrent_creates_with_same_sound_are_serialized(self, app, db, monkeypatch):
        from concurrent.futures import ThreadPoolExecutor
        import threading

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from types import SimpleNamespace

        from campaign_manager.models import Base
        from campaign_manager.services import chartmetric_autolink

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        old_engine, old_sessions = db._engine, db._SessionLocal
        db._engine = engine
        db._SessionLocal = sessionmaker(bind=engine)

        advisory_lock = threading.Lock()
        barrier = threading.Barrier(2)
        observed_locks = []
        observed_locks_guard = threading.Lock()
        real_get_session = db.get_session
        real_save_campaign = db.save_campaign

        class SerializedPostgresSession:
            def __init__(self):
                self.session = real_get_session()
                self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
                self.owns_lock = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                try:
                    return self.session.__exit__(*args)
                finally:
                    if self.owns_lock:
                        self.owns_lock = False
                        advisory_lock.release()

            def execute(self, statement, *args, **kwargs):
                sql = str(statement)
                if "pg_advisory_xact_lock(hashtext('campaign-sound-url'))" in sql:
                    advisory_lock.acquire()
                    self.owns_lock = True
                    with observed_locks_guard:
                        observed_locks.append(sql)
                    return None
                return self.session.execute(statement, *args, **kwargs)

            def commit(self):
                try:
                    return self.session.commit()
                finally:
                    if self.owns_lock:
                        self.owns_lock = False
                        advisory_lock.release()

            def __getattr__(self, name):
                return getattr(self.session, name)

        def simultaneous_save(slug, meta, **kwargs):
            barrier.wait(timeout=5)
            return real_save_campaign(slug, meta, **kwargs)

        monkeypatch.setattr(db, "get_session", SerializedPostgresSession)
        monkeypatch.setattr(db, "save_campaign", simultaneous_save)
        monkeypatch.setattr(db, "campaign_exists", lambda slug: False)
        monkeypatch.setattr(db, "save_creators", lambda slug, creators: None)
        monkeypatch.setattr(chartmetric_autolink, "request_immediate_resolve", lambda slug: None)
        url = "https://www.tiktok.com/music/shared-1234567890123456789"

        def create(title):
            with app.test_client() as thread_client:
                response = thread_client.post(
                    "/api/campaign/create",
                    json={"title": title, "official_sound": url},
                )
                return response.status_code, response.get_json()

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(create, ["Concurrent A - Track", "Concurrent B - Track"]))
            assert sorted(status for status, _body in results) == [201, 409]
            assert [body.get("code") for status, body in results if status == 409] == ["duplicate"]
            assert len(observed_locks) == 2
            session = db._SessionLocal()
            try:
                rows = session.query(db.Campaign.slug).filter(db.Campaign.official_sound == url).all()
            finally:
                session.close()
            assert len(rows) == 1
        finally:
            db._engine, db._SessionLocal = old_engine, old_sessions
            engine.dispose()

    def test_refuses_file_fallback_for_url_campaign_create(self, client, db, monkeypatch, tmp_path):
        from campaign_manager.blueprints import campaigns

        monkeypatch.setattr(campaigns, "ACTIVE_DIR", tmp_path)
        monkeypatch.setattr(db, "is_active", lambda: False)
        response = _create(
            client,
            title="File-backed Artist - Track",
            official_sound="https://www.tiktok.com/music/song-1234567890123456789",
        )
        assert response.status_code == 503
        assert response.get_json()["code"] == "database_required"
        assert not (tmp_path / "file_backed_artist_track").exists()

    def test_parses_artist_and_song_from_title(self, client, db):
        _create(client, title="Foo - Bar")
        meta = db.get_campaign("foo_bar")
        assert meta["artist"] == "Foo"
        assert meta["song"] == "Bar"


class TestCampaignDetail:
    def test_returns_404_for_missing(self, client):
        resp = client.get("/api/campaign/missing")
        assert resp.status_code == 404

    def test_returns_full_detail_after_create(self, client):
        _create(client)
        resp = client.get("/api/campaign/sam_barber_fever_dream")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["slug"] == "sam_barber_fever_dream"
        assert body["title"] == "Sam Barber - Fever Dream"
        assert body["artist"] == "Sam Barber"
        assert body["creators"] == []
        assert body["matched_videos"] == []
        assert body["budget"]["total"] == 1000.0


class TestEditCampaign:
    def test_404_for_missing(self, client):
        resp = client.post("/api/campaign/none/edit", json={"title": "x"})
        assert resp.status_code == 404

    def test_updates_title_artist_song(self, client):
        _create(client)
        resp = client.post(
            "/api/campaign/sam_barber_fever_dream/edit",
            json={"title": "New Artist - New Song"},
        )
        assert resp.status_code == 200
        detail = client.get("/api/campaign/sam_barber_fever_dream").get_json()
        assert detail["title"] == "New Artist - New Song"
        assert detail["artist"] == "New Artist"
        assert detail["song"] == "New Song"

    def test_rejects_bad_completion_status(self, client):
        _create(client)
        resp = client.post(
            "/api/campaign/sam_barber_fever_dream/edit",
            json={"completion_status": "bogus"},
        )
        assert resp.status_code == 400

    def test_accepts_valid_completion_status(self, client):
        _create(client)
        resp = client.post(
            "/api/campaign/sam_barber_fever_dream/edit",
            json={"completion_status": "completed"},
        )
        assert resp.status_code == 200
        detail = client.get("/api/campaign/sam_barber_fever_dream").get_json()
        assert detail["meta"]["completion_status"] == "completed"

    def test_partial_edits_preserve_optional_campaign_fields(self, client):
        # Keep the date pair valid independently of the day this suite runs.
        _create(client, start_date="2026-09-01")
        slug = "sam_barber_fever_dream"
        client.post(f"/api/campaign/{slug}/edit", json={"additional_sounds": ["123"], "cobrand_link": "https://example.test"})
        for body in ({"end_date": "2026-09-30"}, {"completion_status": "completed"}):
            assert client.post(f"/api/campaign/{slug}/edit", json=body).status_code == 200
            meta = client.get(f"/api/campaign/{slug}").get_json()["meta"]
            assert meta["additional_sounds"] == ["123"]
            assert meta["cobrand_link"] == "https://example.test"
        client.post(f"/api/campaign/{slug}/edit", json={"cobrand_link": ""})
        assert client.get(f"/api/campaign/{slug}").get_json()["meta"]["cobrand_link"] == ""

    def test_start_date_update_validates_effective_end_date(self, client):
        _create(client)
        slug = "sam_barber_fever_dream"
        client.post(f"/api/campaign/{slug}/edit", json={"start_date": "2026-09-01", "end_date": "2026-09-20"})
        assert client.post(f"/api/campaign/{slug}/edit", json={"start_date": "2026-09-21"}).status_code == 400
        assert client.post(f"/api/campaign/{slug}/edit", json={"start_date": "2026-9-02"}).status_code == 400
        assert client.post(f"/api/campaign/{slug}/edit", json={"start_date": "2026-09-02"}).status_code == 200

    def test_header_body_preserves_legacy_start_date_and_validates_changed_dates(self, client):
        _create(client)
        slug = "sam_barber_fever_dream"
        from campaign_manager import db
        meta = db.get_campaign(slug)
        meta["start_date"] = "2026-03-12T10:00:00.000-05:00"
        db.save_campaign(slug, meta)
        body = {"title": "Sam Barber - Fever Dream", "sound_id": "", "tt_artist_label": "", "tt_track_name": "", "additional_sounds": [], "start_date": meta["start_date"], "budget": 1200, "cobrand_link": ""}
        assert client.post(f"/api/campaign/{slug}/edit", json=body).status_code == 200
        assert client.post(f"/api/campaign/{slug}/edit", json={"start_date": "bad-date"}).status_code == 400
        assert client.post(f"/api/campaign/{slug}/edit", json={"start_date": 7}).status_code == 400
        assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-03-12"}).status_code == 400
        meta["start_date"] = "2026-03-12"
        db.save_campaign(slug, meta)
        assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-03-12"}).status_code == 200
        assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": None}).status_code == 400

    def test_rejects_bad_match_strategy(self, client):
        _create(client)
        resp = client.post(
            "/api/campaign/sam_barber_fever_dream/edit",
            json={"match_strategy": "fancy"},
        )
        assert resp.status_code == 400

    def test_accepts_strict_match_strategy(self, client):
        _create(client)
        resp = client.post(
            "/api/campaign/sam_barber_fever_dream/edit",
            json={"match_strategy": "strict"},
        )
        assert resp.status_code == 200

    def test_legacy_sound_url_edit_rejects_canonical_duplicate_and_stale_revision(self, client, db):
        canonical = "https://www.tiktok.com/music/example-123"
        _create(client, title="First Artist - First Song", official_sound=canonical)
        _create(client, title="Second Artist - Second Song")
        slug = "second_artist_second_song"

        # Host case, explicit default port, and fragment do not create a new URL identity.
        duplicate = client.post(
            f"/api/campaign/{slug}/edit",
            json={
                "sound_id": "HTTPS://WWW.TIKTOK.COM:443/music/example-123#share",
                "expected_official_sound": "",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.get_json()["code"] == "duplicate"
        assert db.get_campaign(slug)["official_sound"] == ""

        missing_revision = client.post(
            f"/api/campaign/{slug}/edit",
            json={"sound_id": "https://www.tiktok.com/music/new-456"},
        )
        assert missing_revision.status_code == 409
        assert missing_revision.get_json()["code"] == "missing_revision"

    def test_legacy_sound_id_edit_keeps_identifier_behavior(self, client):
        _create(client)
        slug = "sam_barber_fever_dream"
        sound_id = "1234567890123456789"
        response = client.post(
            f"/api/campaign/{slug}/edit",
            json={"sound_id": sound_id},
        )
        assert response.status_code == 200
        detail = client.get(f"/api/campaign/{slug}").get_json()
        assert detail["sound_id"] == sound_id
        assert detail["official_sound"] == sound_id

    def test_legacy_sound_url_write_takes_shared_postgres_lock_before_read(self, client, db, monkeypatch):
        from types import SimpleNamespace

        _create(client)
        slug = "sam_barber_fever_dream"
        first_meta = db.get_campaign(slug)
        original_get_session = db.get_session
        events = []

        class SessionProxy:
            def __init__(self):
                self.session = original_get_session()
                self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.session.close()

            def execute(self, statement, *args, **kwargs):
                sql = str(statement)
                events.append(("lock", sql))
                assert "pg_advisory_xact_lock(hashtext('campaign-sound-url'))" in sql
                # The test fixture uses SQLite, so observe rather than execute PostgreSQL SQL.
                return None

            def query(self, *args, **kwargs):
                events.append(("query", ""))
                return self.session.query(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.session, name)

        monkeypatch.setattr(db, "get_session", SessionProxy)
        candidate = "https://www.tiktok.com/music/unique-456"
        result = db.save_campaign(
            slug,
            {**first_meta, "official_sound": candidate},
            expected_official_sound="",
        )
        assert result == "updated"
        assert events[0][0] == "lock"
        assert all(event[0] == "query" for event in events[1:])

        # A second writer carrying the same old revision sees the committed URL
        # after taking the same lock and cannot overwrite it.
        second_meta = db.get_campaign(slug)
        events.clear()
        result = db.save_campaign(
            slug,
            {**second_meta, "official_sound": candidate},
            expected_official_sound="",
        )
        assert result == "conflict"
        assert events[0][0] == "lock"

    def test_legacy_edit_surfaces_missing_revision_after_interleaved_url_change(self, client, db, monkeypatch):
        original_url = "https://www.tiktok.com/music/original-123"
        concurrent_url = "https://www.tiktok.com/music/concurrent-456"
        _create(client, official_sound=original_url)
        original_save = db.save_campaign

        def interleaved_save(slug, meta, **kwargs):
            # Another request commits after this route's initial read.
            db.update_campaign_fields(slug, {"official_sound": concurrent_url})
            return original_save(slug, meta, **kwargs)

        monkeypatch.setattr(db, "save_campaign", interleaved_save)
        response = client.post(
            "/api/campaign/sam_barber_fever_dream/edit",
            json={"sound_id": original_url},
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "missing_revision"
        assert db.get_campaign("sam_barber_fever_dream")["official_sound"] == concurrent_url


class TestCampaignSoundLink:
    def test_stores_canonical_url_and_replaces_stale_sound_id(self, client, db):
        old_url = "https://www.tiktok.com/music/old-1234567890123456789"
        new_url = "https://www.tiktok.com/music/new-9876543210987654321"
        _create(client, official_sound=old_url, title="First - Song")
        assert db.get_campaign("first_song")["sound_id"] == "1234567890123456789"
        response = client.put("/api/campaign/first_song/sound-link", json={
            "url": f" {new_url}#details ", "expected_url": old_url,
        })
        assert response.status_code == 200
        assert response.get_json()["official_sound"] == new_url
        assert response.get_json()["sound_id"] == "9876543210987654321"
        saved = db.get_campaign("first_song")
        assert saved["official_sound"] == new_url
        assert saved["sound_id"] == "9876543210987654321"

    def test_sound_link_write_uses_shared_postgres_advisory_lock(self, client, db, monkeypatch):
        from types import SimpleNamespace

        _create(client)
        original_get_session = db.get_session
        events = []

        class SessionProxy:
            def __init__(self):
                self.session = original_get_session()
                self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.session.close()

            def execute(self, statement, *args, **kwargs):
                sql = str(statement)
                events.append(("lock", sql))
                assert "pg_advisory_xact_lock(hashtext('campaign-sound-url'))" in sql
                return None

            def query(self, *args, **kwargs):
                events.append(("query", ""))
                return self.session.query(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.session, name)

        monkeypatch.setattr(db, "get_session", SessionProxy)
        response = client.put("/api/campaign/sam_barber_fever_dream/sound-link", json={
            "url": "https://www.tiktok.com/music/new-9876543210987654321", "expected_url": "",
        })
        assert response.status_code == 200
        assert events[0][0] == "lock"
        assert all(event[0] == "query" for event in events[1:])

    def test_non_tiktok_url_clears_old_sound_id(self, client, db):
        _create(client, official_sound="https://www.tiktok.com/music/old-1234567890123456789")
        response = client.put("/api/campaign/sam_barber_fever_dream/sound-link", json={
            "url": "https://example.com/new-sound",
            "expected_url": "https://www.tiktok.com/music/old-1234567890123456789",
        })
        assert response.status_code == 200
        saved = db.get_campaign("sam_barber_fever_dream")
        assert saved["official_sound"] == "https://example.com/new-sound"
        assert saved["sound_id"] == ""

    def test_rejects_non_object_payload(self, client):
        response = client.put(
            "/api/campaign/sam_barber_fever_dream/sound-link",
            json=["https://example.com"],
        )
        assert response.status_code == 400
        assert response.get_json()["code"] == "invalid_payload"

    def test_refuses_file_fallback_for_unique_sound_link(self, client, db, monkeypatch, tmp_path):
        import json
        from campaign_manager.blueprints import campaigns

        campaign_dir = tmp_path / "sam_barber_fever_dream"
        campaign_dir.mkdir()
        campaign_file = campaign_dir / "campaign.json"
        original = {
            "official_sound": "https://old.example/sound",
            "sound_id": "1234567890123456789",
        }
        campaign_file.write_text(json.dumps(original))
        monkeypatch.setattr(campaigns, "ACTIVE_DIR", tmp_path)
        monkeypatch.setattr(db, "is_active", lambda: False)

        response = client.put("/api/campaign/sam_barber_fever_dream/sound-link", json={
            "url": "https://www.tiktok.com/music/new-9876543210987654321",
            "expected_url": original["official_sound"],
        })
        assert response.status_code == 503
        assert response.get_json()["code"] == "database_required"
        assert json.loads(campaign_file.read_text()) == original

    def test_refuses_legacy_url_change_in_file_fallback(self, client, db, monkeypatch, tmp_path):
        import json
        from campaign_manager.blueprints import campaigns

        campaign_dir = tmp_path / "sam_barber_fever_dream"
        campaign_dir.mkdir()
        campaign_file = campaign_dir / "campaign.json"
        original = {
            "title": "Sam Barber - Fever Dream",
            "official_sound": "https://old.example/sound",
            "sound_id": "1234567890123456789",
            "start_date": "2026-01-01",
        }
        campaign_file.write_text(json.dumps(original))
        monkeypatch.setattr(campaigns, "ACTIVE_DIR", tmp_path)
        monkeypatch.setattr(db, "is_active", lambda: False)

        response = client.post("/api/campaign/sam_barber_fever_dream/edit", json={
            "sound_id": "https://www.tiktok.com/music/new-9876543210987654321",
            "expected_official_sound": original["official_sound"],
        })
        assert response.status_code == 503
        assert response.get_json()["code"] == "database_required"
        assert json.loads(campaign_file.read_text()) == original

    @pytest.mark.parametrize("url", ["", "not a link", "ftp://example.com/x", "https://user:pass@example.com/x"])
    def test_rejects_non_http_urls(self, client, url):
        _create(client)
        response = client.put("/api/campaign/sam_barber_fever_dream/sound-link", json={
            "url": url, "expected_url": "",
        })
        assert response.status_code == 400
        assert response.get_json()["code"] == "invalid_url"

    def test_rejects_a_link_already_used_by_another_campaign(self, client):
        _create(client, title="First - Song", official_sound="https://EXAMPLE.com:443/music/123#old")
        _create(client, title="Second - Song")
        response = client.put("/api/campaign/second_song/sound-link", json={
            "url": "https://example.com/music/123", "expected_url": "",
        })
        assert response.status_code == 409
        assert response.get_json()["code"] == "duplicate"

    def test_rejects_a_stale_browser_edit_without_overwriting(self, client, db):
        _create(client, official_sound="https://example.com/current")
        response = client.put("/api/campaign/sam_barber_fever_dream/sound-link", json={
            "url": "https://example.com/new", "expected_url": "https://example.com/old",
        })
        assert response.status_code == 409
        assert response.get_json()["code"] == "conflict"
        assert db.get_campaign("sam_barber_fever_dream")["official_sound"] == "https://example.com/current"


class TestCreatorNichesRoundtrip:
    """Regression: niches field was omitted from campaign_detail creator response,
    causing the frontend to silently overwrite stored niches with [] on every edit."""

    def _slug(self):
        return "sam_barber_fever_dream"

    def test_niches_present_in_campaign_detail_after_add(self, client):
        _create(client)
        client.post(
            f"/api/campaign/{self._slug()}/creator/add",
            json={"username": "testcreator", "posts_owed": 2, "total_rate": 400,
                  "niches": ["fashion", "lifestyle"]},
        )
        detail = client.get(f"/api/campaign/{self._slug()}").get_json()
        creator = next(c for c in detail["creators"] if c["username"] == "testcreator")
        assert creator["niches"] == ["fashion", "lifestyle"]

    def test_niches_survive_edit_roundtrip(self, client):
        _create(client)
        client.post(
            f"/api/campaign/{self._slug()}/creator/add",
            json={"username": "testcreator", "posts_owed": 2, "total_rate": 400,
                  "niches": ["fashion"]},
        )
        # Edit creator, explicitly passing the niches back (as the frontend does
        # when it reads niches from the detail response and echoes them on save).
        client.post(
            f"/api/campaign/{self._slug()}/creator/testcreator/edit",
            json={"posts_owed": 3, "total_rate": 600, "niches": ["fashion"]},
        )
        detail = client.get(f"/api/campaign/{self._slug()}").get_json()
        creator = next(c for c in detail["creators"] if c["username"] == "testcreator")
        assert creator["niches"] == ["fashion"]

    def test_empty_niches_field_present_when_no_niches_set(self, client):
        _create(client)
        client.post(
            f"/api/campaign/{self._slug()}/creator/add",
            json={"username": "bare", "posts_owed": 1, "total_rate": 200},
        )
        detail = client.get(f"/api/campaign/{self._slug()}").get_json()
        creator = next(c for c in detail["creators"] if c["username"] == "bare")
        assert creator["niches"] == []
