"""Outreach delivery receipts and literal roster identity; no live requests."""
from unittest.mock import Mock

import pytest

from campaign_manager.models import Campaign


@pytest.fixture
def draft(db):
    with db.get_session() as session:
        campaign = Campaign(slug="outreach-truth", title="Outreach truth", artist="Artist", song="Song")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
    db.add_network_creator({"username": "a_b", "manychat_subscriber_id": "fixture-subscriber"})
    db.add_outreach_messages(campaign_id, [{"username": "a_b", "rate": 125.75, "posts": 3}])
    return campaign_id


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_provider_preserves_draft_and_never_claims_delivery(app, client, db, draft, monkeypatch, key):
    from campaign_manager.blueprints import outreach
    app.config["MANYCHAT_API_KEY"] = key
    send = Mock(side_effect=AssertionError("provider must not be called"))
    monkeypatch.setattr(outreach.http_requests, "post", send)
    response = client.post('/api/campaign/outreach-truth/outreach/send', json={"message_template": "${rate}"})
    assert response.status_code == 503
    assert response.get_json()["sent"] == []
    message = db.get_outreach_message(draft, "a_b")
    assert message["status"] == "draft"
    assert not message["sent_at"]
    send.assert_not_called()


@pytest.mark.parametrize("amount,rendered", [(125.75, "125.75"), (125, "125.00"), (0, "0.00")])
def test_send_preserves_offered_cents(app, client, db, draft, monkeypatch, amount, rendered):
    from campaign_manager.blueprints import outreach
    app.config["MANYCHAT_API_KEY"] = "fixture-key"
    db.update_outreach_message(draft, "a_b", {"rate_offered": amount})
    send = Mock(return_value=Mock(status_code=200, json=lambda: {"status": "success"}))
    monkeypatch.setattr(outreach.http_requests, "post", send)
    response = client.post('/api/campaign/outreach-truth/outreach/send', json={"message_template": "${rate} for {posts} posts"})
    assert response.status_code == 200
    assert response.get_json()["sent"] == ["a_b"]
    text = send.call_args.kwargs["json"]["data"]["content"]["messages"][0]["text"]
    assert text == f"${rendered} for 3 posts"
    message = db.get_outreach_message(draft, "a_b")
    assert message["status"] == "sent"
    assert message["message_text"] == text
    assert message["rate_offered"] == amount


def test_network_identity_is_literal_and_normalized_for_reads_updates_and_removal(db):
    # Insert wildcard-match competitor first so a LIKE lookup selects it.
    db.add_network_creator({"username": "acb", "default_rate": 10})
    db.add_network_creator({"username": "a_b", "default_rate": 20})
    assert db.get_network_creator("  @A_B  ")["username"] == "a_b"
    assert db.get_network_creator("a_b")["default_rate"] == 20
    assert db.get_network_creator("%") is None
    assert db.update_network_creator("%", {"default_rate": 99}) is None
    assert db.update_network_creator("  @A_B  ", {"default_rate": 30})["username"] == "a_b"
    assert db.get_network_creator("acb")["default_rate"] == 10
    assert db.get_network_creator("a_b")["default_rate"] == 30
    assert db.remove_network_creator("%") is False
    assert len(db.get_network_creators()) == 2
    assert db.remove_network_creator("  @A_B  ") is True
    assert db.get_network_creator("a_b") is None
    assert db.get_network_creator("acb")["default_rate"] == 10
