"""Creator rate evidence must belong to the platform being booked."""
from datetime import datetime

import pytest

from campaign_manager.models import Campaign, Creator, CreatorProfile
from campaign_manager.services.creator_library_view import build_library, rate_for_booking


def _history(session, order=("tiktok", "instagram")):
    values = {"tiktok": (100, 2, "2026-01-01"), "instagram": (900, 3, "2026-06-01")}
    for platform in order:
        total, posts, added = values[platform]
        campaign = Campaign(slug=f"history-{platform}", title=platform)
        session.add(campaign)
        session.flush()
        session.add(Creator(campaign_id=campaign.id, username="Shared", platform=platform,
                            total_rate=total, posts_owed=posts, added_date=added))
    session.commit()


@pytest.mark.parametrize("order", [("tiktok", "instagram"), ("instagram", "tiktok")])
def test_unscoped_rate_and_returned_platform_are_consistent_regardless_of_row_order(db, order):
    with db.get_session() as session:
        _history(session, order)
        row = build_library(session)[0]
        assert row["platform"] == "tiktok"
        assert row["rate"] == 50
        assert row["rate_source"] == "booking"
        assert row["last_booked_at"] == "2026-01-01"
        # Preserve the existing person-level historical totals.
        assert row["spend"] == 1000
        assert row["campaigns"] == 2
        quote = rate_for_booking(session, "@SHARED")
        assert quote["platform"] == "tiktok"
        assert quote["rate"] == quote["last_rate"] == 50


@pytest.mark.parametrize("platform,expected", [("tiktok", 50), ("instagram", 300)])
def test_explicit_platform_returns_its_own_booking_rate(db, client, platform, expected):
    with db.get_session() as session:
        _history(session)
        assert build_library(session, platform=platform)[0]["rate"] == expected
        assert rate_for_booking(session, "shared", platform=platform)["rate"] == expected
    response = client.get(f"/api/library/creators?platform={platform}")
    assert response.status_code == 200
    row = response.get_json()["creators"][0]
    assert row["platform"] == platform
    assert row["rate"] == expected
    quote = client.get(f"/api/library/creators/shared/rate?platform={platform}").get_json()
    assert quote["platform"] == platform
    assert quote["rate"] == expected


@pytest.mark.parametrize("profile_platform,other", [("instagram", "tiktok"), ("tiktok", "instagram")])
def test_manual_override_is_scoped_to_the_profile_platform(db, profile_platform, other):
    with db.get_session() as session:
        _history(session)
        session.add(CreatorProfile(username="shared", platform=profile_platform,
                                   rate_override=777, rate_override_at=datetime(2026, 7, 1)))
        session.commit()
        default = build_library(session)[0]
        assert default["platform"] == profile_platform
        assert default["rate"] == 777
        assert rate_for_booking(session, "shared")["rate"] == 777
        row = build_library(session, platform=other)[0]
        assert row["platform"] == other
        assert row["rate_override"] is None
        assert row["rate"] == (50 if other == "tiktok" else 300)
        quote = rate_for_booking(session, "shared", platform=other)
        assert quote["platform"] == other
        assert quote["source"] == "booking"
        assert quote["rate"] == row["rate"]


def test_other_platform_stats_are_not_used_for_projected_cpm(db):
    with db.get_session() as session:
        _history(session)
        session.add(CreatorProfile(username="shared", platform="instagram",
                                   stats={"w60": {"median": 100000, "p25": 50000}}))
        session.commit()
        row = build_library(session, platform="tiktok")[0]
        assert row["rate"] == 50
        assert not row["stats"].get("w60")


def test_platform_filter_does_not_offer_an_instagram_only_creator_as_tiktok(db, client):
    with db.get_session() as session:
        _history(session, order=("instagram",))
        assert build_library(session)[0]["platform"] == "instagram"
        assert build_library(session, platform="tiktok") == []
        quote = rate_for_booking(session, "shared", platform="tiktok")
        assert quote["platform"] == "tiktok"
        assert quote["rate"] is None
        assert quote["last_rate"] is None
    assert client.get("/api/library/creators?platform=tiktok").get_json()["creators"] == []


def test_scouted_profile_rate_only_appears_on_its_declared_platform(db):
    with db.get_session() as session:
        session.add(CreatorProfile(username="scouted", platform="instagram",
                                   rate_override=120, rate_override_at=datetime(2026, 2, 1)))
        session.commit()
        assert build_library(session)[0]["platform"] == "instagram"
        assert build_library(session, platform="instagram")[0]["rate"] == 120
        assert build_library(session, platform="tiktok") == []
        assert rate_for_booking(session, "scouted", platform="tiktok")["rate"] is None


def test_other_platform_newer_booking_cannot_supersede_a_manual_rate(db):
    with db.get_session() as session:
        _history(session)
        session.add(CreatorProfile(username="shared", platform="tiktok",
                                   rate_override=70, rate_override_at=datetime(2026, 2, 1)))
        session.commit()
        # The June Instagram booking must not supersede February's TikTok quote.
        assert rate_for_booking(session, "shared")["rate"] == 70
        assert build_library(session)[0]["rate"] == 70
        campaign = Campaign(slug="later-tiktok", title="later-tiktok")
        session.add(campaign)
        session.flush()
        session.add(Creator(campaign_id=campaign.id, username="shared", platform="tiktok",
                            total_rate=80, posts_owed=1, added_date="2026-07-01"))
        session.commit()
        quote = rate_for_booking(session, "shared")
        assert quote["rate"] == 80
        assert quote["source"] == "booking"


def test_explicit_zero_override_remains_zero_on_its_own_platform(db):
    with db.get_session() as session:
        _history(session)
        session.add(CreatorProfile(username="shared", platform="tiktok",
                                   rate_override=0, rate_override_at=datetime(2026, 7, 1)))
        session.commit()
        assert build_library(session, platform="tiktok")[0]["rate"] == 0
        assert rate_for_booking(session, "shared", platform="tiktok")["source"] == "override"
        assert rate_for_booking(session, "shared", platform="instagram")["rate"] == 300


def test_blank_profile_platform_does_not_override_available_platform_evidence(db):
    with db.get_session() as session:
        _history(session, order=("instagram",))
        session.add(CreatorProfile(username="shared", platform="", rate_override=777,
                                   rate_override_at=datetime(2026, 7, 1)))
        session.commit()
        row = build_library(session)[0]
        assert row["platform"] == "instagram"
        assert row["rate"] == 300
        assert row["rate_override"] is None


@pytest.mark.parametrize("path", ["/api/library/creators", "/api/library/creators/shared/rate"])
def test_invalid_platform_query_is_rejected(client, path):
    response = client.get(f"{path}?platform=youtube")
    assert response.status_code == 400
    assert "platform" in response.get_json()["error"]
