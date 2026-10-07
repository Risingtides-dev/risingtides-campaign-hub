"""Round reuse must not move or report posts from an earlier window."""
from types import SimpleNamespace

from campaign_manager.services import campaign_report, campaign_stats, scheduler


def test_internal_attach_selects_round_at_post_date(monkeypatch):
    campaigns = [
        {"slug": "r1", "sound_id": "123456", "start_date": "2026-04-01", "created_at": "2026-04-01"},
        {"slug": "r2", "sound_id": "123456", "start_date": "2026-05-01", "created_at": "2026-05-01"},
        {"slug": "invalid", "sound_id": "123456", "start_date": "2026-99-99", "created_at": "2026-06-01"},
    ]
    stored = {"r1": [], "r2": [{"url": "stored-r1", "timestamp": "2026-04-10T00:00:00", "views": 5000, "likes": 50}], "invalid": []}
    totals = {}
    monkeypatch.setattr(scheduler._db, "list_campaigns", lambda **kw: campaigns)
    monkeypatch.setattr(scheduler._db, "get_matched_videos", lambda slug: stored[slug])
    monkeypatch.setattr(scheduler._db, "replace_matched_videos", lambda slug, rows: stored.__setitem__(slug, rows))
    monkeypatch.setattr(scheduler._db, "update_campaign_stats", lambda slug, views, likes: totals.__setitem__(slug, (views, likes)))
    videos = [
        {"url": "r1-post", "music_id": "123456", "timestamp": "2026-04-15T12:00:00", "views": 100},
        {"url": "r2-post", "music_id": "123456", "upload_date": "20260515", "views": 200},
        {"url": "too-early", "music_id": "123456", "timestamp": "2026-03-15T12:00:00"},
        {"url": "undated", "music_id": "123456"},
        {"url": "bad-date", "music_id": "123456", "timestamp": "2026-99-99"},
    ]
    result = scheduler._attach_internal_to_campaigns(videos)
    assert {slug: [v["url"] for v in rows] for slug, rows in stored.items()} == {
        "r1": ["r1-post"], "r2": ["stored-r1", "r2-post"], "invalid": [],
    }
    assert result["attached_count"] == 2
    assert result["skipped_no_active_campaign"] == 3
    assert totals == {"r1": (100, 0), "r2": (200, 0)}


def test_report_filters_historical_and_undated_rows_from_all_totals(monkeypatch):
    rows = [
        {"url": "r1-post", "account": "@creator", "timestamp": "2026-04-15T12:00:00", "views": 100, "likes": 10},
        {"url": "r2-post", "account": "@creator", "upload_date": "20260515", "views": 200, "likes": 20},
        {"url": "undated", "account": "@creator", "views": 300, "likes": 30},
        {"url": "bad-date", "account": "@creator", "timestamp": "bad", "views": 400, "likes": 40},
    ]
    from campaign_manager import db
    monkeypatch.setattr(db, "is_active", lambda: True)
    meta = {"title": "Round 2", "start_date": "2026-05-01", "cobrand_share_url": "share"}
    monkeypatch.setattr(db, "get_campaign", lambda slug: {"slug": slug, **meta})
    monkeypatch.setattr(db, "get_creators", lambda slug: [{"username": "creator"}])
    monkeypatch.setattr(db, "get_matched_videos", lambda slug: rows)
    monkeypatch.setattr(campaign_stats, "get_campaign_stats", lambda *a, **kw: SimpleNamespace(submissions=[], source="scraper_fallback", stale_since=""))
    monkeypatch.setattr(campaign_stats, "overlay_video_stats", lambda matched, _: matched)
    from campaign_manager.services import cobrand_outcomes
    monkeypatch.setattr(cobrand_outcomes, "fetch_submissions", lambda _: [
        {"url": "r1-post", "username": "creator", "shares": 100, "comments": 100},
        {"url": "r2-post", "username": "creator", "shares": 2, "comments": 3},
    ])
    report = campaign_report.build_report("r2")
    assert report["headline"] == {"total_views": 200, "total_likes": 20, "post_count": 1, "creator_count": 1}
    assert [p["url"] for p in report["top_posts"]] == ["r2-post"]
    assert report["creators"] == [{"username": "creator", "posts": 1, "views": 200, "likes": 20, "shares": 2, "comments": 3}]

    meta["start_date"] = "2026-99-99"
    invalid = campaign_report.build_report("r2")
    assert invalid["headline"]["post_count"] == 0
    assert invalid["creators"][0]["shares"] == 0

    meta["start_date"] = ""
    legacy = campaign_report.build_report("r2")
    assert legacy["headline"]["post_count"] == 4
    assert legacy["creators"][0]["shares"] == 102
