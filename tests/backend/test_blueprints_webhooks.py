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


class TestNotionSync:
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


class TestSlackSoundsHook:
    def test_returns_500_without_channel_configured(self, client, monkeypatch):
        monkeypatch.delenv("SLACK_SOUNDS_CHANNEL", raising=False)
        resp = client.post("/api/webhooks/slack/sounds")
        assert resp.status_code == 500
