"""Tests for the outreach send endpoint — provider-key guard."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


def _make_campaign(client):
    resp = client.post("/api/campaign/create", json={"title": "Test Artist - Test Song", "budget": 500})
    assert resp.status_code in (200, 201)
    return resp.get_json()["slug"]


def _add_network_creator(client, username, manychat_id="sub_123"):
    resp = client.post("/api/network", json={
        "username": username,
        "default_rate": 100,
        "default_posts": 1,
        "manychat_subscriber_id": manychat_id,
    })
    assert resp.status_code == 200


def _add_to_outreach(client, slug, username):
    resp = client.post(f"/api/campaign/{slug}/outreach/add", json=[{
        "username": username,
        "rate": 100,
        "posts": 1,
    }])
    assert resp.status_code == 200


class TestSendOutreachNoKey:
    """When MANYCHAT_API_KEY is absent or blank, send must fail fast and preserve drafts."""

    def test_missing_key_returns_503(self, client, app):
        slug = _make_campaign(client)
        _add_network_creator(client, "creator1")
        _add_to_outreach(client, slug, "creator1")

        app.config.pop("MANYCHAT_API_KEY", None)

        resp = client.post(f"/api/campaign/{slug}/outreach/send", json={"message_template": "hi {creator}"})
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["sent"] == []
        assert "not configured" in body["error"].lower()

    def test_blank_key_returns_503(self, client, app):
        slug = _make_campaign(client)
        _add_network_creator(client, "creator2")
        _add_to_outreach(client, slug, "creator2")

        app.config["MANYCHAT_API_KEY"] = ""

        resp = client.post(f"/api/campaign/{slug}/outreach/send", json={"message_template": "hi {creator}"})
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["sent"] == []

    def test_drafts_preserved_when_key_missing(self, client, app):
        slug = _make_campaign(client)
        _add_network_creator(client, "creator3")
        _add_to_outreach(client, slug, "creator3")

        app.config.pop("MANYCHAT_API_KEY", None)

        client.post(f"/api/campaign/{slug}/outreach/send", json={"message_template": "hi {creator}"})

        # Draft must still be a draft
        status_resp = client.get(f"/api/campaign/{slug}/outreach/status")
        messages = status_resp.get_json()["messages"]
        assert all(m["status"] == "draft" for m in messages)


class TestSendOutreachSuccess:
    """With a configured key and a mocked 200 from ManyChat, messages move to sent."""

    def test_mocked_200_marks_message_sent(self, client, app):
        slug = _make_campaign(client)
        _add_network_creator(client, "creator4", manychat_id="sub_456")
        _add_to_outreach(client, slug, "creator4")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "sent"}

        app.config["MANYCHAT_API_KEY"] = "test-key-abc"

        with patch("campaign_manager.blueprints.outreach.http_requests.post", return_value=mock_resp):
            resp = client.post(
                f"/api/campaign/{slug}/outreach/send",
                json={"message_template": "hey {creator}!"},
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert "creator4" in body["sent"]
        assert body["errors"] == []

        status_resp = client.get(f"/api/campaign/{slug}/outreach/status")
        messages = status_resp.get_json()["messages"]
        assert all(m["status"] == "sent" for m in messages)

    def test_mocked_non_200_leaves_draft_and_reports_error(self, client, app):
        slug = _make_campaign(client)
        _add_network_creator(client, "creator5", manychat_id="sub_789")
        _add_to_outreach(client, slug, "creator5")

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        app.config["MANYCHAT_API_KEY"] = "test-key-abc"

        with patch("campaign_manager.blueprints.outreach.http_requests.post", return_value=mock_resp):
            resp = client.post(
                f"/api/campaign/{slug}/outreach/send",
                json={"message_template": "hey {creator}!"},
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["sent"] == []
        assert any("creator5" in e["username"] for e in body["errors"])

        status_resp = client.get(f"/api/campaign/{slug}/outreach/status")
        messages = status_resp.get_json()["messages"]
        assert all(m["status"] == "draft" for m in messages)
