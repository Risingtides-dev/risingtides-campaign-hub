"""Durable message admission and invalid quote refusal with no real sends."""
from unittest.mock import Mock

import pytest
import requests

from campaign_manager.models import Campaign


@pytest.fixture
def quote(db):
    with db.get_session() as session:
        campaign = Campaign(slug="admission", title="Admission")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id
    db.add_network_creator({"username": "alice", "manychat_subscriber_id": "fixture"})
    db.add_outreach_messages(campaign_id, [{"username": "alice", "rate": 50, "posts": 2}])
    return campaign_id


def test_claim_is_committed_before_http_and_nested_send_cannot_replay(app, client, db, quote, monkeypatch):
    from campaign_manager.blueprints import outreach
    app.config["MANYCHAT_API_KEY"] = "fixture"
    def deliver(*args, **kwargs):
        assert db.get_outreach_message(quote, "alice")["status"] == "sending"
        with app.test_client() as other:
            refused = other.post('/api/campaign/admission/outreach/send', json={"message_template": "Offer ${rate}"})
        assert refused.status_code == 400
        assert "No draft" in refused.get_json()["error"]
        return Mock(status_code=200, json=lambda: {"status": "success"})
    post = Mock(side_effect=deliver)
    monkeypatch.setattr(outreach.http_requests, "post", post)
    response = client.post('/api/campaign/admission/outreach/send', json={"message_template": "Offer ${rate}"})
    assert response.get_json()["sent"] == ["alice"]
    assert post.call_count == 1
    assert db.get_outreach_message(quote, "alice")["status"] == "sent"
    assert not db.claim_outreach_delivery(quote, "alice", "second attempt")


@pytest.mark.parametrize("failure", [requests.Timeout("private request detail"), ValueError("private response detail")])
def test_unknown_provider_outcome_is_reserved_and_never_replayed(app, client, db, quote, monkeypatch, failure):
    from campaign_manager.blueprints import outreach
    app.config["MANYCHAT_API_KEY"] = "fixture"
    post = (Mock(side_effect=failure) if isinstance(failure, requests.Timeout)
            else Mock(return_value=Mock(status_code=200, json=Mock(side_effect=failure))))
    monkeypatch.setattr(outreach.http_requests, "post", post)
    response = client.post('/api/campaign/admission/outreach/send', json={"message_template": "Offer ${rate}"})
    assert response.get_json()["sent"] == []
    assert "private" not in response.get_data(as_text=True)
    message = db.get_outreach_message(quote, "alice")
    assert message["status"] == "unknown"
    assert not message["sent_at"]
    assert message["message_text"] == "Offer $50.00"
    again = client.post('/api/campaign/admission/outreach/send', json={"message_template": "Offer ${rate}"})
    assert again.status_code == 400
    assert post.call_count == 1


def test_worker_loss_after_admission_leaves_nonretryable_attempt(app, client, db, quote, monkeypatch):
    from campaign_manager.blueprints import outreach
    class WorkerLoss(BaseException): pass
    app.config["MANYCHAT_API_KEY"] = "fixture"
    post = Mock(side_effect=WorkerLoss())
    monkeypatch.setattr(outreach.http_requests, "post", post)
    with pytest.raises(WorkerLoss):
        client.post('/api/campaign/admission/outreach/send', json={"message_template": "Offer"})
    assert db.get_outreach_message(quote, "alice")["status"] == "sending"
    again = client.post('/api/campaign/admission/outreach/send', json={"message_template": "Offer"})
    assert again.status_code == 400
    assert post.call_count == 1


@pytest.mark.parametrize("field,value", [
    ("username", "@"), ("username", 3),
    ("default_rate", -1), ("default_rate", "NaN"), ("default_rate", "Infinity"),
    ("default_rate", True), ("default_rate", None),
    ("default_posts", 0), ("default_posts", -1), ("default_posts", 1.5),
    ("default_posts", True), ("default_posts", "bad"), ("default_posts", 2147483648),
])
def test_invalid_network_create_and_update_are_400_without_changes(client, db, field, value):
    response = client.post('/api/network', json={"username": "alice", field: value})
    assert response.status_code == 400
    assert db.get_network_creators() == []
    db.add_network_creator({"username": "alice", "default_rate": 25, "default_posts": 2})
    before = db.get_network_creator("alice")
    response = client.put('/api/network/alice', json={field: value})
    assert response.status_code == 400
    assert db.get_network_creator("alice") == before


@pytest.mark.parametrize("payload", [None, [], "creator", True])
def test_network_shape_refusal(client, payload):
    response = client.post('/api/network', json=payload, content_type='application/json')
    assert response.status_code == 400
    response = client.put('/api/network/alice', json=payload, content_type='application/json')
    assert response.status_code == 400


@pytest.mark.parametrize("bad", [
    {"username": "@"}, {"username": "bad", "rate": -1}, {"username": "bad", "rate": "NaN"},
    {"username": "bad", "posts": 0}, {"username": "bad", "posts": 1.5},
    {"username": "bad", "posts": True}, "bad", None,
])
def test_invalid_outreach_batch_writes_nothing(client, db, quote, bad):
    response = client.post('/api/campaign/admission/outreach/add', json=[{"username": "good", "rate": 0, "posts": 1}, bad])
    assert response.status_code == 400
    assert [message["username"] for message in db.get_outreach_messages(quote)] == ["alice"]


def test_valid_zero_quote_and_integral_legacy_count_are_preserved(client, db, quote):
    response = client.post('/api/campaign/admission/outreach/add', json={"creators": [{"username": " @BOB ", "rate": 0, "posts": "2"}]})
    assert response.status_code == 200
    message = db.get_outreach_message(quote, "bob")
    assert message["rate_offered"] == 0
    assert message["posts_offered"] == 2
