"""An outreach quote retains its booking platform instead of consulting later edits."""
import pytest

from campaign_manager.models import Campaign, Creator, OutreachMessage


@pytest.fixture
def campaign(db):
    with db.get_session() as session:
        row = Campaign(slug="platform-quote", title="Platform quote")
        session.add(row)
        session.commit()
        return row.id


def test_instagram_quote_freezes_platform_and_keeps_other_platform_booking(db, client, campaign):
    db.add_network_creator({"username": "alice", "platform": "instagram"})
    with db.get_session() as session:
        session.add(Creator(campaign_id=campaign, username="alice", platform="tiktok", total_rate=99))
        session.commit()
    added = client.post('/api/campaign/platform-quote/outreach/add', json=[{"username": "alice", "rate": 75, "posts": 3}])
    assert added.status_code == 200
    assert added.get_json()["messages"][0]["platform"] == "instagram"
    # The roster is editable; it must not rewrite the meaning of the quote.
    db.update_network_creator("alice", {"platform": "tiktok"})
    response = client.post('/api/campaign/platform-quote/outreach/confirm', json={"username": "alice"})
    assert response.status_code == 200
    with db.get_session() as session:
        rows = {row.platform: row for row in session.query(Creator).filter_by(campaign_id=campaign).all()}
        assert set(rows) == {"tiktok", "instagram"}
        assert rows["tiktok"].total_rate == 99
        assert rows["instagram"].total_rate == 75
        assert rows["instagram"].per_post_rate == 25
    repeated = client.post('/api/campaign/platform-quote/outreach/confirm', json={"username": "alice"})
    assert repeated.status_code == 200
    assert repeated.get_json()["message"]["responded_at"] == response.get_json()["message"]["responded_at"]
    with db.get_session() as session:
        assert session.query(Creator).filter_by(campaign_id=campaign).count() == 2


def test_wizard_explicit_tiktok_quote_does_not_inherit_instagram_roster(db, client, campaign):
    db.add_network_creator({"username": "alice", "platform": "instagram"})
    added = client.post('/api/campaign/platform-quote/outreach/add', json=[{"username": "alice", "rate": 75, "posts": 3, "platform": "tiktok"}])
    assert added.status_code == 200
    response = client.post('/api/campaign/platform-quote/outreach/confirm', json={"username": "alice"})
    assert response.status_code == 200
    with db.get_session() as session:
        assert session.query(Creator).filter_by(campaign_id=campaign).one().platform == "tiktok"


@pytest.mark.parametrize("status", ["draft", "sent", "responded"])
def test_legacy_unstamped_quote_cannot_guess_platform_from_current_roster(db, client, campaign, status):
    db.add_network_creator({"username": "alice", "platform": "instagram"})
    with db.get_session() as session:
        session.add(OutreachMessage(campaign_id=campaign, username="alice", platform=None, status=status, rate_offered=50, posts_offered=1))
        session.commit()
    response = client.post('/api/campaign/platform-quote/outreach/confirm', json={"username": "alice"})
    assert response.status_code == 409
    assert db.get_outreach_message(campaign, "alice")["status"] == status
    assert db.get_outreach_message(campaign, "alice")["platform"] is None
    with db.get_session() as session:
        assert session.query(Creator).filter_by(campaign_id=campaign).count() == 0


def test_accepted_legacy_quote_is_idempotent_without_new_booking(db, client, campaign):
    with db.get_session() as session:
        session.add(OutreachMessage(campaign_id=campaign, username="alice", platform=None, status="accepted"))
        session.commit()
    response = client.post('/api/campaign/platform-quote/outreach/confirm', json={"username": "alice"})
    assert response.status_code == 200
    with db.get_session() as session:
        assert session.query(Creator).filter_by(campaign_id=campaign).count() == 0


def test_invalid_explicit_platform_rejects_entire_draft_batch(db, client, campaign):
    response = client.post('/api/campaign/platform-quote/outreach/add', json=[
        {"username": "good", "rate": 1, "posts": 1},
        {"username": "bad", "rate": 1, "posts": 1, "platform": "unknown"},
    ])
    assert response.status_code == 400
    assert db.get_outreach_messages(campaign) == []
