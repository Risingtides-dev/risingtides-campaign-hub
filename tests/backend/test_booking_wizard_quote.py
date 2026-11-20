"""Outreach confirmation books the right platform with the right rate."""
import pytest

from campaign_manager.models import Campaign, Creator, NetworkCreator


def _make_campaign(db, slug="wizard-quote"):
    with db.get_session() as session:
        campaign = Campaign(slug=slug, title="Wizard quote")
        session.add(campaign)
        session.commit()
        return campaign.id


@pytest.mark.parametrize("total_quote,posts", [(75, 3), (10, 3)])
def test_outreach_confirmation_preserves_total_quote_and_derives_per_post_rate(db, client, total_quote, posts):
    campaign_id = _make_campaign(db)

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


def test_instagram_outreach_books_instagram_creator(db, client):
    """An outreach for an Instagram creator must produce platform='instagram', not 'tiktok'."""
    campaign_id = _make_campaign(db)

    response = client.post("/api/campaign/wizard-quote/outreach/add", json=[
        {"username": "bobig", "platform": "instagram", "rate": 50, "posts": 1},
    ])
    assert response.status_code == 200
    msg = response.get_json()["messages"][0]
    assert msg["platform"] == "instagram"

    accepted = client.post("/api/campaign/wizard-quote/outreach/confirm", json={"username": "bobig"})
    assert accepted.status_code == 200
    with db.get_session() as session:
        booked = session.query(Creator).filter_by(campaign_id=campaign_id, username="bobig").one()
        assert booked.platform == "instagram"


def test_instagram_confirm_does_not_collide_with_existing_tiktok_booking(db, client):
    """Same handle, different platforms: confirming an IG outreach must create a new row
    even when a TikTok Creator row already exists for that handle on the campaign."""
    campaign_id = _make_campaign(db)

    # Pre-existing TikTok booking for the same handle
    with db.get_session() as session:
        tiktok_booking = Creator(
            campaign_id=campaign_id,
            username="crossbob",
            platform="tiktok",
            posts_owed=2,
            total_rate=100.0,
            per_post_rate=50.0,
            status="active",
            added_date="2026-01-01",
        )
        session.add(tiktok_booking)
        session.commit()

    # Add and confirm an Instagram outreach for the same handle
    client.post("/api/campaign/wizard-quote/outreach/add", json=[
        {"username": "crossbob", "platform": "instagram", "rate": 60, "posts": 1},
    ])
    accepted = client.post("/api/campaign/wizard-quote/outreach/confirm", json={"username": "crossbob"})
    assert accepted.status_code == 200

    with db.get_session() as session:
        rows = session.query(Creator).filter_by(campaign_id=campaign_id, username="crossbob").all()
        platforms = {r.platform for r in rows}
        assert platforms == {"tiktok", "instagram"}, (
            f"Expected both platforms; got {platforms}"
        )


def test_repeat_confirm_is_idempotent(db, client):
    """Confirming the same outreach twice must not create duplicate Creator rows."""
    campaign_id = _make_campaign(db, slug="idempotent-campaign")

    client.post("/api/campaign/idempotent-campaign/outreach/add", json=[
        {"username": "eve", "platform": "tiktok", "rate": 40, "posts": 2},
    ])
    client.post("/api/campaign/idempotent-campaign/outreach/confirm", json={"username": "eve"})
    client.post("/api/campaign/idempotent-campaign/outreach/confirm", json={"username": "eve"})

    with db.get_session() as session:
        count = session.query(Creator).filter_by(campaign_id=campaign_id, username="eve").count()
        assert count == 1


def test_network_creator_platform_used_as_fallback(db, client):
    """Pre-migration rows lack a stored platform; confirm_outreach must fall back to
    NetworkCreator.platform rather than hardcoding tiktok."""
    campaign_id = _make_campaign(db, slug="fallback-campaign")

    # Seed the network creator roster with platform=instagram
    with db.get_session() as session:
        nc = NetworkCreator(username="igonly", platform="instagram", default_rate=0.0)
        session.add(nc)
        session.commit()

    # Add outreach WITHOUT an explicit platform (simulates pre-migration or
    # a client that doesn't pass platform yet)
    client.post("/api/campaign/fallback-campaign/outreach/add", json=[
        {"username": "igonly", "rate": 30, "posts": 1},
    ])

    # Force the stored platform to empty string to simulate a pre-migration row
    with db.get_session() as session:
        from campaign_manager.models import OutreachMessage
        msg = session.query(OutreachMessage).filter_by(username="igonly").first()
        msg.platform = ""
        session.commit()

    accepted = client.post("/api/campaign/fallback-campaign/outreach/confirm", json={"username": "igonly"})
    assert accepted.status_code == 200

    with db.get_session() as session:
        booked = session.query(Creator).filter_by(campaign_id=campaign_id, username="igonly").one()
        assert booked.platform == "instagram"
