"""The Wizard's outreach rate is a total quote, not a per-post amount."""
import pytest

from campaign_manager.models import Campaign, Creator


@pytest.mark.parametrize("total_quote,posts", [(75, 3), (10, 3)])
def test_outreach_confirmation_preserves_total_quote_and_derives_per_post_rate(db, client, total_quote, posts):
    with db.get_session() as session:
        campaign = Campaign(slug="wizard-quote", title="Wizard quote")
        session.add(campaign)
        session.commit()
        campaign_id = campaign.id

    response = client.post("/api/campaign/wizard-quote/outreach/add", json=[
        {"username": "alice", "rate": total_quote, "posts": posts},
    ])
    assert response.status_code == 200
    assert response.get_json()["added"] == 1
    quote = response.get_json()["messages"][0]
    assert quote["rate_offered"] == total_quote
    assert quote["posts_offered"] == posts

    accepted = client.post("/api/campaign/wizard-quote/outreach/confirm", json={"username": "alice"})
    assert accepted.status_code == 200
    with db.get_session() as session:
        booked = session.query(Creator).filter_by(campaign_id=campaign_id, username="alice").one()
        assert booked.total_rate == total_quote
        assert booked.posts_owed == posts
        assert booked.per_post_rate == pytest.approx(total_quote / posts)
