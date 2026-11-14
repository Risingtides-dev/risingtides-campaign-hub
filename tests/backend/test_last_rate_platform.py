"""Manual creator entry must not prefill another platform's booking price."""
import pytest

from campaign_manager.models import Campaign, Creator


def _seed(db, rows):
    with db.get_session() as session:
        for index, row in enumerate(rows):
            campaign = Campaign(slug=f"price-{index}", title=f"Price {index}")
            session.add(campaign)
            session.flush()
            session.add(Creator(campaign_id=campaign.id, **row))
        session.commit()


def _row(platform="tiktok", username="shared", rate=100, added="2026-01-01", status="active"):
    return dict(username=username, platform=platform, total_rate=rate,
                posts_owed=2, added_date=added, status=status)


def test_scoped_last_rate_cannot_use_newer_booking_on_other_platform(db, client):
    _seed(db, [_row(), _row(platform="instagram", rate=900, added="2026-06-01")])
    tiktok = client.get("/api/last-rate/shared?platform=tiktok").get_json()["last_rate"]
    instagram = client.get("/api/last-rate/shared?platform=instagram").get_json()["last_rate"]
    assert tiktok["total_rate"] == 100
    assert tiktok["platform"] == "tiktok"
    assert instagram["total_rate"] == 900
    assert instagram["platform"] == "instagram"


@pytest.mark.parametrize("stored,requested", [(" @ShArEd ", "SHARED"), ("@@Shared", " @shared "),
                                             ("\t@Shared\n", "SHARED")])
def test_lookup_normalizes_stored_and_requested_handle(db, stored, requested):
    _seed(db, [_row(username=stored)])
    last = db.get_last_rate(requested)
    assert last is not None
    assert last["total_rate"] == 100


def test_unscoped_last_rate_keeps_legacy_newest_booking_behavior(db, client):
    _seed(db, [_row(), _row(platform="instagram", rate=900, added="2026-06-01")])
    last = client.get("/api/last-rate/shared").get_json()["last_rate"]
    assert last["total_rate"] == 900
    assert last["posts_owed"] == 2
    assert last["campaign"] == "Price 1"
    assert last["added_date"] == "2026-06-01"


def test_missing_scoped_platform_has_no_rate(db, client):
    _seed(db, [_row(platform="instagram", rate=900)])
    assert client.get("/api/last-rate/shared?platform=tiktok").get_json() == {"last_rate": None}


def test_scoped_lookup_still_skips_removed_and_zero_rate_rows(db, client):
    _seed(db, [_row(), _row(rate=0, added="2026-02-01"),
               _row(rate=200, added="2026-03-01", status="removed"),
               _row(platform="instagram", rate=900, added="2026-06-01")])
    assert client.get("/api/last-rate/shared?platform=tiktok").get_json()["last_rate"]["total_rate"] == 100


def test_scoped_platform_normalization_matches_legacy_blank_platform(db, client):
    _seed(db, [_row(platform="")])
    response = client.get("/api/last-rate/shared?platform=%20TikTok%20")
    assert response.status_code == 200
    assert response.get_json()["last_rate"]["platform"] == "tiktok"


@pytest.mark.parametrize("platform", ["youtube", ""])
def test_invalid_platform_is_rejected_before_database_access(client, monkeypatch, platform):
    from campaign_manager.blueprints import campaigns
    monkeypatch.setattr(campaigns._db, "is_active", lambda: pytest.fail("database consulted before validation"))
    response = client.get(f"/api/last-rate/shared?platform={platform}")
    assert response.status_code == 400
    assert "platform" in response.get_json()["error"]
