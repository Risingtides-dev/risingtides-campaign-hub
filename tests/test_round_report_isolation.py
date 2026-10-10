"""Round reuse must not move or report posts from an earlier window."""
from datetime import date
from types import SimpleNamespace

import pytest

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

    # An already-matched URL must still repair stale campaign-level totals.
    totals["r2"] = (5200, 50)
    again = scheduler._attach_internal_to_campaigns([videos[1]])
    assert again["attached_count"] == 0
    assert totals["r2"] == (200, 0)


def test_report_filters_historical_and_undated_rows_from_all_totals(monkeypatch):
    rows = [
        {"url": "r1-post", "account": "@creator", "timestamp": "2026-04-15T12:00:00", "views": 100, "likes": 10},
        {"url": "r2-post", "account": "@creator", "upload_date": "20260515", "views": 200, "likes": 20},
        {"url": "undated", "account": "@creator", "views": 300, "likes": 30},
        {"url": "bad-date", "account": "@creator", "timestamp": "bad", "views": 400, "likes": 40},
    ]
    from campaign_manager import db
    monkeypatch.setattr(db, "is_active", lambda: True)
    meta = {"title": "Round 2", "sound_id": "123456789012345", "start_date": "2026-05-01", "cobrand_share_url": "share"}
    monkeypatch.setattr(db, "get_campaign", lambda slug: {"slug": slug, **meta})
    monkeypatch.setattr(db, "list_campaigns", lambda **kw: [
        {"slug": "r1", "sound_id": "123456789012345", "start_date": "2026-04-01"},
        {"slug": "r2", "sound_id": "123456789012345", "start_date": "2026-05-01"},
    ])
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

    meta["start_date"] = "2026-04-01"
    first_round = campaign_report.build_report("r1")
    assert first_round["headline"] == {"total_views": 100, "total_likes": 10, "post_count": 1, "creator_count": 1}
    assert first_round["creators"][0]["shares"] == 100

    secondary = {"url": "secondary", "account": "@creator", "music_id": "222222222222222",
                 "upload_date": "20260520", "views": 30, "likes": 3}
    rows.append(secondary)
    monkeypatch.setattr(db, "list_campaigns", lambda **kw: [
        {"slug": "r1", "sound_id": "123456789012345", "additional_sounds": ["222222222222222"],
         "start_date": "2026-04-01"},
        {"slug": "r2", "sound_id": "123456789012345", "start_date": "2026-05-01"},
    ])
    partial = campaign_report.build_report("r1")
    assert partial["headline"] == {"total_views": 130, "total_likes": 13, "post_count": 2, "creator_count": 1}
    assert {post["url"] for post in partial["top_posts"]} == {"r1-post", "secondary"}
    rows.pop()

    meta["start_date"] = "2026-05-01"

    meta["start_date"] = "2026-99-99"
    invalid = campaign_report.build_report("r2")
    assert invalid["headline"]["post_count"] == 0
    assert invalid["creators"][0]["shares"] == 0

    meta["start_date"] = ""
    legacy = campaign_report.build_report("r2")
    assert legacy["headline"]["post_count"] == 4
    assert legacy["creators"][0]["shares"] == 102


def test_round_scoped_cobrand_outcomes_never_join_on_empty_url(monkeypatch):
    from campaign_manager.services import cobrand_outcomes

    monkeypatch.setattr(cobrand_outcomes, "fetch_submissions", lambda _: [
        {"url": "", "username": "creator", "shares": 99, "comments": 33},
        {"url": "r2-post", "username": "creator", "shares": 2, "comments": 3},
    ])
    rows = campaign_report._per_creator(
        [
            {"url": "", "account": "@creator", "views": 10},
            {"url": "r2-post", "account": "@creator", "views": 20},
        ],
        [{"username": "creator"}],
        "share",
        round_scoped=True,
    )
    assert rows == [{"username": "creator", "posts": 2, "views": 30, "likes": 0, "shares": 2, "comments": 3}]


def test_scheduled_refresh_scopes_stats_and_creator_counts(monkeypatch, caplog):
    from campaign_manager.services import matching, tracker_discovery

    old = {"url": "old", "account": "@creator", "timestamp": "2026-04-15T10:00:00", "views": 900, "likes": 90, "shares": 9}
    current = {"url": "current", "account": "@creator", "timestamp": "2026-05-15T10:00:00", "views": 20, "likes": 2, "shares": 1}
    persisted = [old, current]
    creators = [{"username": "creator", "platform": "tiktok", "status": "active"}]
    writes = {}
    monkeypatch.setattr(scheduler, "_import_scraper", lambda: (None, lambda *a: None))
    monkeypatch.setattr(scheduler._db, "get_creators", lambda slug: creators)
    monkeypatch.setattr(scheduler._db, "get_matched_videos", lambda slug: persisted)
    monkeypatch.setattr(scheduler._db, "replace_matched_videos", lambda slug, rows: writes.__setitem__("stored", rows))
    monkeypatch.setattr(scheduler._db, "save_creators", lambda slug, rows: writes.__setitem__("creators", rows))
    monkeypatch.setattr(scheduler._db, "update_campaign_stats", lambda slug, views, likes: writes.__setitem__("totals", (views, likes)))
    monkeypatch.setattr(scheduler._db, "save_scrape_log", lambda slug, row: writes.__setitem__("log", row))
    monkeypatch.setattr(matching, "match_videos", lambda videos, *args, **kw: videos)
    monkeypatch.setattr(matching, "discover_original_sounds", lambda *args, **kw: ([], []))
    monkeypatch.setattr(tracker_discovery, "find_trackers_for_campaign", lambda meta: [])
    result = scheduler._refresh_single_campaign(
        "r2", {"sound_id": "123456789012345", "start_date": "2026-05-01"},
        shared_videos={"creator": [old, current]},
    )
    assert result["total_matches"] == 1
    assert writes["totals"] == (20, 2)
    assert writes["creators"][0]["posts_done"] == 1
    assert writes["log"]["total_matches"] == 1
    assert "stats snapshot failed" not in caplog.text
    assert {v["url"] for v in writes["stored"]} == {"old", "current"}

    writes.clear()
    secondary = {"url": "secondary", "account": "@creator", "music_id": "222222222222222",
                 "timestamp": "2026-05-15T10:00:00", "views": 30, "likes": 3, "shares": 2}
    persisted.append(secondary)
    first_round = scheduler._refresh_single_campaign(
        "r1", {"sound_id": "123456789012345", "additional_sounds": ["222222222222222"],
               "start_date": "2026-04-01"},
        shared_videos={"creator": [old, current, secondary]},
        round_end={"123456789012345": date(2026, 5, 1), "222222222222222": None},
    )
    assert first_round["total_matches"] == 2
    assert writes["totals"] == (930, 93)


def test_manual_refresh_scopes_existing_rows_and_response(monkeypatch):
    from flask import Flask
    from campaign_manager.blueprints import campaigns
    from campaign_manager.services import matching
    from src.scrapers import master_tracker

    old = {"url": "old", "account": "@creator", "timestamp": "2026-04-15T10:00:00", "views": 900, "likes": 90}
    current = {"url": "current", "account": "@creator", "timestamp": "2026-05-15T10:00:00", "views": 20, "likes": 2}
    persisted = [old, current]
    writes = {}
    meta = {"sound_id": "123456789012345", "start_date": "2026-05-01", "song": "Song", "artist": "Artist", "stats": {}}
    monkeypatch.setattr(campaigns._db, "is_active", lambda: True)
    monkeypatch.setattr(campaigns._db, "get_campaign", lambda slug: meta)
    monkeypatch.setattr(campaigns._db, "list_campaigns", lambda **kw: [
        {"slug": "r1", "sound_id": "123456789012345", "start_date": "2026-04-01"},
        {"slug": "r2", "sound_id": "123456789012345", "start_date": "2026-05-01"},
    ])
    monkeypatch.setattr(campaigns._db, "get_creators", lambda slug: [{"username": "creator", "platform": "tiktok", "status": "active"}])
    monkeypatch.setattr(campaigns._db, "get_matched_videos", lambda slug: persisted)
    monkeypatch.setattr(campaigns._db, "replace_matched_videos", lambda slug, rows: writes.__setitem__("stored", rows))
    monkeypatch.setattr(campaigns._db, "update_campaign_fields", lambda slug, fields: writes.__setitem__("fields", fields))
    monkeypatch.setattr(campaigns._db, "save_creators", lambda slug, rows: writes.__setitem__("creators", rows))
    monkeypatch.setattr(campaigns._db, "save_scrape_log", lambda slug, row: writes.__setitem__("log", row))
    monkeypatch.setattr(master_tracker, "scrape_tiktok_account", lambda *args, **kw: persisted)
    monkeypatch.setattr(matching, "match_videos", lambda videos, *args, **kw: videos)
    app = Flask(__name__)
    app.register_blueprint(campaigns.campaigns_bp)
    with app.test_client() as client:
        response = client.post("/api/campaign/r2/refresh")
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["total_matches"] == 1
    assert (body["total_views"], body["total_likes"]) == (20, 2)
    assert writes["fields"]["total_views"] == 20
    assert writes["creators"][0]["posts_done"] == 1
    assert writes["log"]["total_matches"] == 1
    assert {v["url"] for v in writes["stored"]} == {"old", "current"}

    meta["start_date"] = "2026-04-01"
    meta["additional_sounds"] = ["222222222222222"]
    persisted.append({"url": "secondary", "account": "@creator", "music_id": "222222222222222",
                      "timestamp": "2026-05-15T10:00:00", "views": 30, "likes": 3})
    roster = [
        {"slug": "r1", "sound_id": "123456789012345", "additional_sounds": ["222222222222222"],
         "start_date": "2026-04-01"},
        {"slug": "r2", "sound_id": "123456789012345", "start_date": "2026-05-01"},
    ]
    monkeypatch.setattr(campaigns._db, "list_campaigns", lambda **kw: roster)
    with app.test_client() as client:
        first_round = client.post("/api/campaign/r1/refresh")
    assert first_round.status_code == 200, first_round.get_json()
    assert (first_round.get_json()["total_views"], first_round.get_json()["total_matches"]) == (930, 2)


def test_no_active_creators_reconciles_dated_totals_without_faking_scrape(monkeypatch):
    videos = [
        {"url": "old", "account": "@creator", "timestamp": "2026-04-10T00:00:00", "views": 900, "likes": 90},
        {"url": "current", "account": "@creator", "timestamp": "2026-05-10T00:00:00", "views": 20, "likes": 2},
        {"url": "undated", "account": "@creator", "views": 500, "likes": 50},
        {"url": "dismissed", "account": "@creator", "timestamp": "2026-05-11T00:00:00", "views": 700, "likes": 70, "dismissed_at": "2026-05-12"},
    ]
    writes = {}
    monkeypatch.setattr(scheduler, "_import_scraper", lambda: (None, None))
    monkeypatch.setattr(scheduler._db, "get_creators", lambda slug: [{"username": "creator", "status": "removed", "platform": "tiktok"}])
    monkeypatch.setattr(scheduler._db, "get_matched_videos", lambda slug: videos)
    monkeypatch.setattr(scheduler._db, "save_creators", lambda slug, rows: writes.__setitem__("creators", rows))
    monkeypatch.setattr(scheduler._db, "update_campaign_fields", lambda slug, fields: writes.__setitem__("fields", fields))
    monkeypatch.setattr(scheduler._db, "update_campaign_stats", lambda *args: (_ for _ in ()).throw(AssertionError("no scrape timestamp")))
    monkeypatch.setattr(scheduler._db, "save_scrape_log", lambda *args: (_ for _ in ()).throw(AssertionError("no scrape log")))

    result = scheduler._refresh_single_campaign(
        "r2", {"sound_id": "123456789012345", "start_date": "2026-05-01"},
        shared_videos={},
    )
    assert result == {"new_matches": 0, "total_matches": 1, "videos_checked": 0}
    assert writes["fields"] == {"total_views": 20, "total_likes": 2}
    assert writes["creators"][0]["posts_done"] == 1
    assert len(videos) == 4  # history was not deleted

    writes.clear()
    legacy = scheduler._refresh_single_campaign(
        "legacy", {"sound_id": "123456789012345", "start_date": ""},
        shared_videos={},
    )
    assert legacy["total_matches"] == 4
    assert writes == {}  # no-start early return keeps its prior no-write behavior


def test_round_end_includes_completed_later_round_and_same_day_tie():
    from campaign_manager.utils.helpers import build_round_end_by_slug, round_qualified_videos

    roster = [
        {"slug": "r1", "sound_id": "123456", "start_date": "2026-04-01", "created_at": "2026-04-01"},
        {"slug": "r2", "additional_sounds": ["123456"], "start_date": "2026-05-01", "created_at": "2026-05-01", "completion_status": "completed"},
        {"slug": "same-a", "sound_id": "789012", "start_date": "2026-06-01", "created_at": "2026-05-01"},
        {"slug": "same-b", "sound_id": "789012", "start_date": "2026-06-01", "created_at": "2026-05-02"},
        {"slug": "unrelated", "sound_id": "999999", "start_date": "2026-03-01"},
    ]
    ends = build_round_end_by_slug(roster)
    assert ends["r1"] == {"123456": date(2026, 5, 1)}
    assert ends["same-a"] == {"789012": date(2026, 6, 1)}
    videos = [
        {"timestamp": "2026-04-30T23:59:59"},
        {"timestamp": "2026-05-01T00:00:00"},
    ]
    assert round_qualified_videos(videos, "2026-04-01", end_date=ends["r1"]) == [videos[0]]
    assert round_qualified_videos(videos, "") == videos


def test_partial_sound_overlap_keeps_identified_secondary_post(caplog):
    from campaign_manager.utils.helpers import build_round_end_by_slug, round_qualified_videos, _ambiguous_post_ref
    roster = [
        {"slug": "r1", "sound_id": "111111", "additional_sounds": ["222222"], "start_date": "2026-04-01"},
        {"slug": "r2", "sound_id": "111111", "start_date": "2026-05-01"},
    ]
    window = build_round_end_by_slug(roster)["r1"]
    assert window == {"111111": date(2026, 5, 1), "222222": None}
    rows = [
        {"url": "primary-old", "music_id": "111111", "upload_date": "20260420"},
        {"url": "primary-new", "music_id": "111111", "upload_date": "20260515"},
        {"url": "secondary-new", "music_id": "222222", "upload_date": "20260515"},
        {"url": "https://example.com/unknown-new?token=private-secret", "upload_date": "20260515"},
        {"url": "foreign-new", "music_id": "333333", "upload_date": "20260515"},
    ]
    assert [row["url"] for row in round_qualified_videos(rows, "2026-04-01", end_date=window)] == [
        "primary-old", "secondary-new",
    ]
    assert _ambiguous_post_ref(rows[3]) in caplog.text
    assert _ambiguous_post_ref(rows[4]) in caplog.text
    assert "private-secret" not in caplog.text
    assert "https://example.com/unknown-new" not in caplog.text


def test_internal_attach_does_not_fall_back_to_earlier_active_round_after_later_completed(monkeypatch):
    roster = [
        {"slug": "r1", "sound_id": "123456", "start_date": "2026-04-01", "completion_status": "none"},
        {"slug": "r2", "sound_id": "123456", "start_date": "2026-05-01", "completion_status": "completed"},
    ]
    writes = []
    monkeypatch.setattr(scheduler._db, "list_campaigns", lambda **kw: roster)
    monkeypatch.setattr(scheduler._db, "get_matched_videos", lambda slug: [])
    monkeypatch.setattr(scheduler._db, "replace_matched_videos", lambda slug, rows: writes.append((slug, rows)))
    result = scheduler._attach_internal_to_campaigns([
        {"url": "late", "music_id": "123456", "timestamp": "2026-05-15T00:00:00"},
    ])
    assert result["attached_count"] == 0
    assert result["skipped_no_active_campaign"] == 1
    assert writes == []


@pytest.mark.parametrize("date_fields", [
    {},
    {"timestamp": "2026-99-99"},
    {"timestamp": "bad", "upload_date": "20261340"},
])
@pytest.mark.parametrize("mixed_rounds", [False, True])
def test_internal_attach_unknown_date_retains_no_start_campaigns(monkeypatch, date_fields, mixed_rounds):
    campaigns = [{"slug": "legacy-z", "sound_id": "123456", "created_at": "2026-06-01"}]
    if mixed_rounds:
        campaigns += [
            {"slug": "legacy-old", "sound_id": "123456", "start_date": None, "created_at": "2026-05-01"},
            {"slug": "legacy-a", "sound_id": "123456", "start_date": "  ", "created_at": "2026-06-01"},
            {"slug": "dated", "sound_id": "123456", "start_date": "2026-07-01", "created_at": "2026-07-01"},
            {"slug": "invalid", "sound_id": "123456", "start_date": "bad", "created_at": "2026-08-01"},
            {"slug": "completed", "sound_id": "123456", "created_at": "2026-09-01", "completion_status": "completed"},
            {"slug": "other-sound", "sound_id": "654321", "created_at": "2026-10-01"},
        ]
    existing = {"url": "retained", "music_id": "123456", "views": 10, "likes": 2}
    stored = {c["slug"]: [dict(existing)] for c in campaigns}
    totals = {}
    monkeypatch.setattr(scheduler._db, "list_campaigns", lambda **kw: campaigns)
    monkeypatch.setattr(scheduler._db, "get_matched_videos", lambda slug: stored[slug])
    monkeypatch.setattr(scheduler._db, "replace_matched_videos", lambda slug, rows: stored.__setitem__(slug, rows))
    monkeypatch.setattr(scheduler._db, "update_campaign_stats", lambda slug, views, likes: totals.__setitem__(slug, (views, likes)))
    video = {"url": "undated", "music_id": "123456", "views": 20, "likes": 3, **date_fields}

    result = scheduler._attach_internal_to_campaigns([video])

    assert result["attached_count"] == 1
    assert result["skipped_no_active_campaign"] == 0
    assert result["per_campaign"] == {"legacy-z": 1}
    assert [v["url"] for v in stored["legacy-z"]] == ["retained", "undated"]
    assert stored["legacy-z"][1]["match_strategy"] == "internal_creator"
    assert totals == {"legacy-z": (30, 5)}
    assert all(rows == [existing] for slug, rows in stored.items() if slug != "legacy-z")


@pytest.mark.parametrize("date_fields", [
    {},
    {"timestamp": "2026-99-99"},
    {"upload_date": "20261340"},
])
def test_internal_attach_unknown_date_never_proves_dated_round_membership(monkeypatch, date_fields):
    campaigns = [
        {"slug": "dated", "sound_id": "123456", "start_date": "2026-04-01"},
        {"slug": "invalid", "sound_id": "123456", "start_date": "bad"},
    ]
    monkeypatch.setattr(scheduler._db, "list_campaigns", lambda **kw: campaigns)
    monkeypatch.setattr(scheduler._db, "get_matched_videos", lambda slug: pytest.fail("ineligible campaign read"))
    monkeypatch.setattr(scheduler._db, "replace_matched_videos", lambda *args: pytest.fail("ineligible campaign write"))
    result = scheduler._attach_internal_to_campaigns([
        {"url": "undated", "music_id": "123456", **date_fields},
    ])
    assert result["attached_count"] == 0
    assert result["skipped_no_active_campaign"] == 1
