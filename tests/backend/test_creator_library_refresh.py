"""Refreshing library stats from the Tides Trackers.

This job exists because the Hub only overlays live tracker stats onto
*active* campaigns. Completed campaigns keep whatever the last scrape
caught, and since TikTok views climb for weeks after posting, anything
marked complete early is undercounted for good — measured at roughly 4x
across the roster.

The fetcher is injected so these tests never touch the network.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from campaign_manager.models import Campaign, CreatorProfile
from campaign_manager.services import creator_library as lib
from campaign_manager.services.creator_library_refresh import (
    extract_rows,
    refresh_creator_stats,
)


@pytest.fixture
def session(db):
    with db.get_session() as s:
        yield s


def _video(username, vid, views, published, followers=0):
    return {
        "username": username,
        "video_url": f"https://www.tiktok.com/@{username}/video/{vid}",
        "views": views,
        "published_at": published,
        "author_followers": followers,
    }


# ── payload parsing ────────────────────────────────────────────────────

def test_extract_rows_reads_the_tracker_payload():
    rows, followers = extract_rows([
        _video("alice", 111, 5000, "2026-08-01T12:00:00Z", followers=1200),
    ])

    assert rows["alice"] == [
        ("https://www.tiktok.com/@alice/video/111", date(2026, 8, 1), 5000)
    ]
    assert followers["alice"] == 1200


def test_extract_rows_ignores_entries_without_a_usable_date():
    rows, _ = extract_rows([
        _video("alice", 111, 5000, ""),
        _video("alice", 222, 6000, "2026-08-02T00:00:00Z"),
    ])
    assert len(rows["alice"]) == 1


def test_extract_rows_normalises_the_username():
    rows, _ = extract_rows([_video("@Alice", 111, 10, "2026-08-01T00:00:00Z")])
    assert "alice" in rows


def test_extract_rows_keeps_the_highest_follower_count_seen():
    rows, followers = extract_rows([
        _video("alice", 111, 10, "2026-08-01T00:00:00Z", followers=900),
        _video("alice", 222, 10, "2026-08-02T00:00:00Z", followers=1500),
    ])
    assert followers["alice"] == 1500


# ── the job ────────────────────────────────────────────────────────────

def test_refresh_writes_windows_onto_the_profile(session):
    payloads = {
        "tracker-a": [
            _video("alice", 111, 10_000, "2026-08-05T00:00:00Z", followers=5000),
            _video("alice", 222, 30_000, "2026-08-08T00:00:00Z"),
        ],
    }
    summary = refresh_creator_stats(
        session,
        tracker_ids=["tracker-a"],
        fetch_videos=payloads.get,
        today=date(2026, 8, 10),
    )

    assert summary["creators"] == 1
    assert summary["trackers"] == 1
    assert summary["posts"] == 2

    profile = session.get(CreatorProfile, "alice")
    assert profile.stats["w30"]["posts"] == 2
    assert profile.stats["w30"]["total"] == 40_000
    assert profile.stats["w30"]["median"] == 20_000
    assert profile.followers == 5000
    assert isinstance(profile.stats_updated_at, datetime)


def test_refresh_counts_a_post_once_across_trackers(session):
    """The same video submitted to two campaigns must not double the total."""
    payloads = {
        "tracker-a": [_video("alice", 111, 10_000, "2026-08-05T00:00:00Z")],
        "tracker-b": [_video("alice", 111, 12_000, "2026-08-05T00:00:00Z")],
    }
    refresh_creator_stats(
        session,
        tracker_ids=["tracker-a", "tracker-b"],
        fetch_videos=payloads.get,
        today=date(2026, 8, 10),
    )

    profile = session.get(CreatorProfile, "alice")
    assert profile.stats["w30"]["posts"] == 1
    assert profile.stats["w30"]["total"] == 12_000, "freshest count wins"


def test_refresh_does_not_store_cpm(session):
    """CPM is derived at read time from the current rate, so caching it
    here would go stale the moment a rate is edited."""
    payloads = {"t": [_video("alice", 111, 10_000, "2026-08-05T00:00:00Z")]}
    refresh_creator_stats(
        session, tracker_ids=["t"], fetch_videos=payloads.get,
        today=date(2026, 8, 10),
    )

    window = session.get(CreatorProfile, "alice").stats["w30"]
    assert window["pcpm"] is None
    assert window["floor"] is None


def test_a_failing_tracker_does_not_abort_the_run(session):
    def fetch(tracker_id):
        if tracker_id == "broken":
            raise RuntimeError("tracker exploded")
        return [_video("alice", 111, 10_000, "2026-08-05T00:00:00Z")]

    summary = refresh_creator_stats(
        session,
        tracker_ids=["broken", "good"],
        fetch_videos=fetch,
        today=date(2026, 8, 10),
    )

    assert summary["failed"] == 1
    assert summary["creators"] == 1, "one bad tracker must not lose the rest"


def test_refresh_preserves_tags_and_rate_on_an_existing_profile(session):
    lib.set_niches(session, "alice", ["gym"])
    lib.update_profile(session, "alice", rate_override=42.0, note="keep me")

    payloads = {"t": [_video("alice", 111, 10_000, "2026-08-05T00:00:00Z")]}
    refresh_creator_stats(
        session, tracker_ids=["t"], fetch_videos=payloads.get,
        today=date(2026, 8, 10),
    )

    profile = session.get(CreatorProfile, "alice")
    assert profile.rate_override == 42.0
    assert profile.note == "keep me"
    assert lib.niches_for(session, ["alice"])["alice"] == ["gym"]


def test_tracker_ids_are_collected_from_campaigns(session):
    session.add(Campaign(slug="camp-a", title="A", tracker_campaign_id="uuid-a"))
    session.add(Campaign(slug="camp-b", title="B", tracker_campaign_id=""))
    session.commit()

    seen = []

    def fetch(tracker_id):
        seen.append(tracker_id)
        return []

    refresh_creator_stats(session, fetch_videos=fetch, today=date(2026, 8, 10))
    assert seen == ["uuid-a"], "campaigns without a tracker are skipped"


def test_trackers_are_fetched_concurrently(session):
    """Sequential fetches overran gunicorn's 120s worker timeout in
    production. The work is pure network wait, so it must overlap."""
    import threading
    import time

    active = 0
    peak = 0
    lock = threading.Lock()

    def slow_fetch(tracker_id):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return [_video("alice", tracker_id, 100, "2026-08-05T00:00:00Z")]

    ids = [str(i) for i in range(12)]
    started = time.monotonic()
    refresh_creator_stats(
        session, tracker_ids=ids, fetch_videos=slow_fetch,
        today=date(2026, 8, 10), max_workers=6,
    )
    elapsed = time.monotonic() - started

    assert peak > 1, "fetches ran one at a time"
    assert elapsed < 12 * 0.05, "no better than sequential"


def test_concurrent_run_still_isolates_a_failing_tracker(session):
    def fetch(tracker_id):
        if tracker_id in {"bad1", "bad2"}:
            raise RuntimeError("boom")
        return [_video("alice", tracker_id, 5_000, "2026-08-05T00:00:00Z")]

    summary = refresh_creator_stats(
        session,
        tracker_ids=["bad1", "good1", "bad2", "good2"],
        fetch_videos=fetch,
        today=date(2026, 8, 10),
    )

    assert summary["failed"] == 2
    assert summary["trackers"] == 2
    assert session.get(CreatorProfile, "alice").stats["w30"]["posts"] == 2


def test_no_trackers_is_a_clean_no_op(session):
    summary = refresh_creator_stats(
        session, tracker_ids=[], fetch_videos=lambda _: [],
        today=date(2026, 8, 10),
    )
    assert summary["creators"] == 0 and summary["trackers"] == 0
