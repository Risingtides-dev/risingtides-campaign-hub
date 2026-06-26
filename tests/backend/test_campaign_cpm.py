"""Regression tests for CPM numerator semantics."""
from __future__ import annotations

from campaign_manager.blueprints.campaigns import _stats_from_result
from campaign_manager.services.campaign_stats import CampaignStatsResult
from campaign_manager.services.tides_tracker import Submission


def _seed_campaign(db):
    db.save_campaign(
        "gross_cpm",
        {
            "slug": "gross_cpm",
            "title": "Gross Artist - Gross Song",
            "artist": "Gross Artist",
            "song": "Gross Song",
            "budget": 1500,
            "status": "active",
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
