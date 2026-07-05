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
