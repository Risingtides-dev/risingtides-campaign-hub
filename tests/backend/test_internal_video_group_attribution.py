"""Tests for the durable point-in-time group attribution side table (RTA-13).

Verifies that:
  1. New scrapes populate `internal_video_group_attribution` for each
     group the account currently belongs to.
  2. After removing an account from a group, a subsequent scrape only
     attributes to the new (current) membership.
  3. Historical attribution rows are NOT rewritten by membership
     changes — the durability property of the side table.
  4. `get_group_stats` reads via the side table for attributed videos
     and falls back to runtime membership join for legacy
     (un-attributed) videos.
"""
from __future__ import annotations

from campaign_manager.models import (
    InternalVideoCache,
    InternalVideoGroupAttribution,
)


def _seed_creator(db, username: str) -> None:
    db.add_internal_creators([username])


def _seed_group(db, slug: str, title: str) -> int:
    g = db.create_internal_group(slug=slug, title=title)
    assert g is not None
    return int(g["id"])


def _video(url: str, views: int = 100, upload_date: str = "20990101") -> dict:
    # upload_date in the future so the _cutoff_yyyymmdd filter never excludes
    # the row regardless of when the test runs.
    return {
        "url": url,
        "song": "Test Song",
        "artist": "Test Artist",
        "account": "test",
        "views": views,
        "likes": 10,
        "upload_date": upload_date,
        "timestamp": "2099-01-01",
    }


class TestAttributionWritePath:
    def test_new_scrape_writes_attribution_row_per_group(self, db):
        _seed_creator(db, "alice")
        g_id = _seed_group(db, "warner", "Warner")
        db.add_group_members(g_id, ["alice"])

        db.merge_internal_cache("alice", [_video("v1")])

        with db.get_session() as s:
            rows = s.query(InternalVideoGroupAttribution).all()
            assert len(rows) == 1
            assert rows[0].group_id == g_id
            vid = s.query(InternalVideoCache).filter_by(url="v1").first()
            assert rows[0].video_id == vid.id

    def test_account_in_multiple_groups_gets_one_row_per_group(self, db):
        _seed_creator(db, "alice")
        g1 = _seed_group(db, "warner", "Warner")
        g2 = _seed_group(db, "atlantic", "Atlantic")
        db.add_group_members(g1, ["alice"])
        db.add_group_members(g2, ["alice"])

        db.merge_internal_cache("alice", [_video("v1")])

        with db.get_session() as s:
            rows = s.query(InternalVideoGroupAttribution).all()
            assert {r.group_id for r in rows} == {g1, g2}

    def test_account_in_no_groups_writes_no_rows(self, db):
        _seed_creator(db, "alice")
        db.merge_internal_cache("alice", [_video("v1")])

        with db.get_session() as s:
            assert s.query(InternalVideoGroupAttribution).count() == 0

    def test_rerunning_merge_is_idempotent(self, db):
        _seed_creator(db, "alice")
        g_id = _seed_group(db, "warner", "Warner")
        db.add_group_members(g_id, ["alice"])

        db.merge_internal_cache("alice", [_video("v1")])
        # Re-run with same URL — merge dedupes on URL so no new
        # InternalVideoCache row is created and no new attribution row
        # either. (Even if it tried, the unique constraint would block.)
        db.merge_internal_cache("alice", [_video("v1", views=500)])

        with db.get_session() as s:
            assert s.query(InternalVideoGroupAttribution).count() == 1


class TestAttributionDurability:
    def test_remove_membership_does_not_rewrite_historical_attribution(self, db):
        """The whole point of the side table: removing a creator from a
        group must NOT silently rewrite the attribution of videos
        scraped while the creator was still a member.
        """
        _seed_creator(db, "alice")
        g_id = _seed_group(db, "warner", "Warner")
        db.add_group_members(g_id, ["alice"])

        # Scrape while alice is in Warner.
        db.merge_internal_cache("alice", [_video("v1")])
        with db.get_session() as s:
            historical_count = s.query(InternalVideoGroupAttribution).count()
        assert historical_count == 1

        # Move alice to a different group.
        db.remove_group_member(g_id, "alice")
        g2 = _seed_group(db, "atlantic", "Atlantic")
        db.add_group_members(g2, ["alice"])

        # Scrape a new video.
        db.merge_internal_cache("alice", [_video("v2")])

        with db.get_session() as s:
            rows = s.query(InternalVideoGroupAttribution).all()
            by_video = {
                s.get(InternalVideoCache, r.video_id).url: r.group_id
                for r in rows
            }
            # v1 stays attributed to Warner even though alice is no
            # longer a Warner member.
            assert by_video["v1"] == g_id
            # v2 picks up the current membership.
            assert by_video["v2"] == g2


class TestAttributionReadPath:
    def test_get_group_stats_uses_side_table(self, db):
        _seed_creator(db, "alice")
        g_id = _seed_group(db, "warner", "Warner")
        db.add_group_members(g_id, ["alice"])

        db.merge_internal_cache("alice", [_video("v1", views=1000)])

        stats = db.get_group_stats(g_id)
        assert stats is not None
        assert stats["total_posts"] == 1
        assert stats["total_views"] == 1000

    def test_get_group_stats_falls_back_for_legacy_videos(self, db):
        """A pre-RTA-13 video has no attribution row — runtime
        membership join should still surface it for the current group.
        """
        _seed_creator(db, "alice")
        g_id = _seed_group(db, "warner", "Warner")
        db.add_group_members(g_id, ["alice"])

        # Insert a video directly, bypassing merge_internal_cache so no
        # attribution row is written (simulates a legacy video).
        with db.get_session() as s:
            s.add(InternalVideoCache(
                username="alice",
                url="legacy",
                song="S",
                artist="A",
                views=222,
                likes=0,
                upload_date="20990101",
            ))
            s.commit()

        stats = db.get_group_stats(g_id)
        assert stats is not None
        assert stats["total_posts"] == 1
        assert stats["total_views"] == 222

    def test_durability_holds_through_read_path(self, db):
        """After re-tagging an account, historical stats for the OLD
        group must still include the old videos.
        """
        _seed_creator(db, "alice")
        warner = _seed_group(db, "warner", "Warner")
        atlantic = _seed_group(db, "atlantic", "Atlantic")
        db.add_group_members(warner, ["alice"])

        # Scrape while alice is in Warner.
        db.merge_internal_cache("alice", [_video("v1", views=500)])

        # Re-tag: move alice to Atlantic.
        db.remove_group_member(warner, "alice")
        db.add_group_members(atlantic, ["alice"])

        warner_stats = db.get_group_stats(warner)
        atlantic_stats = db.get_group_stats(atlantic)

        # v1 stays attributed to Warner.
        assert warner_stats["total_posts"] == 1
        assert warner_stats["total_views"] == 500
        # Atlantic sees nothing yet (alice has no scrapes since joining).
        assert atlantic_stats["total_posts"] == 0
