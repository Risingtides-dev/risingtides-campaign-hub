"""Integration tests for the /api/webhooks endpoints."""
from __future__ import annotations

from unittest.mock import patch

import pytest


pytestmark = pytest.mark.integration


class TestNotionWebhook:
    def test_rejects_missing_body(self, client):
        resp = client.post("/api/webhooks/notion", data="", content_type="application/json")
        assert resp.status_code == 400

    def test_requires_artist_or_song(self, client):
        resp = client.post("/api/webhooks/notion", json={})
        assert resp.status_code == 400

    def test_creates_campaign_from_artist_and_song(self, client, db):
        resp = client.post(
            "/api/webhooks/notion",
            json={
                "artist": "Sam Barber",
                "song": "Fever Dream",
                "budget": "2500",
                "tiktok_sound_link": "https://www.tiktok.com/music/X-1234567890",
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["slug"] == "sam_barber_fever_dream"
        meta = db.get_campaign("sam_barber_fever_dream")
        assert meta["artist"] == "Sam Barber"
        assert meta["song"] == "Fever Dream"
        assert meta["budget"] == 2500.0
        assert meta["sound_id"] == "1234567890"
        assert meta["source"] == "notion"

    def test_uses_provided_title_when_supplied(self, client, db):
        resp = client.post(
            "/api/webhooks/notion",
            json={"title": "Custom Title", "artist": "A", "song": "B"},
        )
        assert resp.status_code == 201
        assert db.get_campaign(resp.get_json()["slug"])["title"] == "Custom Title"

    def test_409_for_duplicate_slug(self, client):
        body = {"artist": "X", "song": "Y"}
        client.post("/api/webhooks/notion", json=body)
        resp = client.post("/api/webhooks/notion", json=body)
        assert resp.status_code == 409

    def test_rejects_duplicate_official_sound_url(self, client):
        body = {
            "artist": "A", "song": "One",
            "tiktok_sound_link": "https://www.tiktok.com/music/shared-1234567890123456789",
        }
        assert client.post("/api/webhooks/notion", json=body).status_code == 201
        duplicate = client.post("/api/webhooks/notion", json={
            **body, "artist": "B", "song": "Two",
            "tiktok_sound_link": "HTTPS://WWW.TIKTOK.COM:443/music/shared-1234567890123456789#share",
        })
        assert duplicate.status_code == 409
        assert duplicate.get_json()["code"] == "duplicate"


class TestNotionSync:
    def test_duplicate_sound_url_is_skipped_without_creating_campaign(self, client, db):
        url = "https://www.tiktok.com/music/shared-1234567890123456789"
        db.save_campaign("existing", {"title": "Existing", "official_sound": url})
        entries = [{
            "notion_page_id": "page-duplicate", "title": "New - Track", "slug": "new_track",
            "artist": "New", "song": "Track", "official_sound": url, "sound_id": "1234567890123456789",
            "start_date": "", "budget": 0,
        }]
        with patch("campaign_manager.services.notion.query_new_clients", return_value=entries):
            resp = client.post("/api/webhooks/notion/sync")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["created"] == []
        assert {item["slug"] for item in body["skipped"]} == {"new_track"}
        assert body["skipped"][0]["reason"] == "duplicate sound URL"
        assert db.get_campaign("new_track") is None

    def test_returns_empty_when_no_new_entries(self, client):
        with patch(
            "campaign_manager.services.notion.query_new_clients",
            return_value=[],
        ):
            resp = client.post("/api/webhooks/notion/sync")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["created"] == []

    def test_creates_new_campaigns_and_skips_existing(self, client, db):
        entries = [
            {
                "notion_page_id": "page-1",
                "title": "A - One",
                "slug": "a_one",
                "artist": "A",
                "song": "One",
                "official_sound": "",
                "sound_id": "",
                "start_date": "2026-04-01",
                "budget": 100,
            },
            {
                "notion_page_id": "page-2",
                "title": "B - Two",
                "slug": "b_two",
                "artist": "B",
                "song": "Two",
                "official_sound": "",
                "sound_id": "",
                "start_date": "",
                "budget": 0,
            },
        ]
        # Seed an existing campaign so we exercise the skip path too.
        db.save_campaign("b_two", {"title": "B - Two", "artist": "B"})

        with patch(
            "campaign_manager.services.notion.query_new_clients",
            return_value=entries,
        ):
            resp = client.post("/api/webhooks/notion/sync")
        assert resp.status_code == 200
        body = resp.get_json()
        assert {c["slug"] for c in body["created"]} == {"a_one"}
        assert {s["slug"] for s in body["skipped"]} == {"b_two"}

    def test_existing_campaigns_get_content_types_refreshed_and_nothing_else(self, client, db):
        # The pre-fix reality: campaigns imported before the property-name
        # fix have empty content_types while the CRM row carries tags.
        db.save_campaign("b_two", {
            "title": "B - Two", "artist": "B", "content_types": [],
            "label": "Operator Edited Label",
        })
        entries = [
            {
                "notion_page_id": "page-2",
                "title": "B - Two",
                "slug": "b_two",
                "artist": "B",
                "song": "Two",
                "official_sound": "",
                "sound_id": "",
                "start_date": "",
                "budget": 0,
                "content_types": ["Trucktok", "POV"],
            },
        ]
        with patch(
            "campaign_manager.services.notion.query_new_clients",
            return_value=entries,
        ) as query:
            resp = client.post("/api/webhooks/notion/sync")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["created"] == []
        assert body["skipped"] == []
        assert body["refreshed"] == [{"slug": "b_two", "content_types": ["Trucktok", "POV"]}]
        meta = db.get_campaign("b_two")
        assert meta["content_types"] == ["Trucktok", "POV"]
        # Only content_types was refreshed — operator-edited fields are untouched.
        assert meta["label"] == "Operator Edited Label"
        # The sync now reads ALL client rows (add-only would never see this one).
        assert query.call_args.args[0] == set()

    def test_backfill_refreshes_existing_fleet_by_page_id_regardless_of_pipeline_status(self, client, db):
        # The real-world case: a campaign imported long ago, its CRM row no
        # longer at Pipeline Status 'Client' (782/783 rows are 'Lead'), so
        # the import funnel never sees it — but its niche targets must still
        # track the CRM.
        db.save_campaign("old_campaign", {
            "title": "Old", "notion_page_id": "page-old", "content_types": [],
        })
        with patch(
            "campaign_manager.services.notion.query_new_clients",
            return_value=[],
        ), patch(
            "campaign_manager.services.notion.fetch_page_campaign_fields",
            return_value={"content_types": ["Trucktok", "Coffee"], "internal_captions": None},
        ) as fetch:
            resp = client.post("/api/webhooks/notion/sync")
        body = resp.get_json()
        assert {"slug": "old_campaign", "content_types": ["Trucktok", "Coffee"]} in body["refreshed"]
        assert db.get_campaign("old_campaign")["content_types"] == ["Trucktok", "Coffee"]
        fetch.assert_called_once_with("page-old")

    def test_backfill_never_empties_on_unreadable_page_and_skips_unchanged(self, client, db):
        db.save_campaign("unreadable", {
            "title": "U", "notion_page_id": "page-gone", "content_types": ["Trucktok"],
        })
        db.save_campaign("already_fresh", {
            "title": "F", "notion_page_id": "page-fresh", "content_types": ["Coffee"],
        })
        def fake_fetch(page_id):
            if page_id == "page-gone":
                return None
            return {"content_types": ["Coffee"], "internal_captions": None}
        with patch(
            "campaign_manager.services.notion.query_new_clients",
            return_value=[],
        ), patch(
            "campaign_manager.services.notion.fetch_page_campaign_fields",
            side_effect=fake_fetch,
        ):
            resp = client.post("/api/webhooks/notion/sync")
        body = resp.get_json()
        assert body["refreshed"] == []
        # An unreadable page keeps its current tags — never emptied.
        assert db.get_campaign("unreadable")["content_types"] == ["Trucktok"]

    def test_unchanged_content_types_skip_quietly(self, client, db):
        db.save_campaign("b_two", {"title": "B - Two", "content_types": ["Trucktok"]})
        entries = [
            {
                "notion_page_id": "page-2", "title": "B - Two", "slug": "b_two",
                "artist": "B", "song": "Two", "official_sound": "", "sound_id": "",
                "start_date": "", "budget": 0, "content_types": ["Trucktok"],
            },
        ]
        with patch(
            "campaign_manager.services.notion.query_new_clients",
            return_value=entries,
        ):
            resp = client.post("/api/webhooks/notion/sync")
        body = resp.get_json()
        assert body["refreshed"] == []
        assert {s["slug"] for s in body["skipped"]} == {"b_two"}

    def test_new_campaign_carries_the_crm_captions(self, client, db):
        entries = [
            {
                "notion_page_id": "page-1", "title": "A - One", "slug": "a_one",
                "artist": "A", "song": "One", "official_sound": "", "sound_id": "",
                "start_date": "", "budget": 0, "content_types": [],
                "internal_captions": "pov: u miss him\nstill not over it",
            },
        ]
        with patch(
            "campaign_manager.services.notion.query_new_clients",
            return_value=entries,
        ), patch(
            "campaign_manager.services.notion.fetch_page_campaign_fields",
            return_value=None,
        ):
            resp = client.post("/api/webhooks/notion/sync")
        assert {c["slug"] for c in resp.get_json()["created"]} == {"a_one"}
        assert db.get_campaign("a_one")["internal_captions"] == "pov: u miss him\nstill not over it"

    def test_backfill_refreshes_captions_by_page_id_and_keeps_them_when_unreadable(self, client, db):
        db.save_campaign("changed", {
            "title": "C", "notion_page_id": "page-changed", "content_types": ["Coffee"],
            "internal_captions": "old line",
        })
        db.save_campaign("unreadable", {
            "title": "U", "notion_page_id": "page-unreadable", "content_types": ["Coffee"],
            "internal_captions": "kept line",
        })
        def fake_fetch(page_id):
            if page_id == "page-changed":
                return {"content_types": ["Coffee"], "internal_captions": "new line"}
            # The page reads, but its captions property does not.
            return {"content_types": ["Coffee"], "internal_captions": None}
        with patch(
            "campaign_manager.services.notion.query_new_clients",
            return_value=[],
        ), patch(
            "campaign_manager.services.notion.fetch_page_campaign_fields",
            side_effect=fake_fetch,
        ):
            resp = client.post("/api/webhooks/notion/sync")
        assert resp.get_json()["refreshed"] == [{"slug": "changed", "internal_captions": "new line"}]
        assert db.get_campaign("changed")["internal_captions"] == "new line"
        assert db.get_campaign("unreadable")["internal_captions"] == "kept line"

    def test_same_titled_crm_row_never_overwrites_another_campaigns_captions(self, client, db):
        # Round 2 of a song slugs the same as round 1. The stored campaign
        # follows ITS CRM row, not whichever row shares its title.
        db.save_campaign("b_two", {
            "title": "B - Two", "notion_page_id": "page-round-1", "content_types": [],
            "internal_captions": "round one line",
        })
        entries = [
            {
                "notion_page_id": "page-round-2", "title": "B - Two", "slug": "b_two",
                "artist": "B", "song": "Two", "official_sound": "", "sound_id": "",
                "start_date": "", "budget": 0, "content_types": [],
                "internal_captions": "round two line",
            },
        ]
        with patch(
            "campaign_manager.services.notion.query_new_clients",
            return_value=entries,
        ), patch(
            "campaign_manager.services.notion.fetch_page_campaign_fields",
            return_value=None,
        ):
            client.post("/api/webhooks/notion/sync")
        assert db.get_campaign("b_two")["internal_captions"] == "round one line"


class TestSlackSoundsHook:
    def test_returns_500_without_channel_configured(self, client, monkeypatch):
        monkeypatch.delenv("SLACK_SOUNDS_CHANNEL", raising=False)
        resp = client.post("/api/webhooks/slack/sounds")
        assert resp.status_code == 500
