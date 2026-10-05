"""Regression tests for CPM numerator semantics."""
from __future__ import annotations

import pytest

from campaign_manager.blueprints.campaigns import _stats_from_result, load_creators
from campaign_manager.models import Creator
from campaign_manager.services.campaign_stats import CampaignStatsResult
from campaign_manager.services.tides_tracker import Submission
from campaign_manager.utils.budget import creator_rates_complete


def _seed_campaign(db):
    db.save_campaign(
        "gross_cpm",
        {
            "slug": "gross_cpm",
            "title": "Gross Artist - Gross Song",
            "artist": "Gross Artist",
            "song": "Gross Song",
            "budget": 1500,
            "completion_status": "completed",
            "stats": {"total_views": 100_000, "total_likes": 0},
        },
    )
    db.save_creators(
        "gross_cpm",
        [{"username": "alice", "posts_owed": 1, "posts_done": 1, "total_rate": 1500}],
    )
    db.save_matched_videos(
        "gross_cpm",
        [{"url": "https://tt.example/v/1", "account": "@alice", "views": 100_000}],
    )


def test_tides_tracker_campaign_cpm_uses_gross_client_spend():
    result = CampaignStatsResult(
        slug="gross_cpm",
        source="api",
        submissions=[Submission(video_url="https://tt.example/v/1", views=100_000)],
    )

    stats = _stats_from_result(
        {"budget": 1500},
        [{"username": "alice", "total_rate": 1500}],
        result,
    )

    assert stats["cpm"] == 30.0


def test_creator_list_avg_cpm_uses_gross_client_spend(client, db):
    _seed_campaign(db)

    rows = client.get("/api/creators").get_json()

    alice = next(r for r in rows if r["username"] == "alice")
    assert alice["total_spend"] == 1500.0
    assert alice["avg_cpm"] == 30.0


def test_creator_profile_avg_cpm_uses_gross_client_spend(client, db):
    _seed_campaign(db)

    profile = client.get("/api/creators/alice").get_json()

    assert profile["stats"]["total_spend"] == 1500.0
    assert profile["stats"]["avg_cpm"] == 30.0


@pytest.mark.parametrize("unknown_rate", [None, "", "  ", "TBD", "n/a", "None"])
def test_unknown_rate_suppresses_campaign_cpm_without_breaking_stats(unknown_rate):
    result = CampaignStatsResult(
        slug="partial_cpm",
        source="api",
        submissions=[Submission(video_url="https://tt.example/v/1", views=100_000)],
    )

    stats = _stats_from_result(
        {"budget": 1500},
        [
            {"username": "alice", "total_rate": 500},
            {"username": "bob", "total_rate": unknown_rate},
        ],
        result,
    )

    assert stats["total_views"] == 100_000
    assert stats["cpm"] is None


def test_missing_rate_is_unknown_but_explicit_zero_is_known():
    assert not creator_rates_complete([{"username": "alice"}])
    assert not creator_rates_complete([{"username": "alice", "total_rate": None}])
    assert creator_rates_complete([{"username": "alice", "total_rate": 0}])


def test_file_creator_rates_keep_quality_and_tolerate_import_placeholders(tmp_path):
    (tmp_path / "creators.csv").write_text(
        "username,total_rate\nalice,0\nbob,TBD\ncarol,\ndave,n/a\n",
        encoding="utf-8",
    )

    rows = load_creators(tmp_path, include_rate_quality=True)

    assert [row["total_rate"] for row in rows] == [0.0, 0.0, 0.0, 0.0]
    assert [row["_total_rate_known"] for row in rows] == [True, False, False, False]


def test_legacy_campaign_dashboard_suppresses_unknown_rate_cpm():
    from campaign_manager.web_dashboard import calc_stats as legacy_calc_stats

    stats = legacy_calc_stats(
        {"stats": {"total_views": 100_000}},
        [
            {"username": "alice", "total_rate": 500},
            {"username": "bob", "total_rate": "TBD"},
        ],
    )

    assert stats["total_views"] == 100_000
    assert stats["cpm"] is None


def test_database_null_rate_suppresses_campaign_and_creator_cpms(client, db):
    _seed_campaign(db)
    with db.get_session() as session:
        creator = session.query(Creator).filter_by(username="alice").one()
        creator.total_rate = None
        session.commit()

    campaign = client.get("/api/campaign/gross_cpm").get_json()
    creator_rows = client.get("/api/creators").get_json()
    profile = client.get("/api/creators/alice").get_json()

    alice = next(row for row in creator_rows if row["username"] == "alice")
    assert campaign["stats"]["cpm"] is None
    assert "_total_rate_known" not in campaign["creators"][0]
    assert alice["avg_cpm"] is None
    assert alice["total_spend"] == 0.0
    assert profile["stats"]["avg_cpm"] is None


@pytest.mark.parametrize("nonfinite_rate", [float("nan"), float("inf"), float("-inf")])
def test_database_nonfinite_rate_is_unknown_alongside_valid_booking(nonfinite_rate, db):
    _seed_campaign(db)
    with db.get_session() as session:
        alice = session.query(Creator).filter_by(username="alice").one()
        alice.total_rate = nonfinite_rate
        session.add(Creator(
            campaign_id=alice.campaign_id,
            username="bob",
            total_rate=250,
            platform="instagram",
        ))
        session.commit()

    _meta, creators, _videos = db.list_campaigns_with_creators(
        include_rate_quality=True,
    )[0]
    quality = {row["username"]: row["_total_rate_known"] for row in creators}
    result = CampaignStatsResult(
        slug="gross_cpm",
        source="api",
        submissions=[Submission(video_url="https://tt.example/v/1", views=100_000)],
    )
    stats = _stats_from_result({}, creators, result)

    assert quality == {"alice": False, "bob": True}
    assert stats["cpm"] is None


def test_creator_profile_sums_platform_booking_rates_but_deduplicates_posts_and_views(client, db):
    _seed_campaign(db)
    db.save_creators("gross_cpm", [
        {
            "username": "alice", "posts_owed": 2, "posts_done": 1,
            "total_rate": 500, "paid": "yes", "platform": "tiktok",
        },
        {
            "username": "alice", "posts_owed": 2, "posts_done": 1,
            "total_rate": 700, "paid": "no", "platform": "instagram",
        },
    ])

    profile = client.get("/api/creators/alice").get_json()

    assert profile["stats"]["total_spend"] == 1200.0
    assert profile["stats"]["total_payout"] == 500.0
    assert profile["stats"]["total_posts_owed"] == 2
    assert profile["stats"]["total_posts_done"] == 1
    assert profile["stats"]["total_views"] == 100_000
    assert profile["stats"]["avg_cpm"] == 24.0
    assert profile["campaigns"][0]["total_rate"] == 1200.0
