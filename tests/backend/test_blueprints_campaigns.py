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
        _create(client)
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
