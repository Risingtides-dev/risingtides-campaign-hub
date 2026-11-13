"""Creator dashboard: own bookings + payments only; Hub brief editing."""
from __future__ import annotations

import pytest

from campaign_manager.blueprints import payouts as payouts_bp_module
from campaign_manager.models import Campaign, Creator
from campaign_manager.services import payout_profiles as payouts


@pytest.fixture(autouse=True)
def _reset_limiters():
    payouts_bp_module.public_limiter.reset()
    yield
    payouts_bp_module.public_limiter.reset()


@pytest.fixture
def seeded(db):
    with db.get_session() as s:
        live = Campaign(
            slug="live", title="Mattilo - Beautiful Life", artist="Mattilo", song="Beautiful Life",
            official_sound="https://www.tiktok.com/music/x-1", additional_sounds=["https://www.tiktok.com/music/x-2"],
            insta_sound="https://www.instagram.com/reels/audio/9", internal_captions="line one\n\nline two",
            creator_brief="nature, car, funny POV", budget=1500, completion_status="none",
            cobrand_share_url="https://cobrand.example/share?token=SECRET", start_date="2026-10-20",
        )
        done = Campaign(slug="done", title="Old - Song", artist="Old", song="Song",
                        official_sound="https://www.tiktok.com/music/y", completion_status="completed",
                        start_date="2026-08-01")
        other = Campaign(slug="other", title="Other - Thing", completion_status="none")
        s.add_all([live, done, other])
        s.flush()
        s.add_all([
            Creator(campaign_id=live.id, username="@Alice", platform="tiktok", posts_owed=3, posts_done=1,
                    total_rate=150, notes="INTERNAL: slow last time", paypal_email="legacy@x.com"),
            Creator(campaign_id=live.id, username="alice", platform="instagram", posts_owed=2, posts_done=2,
                    total_rate=100),
            Creator(campaign_id=done.id, username="alice", posts_owed=2, posts_done=2, total_rate=80,
                    paid="yes", payment_date="2026-08-20"),
            Creator(campaign_id=other.id, username="bob", posts_owed=1, total_rate=999),
            Creator(campaign_id=other.id, username="alice", posts_owed=1, status="removed", total_rate=55),
        ])
        s.commit()
        profile, _ = payouts.issue_token(s, "alice")
        return profile.payout_token


def test_dashboard_shows_own_bookings_and_payments(client, seeded):
    resp = client.post("/api/creator/dashboard", json={"token": seeded})
    assert resp.status_code == 200
    data = resp.json
    assert data["creator"]["handle"] == "alice"

    assert [c["campaign"] for c in data["current"]] == ["Mattilo - Beautiful Life"]
    card = data["current"][0]
    assert card["brief"] == "nature, car, funny POV" and card["open_creative"] is False
    assert card["captions"] == ["line one", "line two"]
    assert card["platforms"] == ["instagram", "tiktok"]
    assert [s["url"] for s in card["sounds"]] == [
        "https://www.tiktok.com/music/x-1", "https://www.tiktok.com/music/x-2",
        "https://www.instagram.com/reels/audio/9",
    ]
    assert (card["posts_owed"], card["posts_done"], card["rate"], card["status"]) == (5, 3, 250.0, "in_progress")

    assert data["payments"] == [{"campaign": "Old - Song", "amount": 80.0, "date": "2026-08-20", "platform": "tiktok"}]
    assert data["totals"] == {"paid": 80.0, "campaigns": 2}


def test_dashboard_never_leaks_internal_or_other_creators(client, seeded):
    body = client.post("/api/creator/dashboard", json={"token": seeded}).get_data(as_text=True)
    for secret in ("SECRET", "cobrand", "INTERNAL", "legacy@x.com", "1500", "bob", "999", "Other - Thing", "55"):
        assert secret not in body, secret


def test_finished_unpaid_campaign_is_not_shown_as_owed(client, db, seeded):
    with db.get_session() as s:
        stale = Campaign(slug="stale", title="Stale - Song", completion_status="completed")
        s.add(stale)
        s.flush()
        s.add(Creator(campaign_id=stale.id, username="alice", posts_owed=1, posts_done=1, total_rate=40))
        s.commit()
    data = client.post("/api/creator/dashboard", json={"token": seeded}).json
    assert "Stale - Song" not in [c["campaign"] for c in data["current"]]
    assert "Stale - Song" not in [p["campaign"] for p in data["payments"]]


def test_blank_brief_reads_open_creative(client, db, seeded):
    with db.get_session() as s:
        s.query(Campaign).filter_by(slug="live").one().creator_brief = ""
        s.commit()
    card = client.post("/api/creator/dashboard", json={"token": seeded}).json["current"][0]
    assert card["brief"] == "Open creative" and card["open_creative"] is True


def test_dashboard_bad_token_is_uniform_404(client, seeded):
    resp = client.post("/api/creator/dashboard", json={"token": "x" * 43})
    assert resp.status_code == 404
    assert resp.json == {"error": payouts_bp_module._INVALID_LINK}


def test_set_creator_brief(client, db, seeded):
    resp = client.post("/api/campaign/live/creator-brief", json={"creator_brief": "  new brief  "})
    assert resp.status_code == 200 and resp.json["creator_brief"] == "new brief"
    assert client.get("/api/campaign/live").json["creator_brief"] == "new brief"
    assert client.post("/api/campaign/live/creator-brief", json={"creator_brief": 5}).status_code == 400
    assert client.post("/api/campaign/live/creator-brief", json={"creator_brief": "x" * 5001}).status_code == 400
    assert client.post("/api/campaign/nope/creator-brief", json={"creator_brief": "a"}).status_code == 404
