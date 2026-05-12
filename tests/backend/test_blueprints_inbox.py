"""Integration tests for the /api/inbox endpoints."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def _create_campaign(client):
    return client.post(
        "/api/campaign/create",
        json={"title": "Sam Barber - Fever Dream", "budget": 1000},
    )


def _add_inbox(client, **overrides):
    body = {
        "source": "slack",
        "raw_message": "booking sam barber",
        "campaign_name": "",
        "creators": [{"username": "alice", "posts_owed": 2, "total_rate": 200}],
    }
    body.update(overrides)
    return client.post("/api/inbox", json=body)


class TestInboxAdd:
    def test_rejects_empty_body(self, client):
        resp = client.post("/api/inbox", data="", content_type="application/json")
        assert resp.status_code == 400

    def test_creates_inbox_item(self, client):
        resp = _add_inbox(client)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["id"]

    def test_auto_suggests_campaign_from_message(self, client):
        _create_campaign(client)
        _add_inbox(client, raw_message="sam barber fever dream booking")
        items = client.get("/api/inbox").get_json()
        assert items[0]["campaign_slug"] == "sam_barber_fever_dream"
        assert items[0]["campaign_suggested"] is True

    def test_no_suggestion_when_message_does_not_match(self, client):
        _create_campaign(client)
        _add_inbox(client, raw_message="hello world", campaign_name="")
        items = client.get("/api/inbox").get_json()
        assert items[0]["campaign_slug"] == ""

    def test_extracts_paypal_email_from_message(self, client, db):
        _add_inbox(
            client,
            raw_message="@alice - alice@example.com booking",
            creators=[{"username": "alice", "posts_owed": 1, "total_rate": 100}],
        )
        # PayPal memory should have been populated.
        assert db.get_paypal("alice") == "alice@example.com"


class TestInboxList:
    def test_lists_pending_by_default(self, client):
        _add_inbox(client)
        items = client.get("/api/inbox").get_json()
        assert len(items) == 1
        assert items[0]["status"] == "pending"

    def test_filter_by_status(self, client):
        _add_inbox(client)
        # No approved items exist yet.
        items = client.get("/api/inbox?status=approved").get_json()
        assert items == []


class TestInboxApprove:
    def test_404_when_item_missing(self, client):
        resp = client.post("/api/inbox/nope/approve", json={})
        assert resp.status_code == 404

    def test_requires_campaign_slug(self, client):
        # Create inbox without an attached campaign and without auto-suggestion.
        _add_inbox(client, raw_message="zzz", campaign_name="")
        items = client.get("/api/inbox").get_json()
        item_id = items[0]["id"]
        resp = client.post(f"/api/inbox/{item_id}/approve", json={})
        assert resp.status_code == 400

    def test_404_when_campaign_does_not_exist(self, client):
        _add_inbox(client, raw_message="zzz", campaign_name="")
        items = client.get("/api/inbox").get_json()
        item_id = items[0]["id"]
        resp = client.post(
            f"/api/inbox/{item_id}/approve",
            json={"campaign_slug": "nonexistent_campaign"},
        )
        assert resp.status_code == 404

    def test_approves_and_adds_creators_to_campaign(self, client):
        _create_campaign(client)
        _add_inbox(client, raw_message="sam barber fever dream booking")
        items = client.get("/api/inbox").get_json()
        item_id = items[0]["id"]

        resp = client.post(f"/api/inbox/{item_id}/approve", json={})
        assert resp.status_code == 200
        body = resp.get_json()
        assert "alice" in body["added"]

        # The campaign should now have alice as a creator.
        detail = client.get("/api/campaign/sam_barber_fever_dream").get_json()
        assert [c["username"] for c in detail["creators"]] == ["alice"]

    def test_idempotent_on_existing_creator(self, client):
        _create_campaign(client)
        _add_inbox(client, raw_message="sam barber fever dream booking")
        items = client.get("/api/inbox").get_json()
        item_id = items[0]["id"]

        # First approval adds alice; reset and approve again to ensure no dupes.
        client.post(f"/api/inbox/{item_id}/approve", json={})
        # Add another inbox item with the same creator and approve again.
        _add_inbox(client, raw_message="sam barber fever dream booking")
        items2 = [i for i in client.get("/api/inbox").get_json() if i["status"] == "pending"]
        assert items2, "expected a pending inbox item"
        client.post(f"/api/inbox/{items2[0]['id']}/approve", json={})

        detail = client.get("/api/campaign/sam_barber_fever_dream").get_json()
        usernames = [c["username"] for c in detail["creators"]]
        assert usernames.count("alice") == 1


class TestInboxDismiss:
    def test_404_when_missing(self, client):
        resp = client.post("/api/inbox/nope/dismiss")
        assert resp.status_code == 404

    def test_marks_status_dismissed(self, client):
        _add_inbox(client)
        items = client.get("/api/inbox").get_json()
        item_id = items[0]["id"]
        resp = client.post(f"/api/inbox/{item_id}/dismiss")
        assert resp.status_code == 200
        # Should no longer appear under pending.
        pending = client.get("/api/inbox?status=pending").get_json()
        assert all(i["id"] != item_id for i in pending)
