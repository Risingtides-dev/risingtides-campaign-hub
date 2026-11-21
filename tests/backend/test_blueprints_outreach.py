"""Tests for outreach send message personalization."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration

TEMPLATE = "Hey {creator}! Rate: ${rate} for {posts} post(s)."


def _create_campaign(client):
    return client.post(
        "/api/campaign/create",
        json={"title": "Sam Barber - Fever Dream", "budget": 1000},
    )


def _add_network_creator(client, username="creator1", subscriber_id="mc_001"):
    return client.post(
        "/api/network",
        json={"username": username, "manychat_subscriber_id": subscriber_id},
    )


def _add_to_outreach(client, slug, username, rate, posts=1):
    return client.post(
        f"/api/campaign/{slug}/outreach/add",
        json=[{"username": username, "rate": rate, "posts": posts}],
    )


def _send_outreach(client, slug, template=TEMPLATE):
    return client.post(
        f"/api/campaign/{slug}/outreach/send",
        json={"message_template": template},
    )


def _get_sent_message_text(client, slug, username):
    resp = client.get(f"/api/campaign/{slug}/outreach/status")
    messages = resp.get_json()["messages"]
    for m in messages:
        if m["username"] == username:
            return m["message_text"]
    return None


class TestOutreachRatePersonalization:
    """The {rate} placeholder must preserve the exact offered amount to cents."""

    def test_fractional_rate_preserves_cents(self, client):
        """125.75 must appear as '125.75' in the sent message, not '125'."""
        _create_campaign(client)
        _add_network_creator(client, "creator1", "mc_001")
        _add_to_outreach(client, "sam_barber_fever_dream", "creator1", 125.75)
        resp = _send_outreach(client, "sam_barber_fever_dream")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "creator1" in body["sent"]
        text = _get_sent_message_text(client, "sam_barber_fever_dream", "creator1")
        assert text is not None
        assert "125.75" in text
        assert "$125 " not in text  # old truncated value must not appear

    def test_whole_dollar_rate_formats_correctly(self, client):
        """125.00 must appear as '125' (no spurious decimal) in the sent message."""
        _create_campaign(client)
        _add_network_creator(client, "creator2", "mc_002")
        _add_to_outreach(client, "sam_barber_fever_dream", "creator2", 125.00)
        resp = _send_outreach(client, "sam_barber_fever_dream")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "creator2" in body["sent"]
        text = _get_sent_message_text(client, "sam_barber_fever_dream", "creator2")
        assert text is not None
        assert "$125" in text
        assert "125.0" not in text  # floating-point repr must not leak through
