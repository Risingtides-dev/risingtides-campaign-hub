"""GET /api/last-rate/<username> — pre-fills a creator's last booked rate."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def _create(client, title):
    return client.post("/api/campaign/create", json={"title": title, "budget": 5000})


def _add(client, slug, username, total_rate, posts_owed=2):
    return client.post(
        f"/api/campaign/{slug}/creator/add",
        json={"username": username, "posts_owed": posts_owed, "total_rate": total_rate},
    )


def _set_added_date(db, username, slug, added_date):
    from campaign_manager.models import Campaign, Creator
    with db.get_session() as s:
        cid = s.query(Campaign.id).filter_by(slug=slug).scalar()
        s.query(Creator).filter_by(campaign_id=cid, username=username).update(
            {"added_date": added_date}
        )
        s.commit()


class TestLastRate:
    def test_unknown_creator_returns_null(self, client):
        resp = client.get("/api/last-rate/nobody")
        assert resp.status_code == 200
        assert resp.get_json() == {"last_rate": None}

    def test_returns_rate_posts_and_campaign(self, client):
        _create(client, "Sam Barber - Fever Dream")
        _add(client, "sam_barber_fever_dream", "beaujenkins", 300, posts_owed=3)

        last = client.get("/api/last-rate/beaujenkins").get_json()["last_rate"]
        assert last["total_rate"] == 300
        assert last["posts_owed"] == 3
        assert last["campaign"] == "Sam Barber - Fever Dream"

    def test_most_recent_booking_wins(self, client, db):
        _create(client, "Old Artist - Old Song")
        _create(client, "New Artist - New Song")
        _add(client, "old_artist_old_song", "beaujenkins", 200)
        _add(client, "new_artist_new_song", "beaujenkins", 450)
        _set_added_date(db, "beaujenkins", "old_artist_old_song", "2026-08-01")
        _set_added_date(db, "beaujenkins", "new_artist_new_song", "2026-09-10")

        last = client.get("/api/last-rate/beaujenkins").get_json()["last_rate"]
        assert last["total_rate"] == 450
        assert last["campaign"] == "New Artist - New Song"

    def test_edited_rate_is_remembered(self, client):
        _create(client, "Sam Barber - Fever Dream")
        _add(client, "sam_barber_fever_dream", "beaujenkins", 300)
        client.post(
            "/api/campaign/sam_barber_fever_dream/creator/beaujenkins/edit",
            json={"posts_owed": 2, "total_rate": 350},
        )

        last = client.get("/api/last-rate/beaujenkins").get_json()["last_rate"]
        assert last["total_rate"] == 350

    def test_lookup_is_case_insensitive_and_strips_at(self, client):
        _create(client, "Sam Barber - Fever Dream")
        _add(client, "sam_barber_fever_dream", "BeauJenkins", 300)

        last = client.get("/api/last-rate/@beaujenkins").get_json()["last_rate"]
        assert last["total_rate"] == 300

    def test_zero_rate_bookings_are_skipped(self, client, db):
        _create(client, "Old Artist - Old Song")
        _create(client, "New Artist - New Song")
        _add(client, "old_artist_old_song", "beaujenkins", 250)
        _add(client, "new_artist_new_song", "beaujenkins", 0)
        _set_added_date(db, "beaujenkins", "old_artist_old_song", "2026-08-01")
        _set_added_date(db, "beaujenkins", "new_artist_new_song", "2026-09-10")

        last = client.get("/api/last-rate/beaujenkins").get_json()["last_rate"]
        assert last["total_rate"] == 250

    def test_removed_bookings_are_skipped(self, client):
        _create(client, "Sam Barber - Fever Dream")
        _add(client, "sam_barber_fever_dream", "beaujenkins", 300)
        client.post("/api/campaign/sam_barber_fever_dream/creator/beaujenkins/remove")

        assert client.get("/api/last-rate/beaujenkins").get_json() == {"last_rate": None}


class TestLastRatePlatform:
    """Platform isolation — TikTok rates must not pre-fill Instagram forms."""

    def test_platform_tiktok_returns_tiktok_booking(self, client):
        _create(client, "TT Campaign")
        client.post(
            "/api/campaign/tt_campaign/creator/add",
            json={"username": "jetblue", "posts_owed": 2, "total_rate": 400, "platform": "tiktok"},
        )
        last = client.get("/api/last-rate/jetblue?platform=tiktok").get_json()["last_rate"]
        assert last is not None
        assert last["total_rate"] == 400

    def test_platform_instagram_returns_instagram_booking(self, client):
        _create(client, "IG Campaign")
        client.post(
            "/api/campaign/ig_campaign/creator/add",
            json={"username": "jetblue", "posts_owed": 1, "total_rate": 250, "platform": "instagram"},
        )
        last = client.get("/api/last-rate/jetblue?platform=instagram").get_json()["last_rate"]
        assert last is not None
        assert last["total_rate"] == 250

    def test_platform_filter_excludes_other_platform(self, client, db):
        """A creator with only a TikTok booking gets null when queried for Instagram."""
        _create(client, "TT Only")
        client.post(
            "/api/campaign/tt_only/creator/add",
            json={"username": "jetblue", "posts_owed": 2, "total_rate": 400, "platform": "tiktok"},
        )
        last = client.get("/api/last-rate/jetblue?platform=instagram").get_json()["last_rate"]
        assert last is None

    def test_no_platform_param_returns_most_recent_across_platforms(self, client, db):
        """Legacy callers without ?platform= still get the most recent booking."""
        _create(client, "TT Old")
        _create(client, "IG New")
        client.post(
            "/api/campaign/tt_old/creator/add",
            json={"username": "jetblue", "posts_owed": 2, "total_rate": 300, "platform": "tiktok"},
        )
        client.post(
            "/api/campaign/ig_new/creator/add",
            json={"username": "jetblue", "posts_owed": 1, "total_rate": 350, "platform": "instagram"},
        )
        _set_added_date(db, "jetblue", "tt_old", "2026-08-01")
        _set_added_date(db, "jetblue", "ig_new", "2026-09-10")

        last = client.get("/api/last-rate/jetblue").get_json()["last_rate"]
        assert last["total_rate"] == 350

    def test_platform_most_recent_within_platform_wins(self, client, db):
        """When multiple bookings exist for the same platform, most recent wins."""
        _create(client, "TT Old Campaign")
        _create(client, "TT New Campaign")
        client.post(
            "/api/campaign/tt_old_campaign/creator/add",
            json={"username": "jetblue", "posts_owed": 2, "total_rate": 200, "platform": "tiktok"},
        )
        client.post(
            "/api/campaign/tt_new_campaign/creator/add",
            json={"username": "jetblue", "posts_owed": 3, "total_rate": 500, "platform": "tiktok"},
        )
        _set_added_date(db, "jetblue", "tt_old_campaign", "2026-07-01")
        _set_added_date(db, "jetblue", "tt_new_campaign", "2026-09-15")

        last = client.get("/api/last-rate/jetblue?platform=tiktok").get_json()["last_rate"]
        assert last["total_rate"] == 500
