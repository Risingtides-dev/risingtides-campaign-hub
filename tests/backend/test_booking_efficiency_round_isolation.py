"""Round-ownership regressions for the booking efficiency service.

Covers:
 - Two campaign rounds sharing a sound: a video posted in round 1's window
   must not inflate round 2's ROI.
 - Wrong-round stored posts: a video stored under a campaign's rows but
   posted after the next round started is excluded.
 - Secondary / additional sounds are scoped correctly.
 - Dismissed rows are already excluded by SQL; the service must not count
   them even if they would otherwise pass the round window.
 - Normalised handles: @creator and creator bookings merge to one record.
 - Zero views still returns a metrics row (no fake fallback).
 - Report and leaderboard surfaces agree on tier/metrics for the same creator.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from campaign_manager.models import Campaign, Creator, MatchedVideo
from campaign_manager.services.booking_efficiency import (
    calculate_creator_metrics,
    generate_efficiency_report,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now_str() -> str:
    return datetime.now().isoformat()


def _days_ago(n: int) -> datetime:
    return datetime.now() - timedelta(days=n)


def _add_campaign(session, *, slug, sound_id="SND001", start_date="2026-01-01",
                  additional_sounds=None, created_at=None, completion_status="none"):
    cam = Campaign(
        slug=slug,
        title=slug,
        artist="Art",
        song="Song",
        sound_id=sound_id,
        additional_sounds=additional_sounds or [],
        start_date=start_date,
        created_at=created_at or datetime.now(),
        completion_status=completion_status,
    )
    session.add(cam)
    session.commit()
    return cam


def _add_creator(session, campaign_id, *, username, posts_owed=1, total_rate=500.0):
    c = Creator(
        campaign_id=campaign_id,
        username=username,
        posts_owed=posts_owed,
        total_rate=total_rate,
    )
    session.add(c)
    session.commit()
    return c


def _add_video(session, campaign_id, *, account, views=1000, likes=50,
               music_id="SND001", timestamp=None, upload_date=None,
               first_seen_at=None, dismissed_at=None):
    v = MatchedVideo(
        campaign_id=campaign_id,
        url=f"https://tiktok.com/@{account}/{id(object())}",
        account=f"@{account}",
        views=views,
        likes=likes,
        music_id=music_id,
        timestamp=timestamp or "",
        upload_date=upload_date or "",
        first_seen_at=first_seen_at or datetime.now(),
        dismissed_at=dismissed_at,
    )
    session.add(v)
    session.commit()
    return v


# ---------------------------------------------------------------------------
# round isolation: shared sound
# ---------------------------------------------------------------------------

class TestRoundIsolation:
    def test_video_from_earlier_round_excluded_from_later_round(self, db):
        """A post dated in round 1's window must not count toward round 2's metrics."""
        with db.get_session() as s:
            # Round 1: Jan 1 – Feb 1
            r1 = _add_campaign(s, slug="r1", sound_id="SND001",
                                start_date="2026-01-01",
                                created_at=_days_ago(60),
                                completion_status="completed")
            # Round 2: Feb 1 onwards
            r2 = _add_campaign(s, slug="r2", sound_id="SND001",
                                start_date="2026-02-01",
                                created_at=_days_ago(30))

            _add_creator(s, r2.id, username="creator")

            # Video posted Jan 15 (round 1 window) but stored in r2's rows
            _add_video(s, r2.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-01-15T12:00:00",
                       views=99999, likes=9999)

            # Video posted Feb 10 (round 2 window), also stored in r2
            _add_video(s, r2.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-02-10T12:00:00",
                       views=5000, likes=250)

        with db.get_session() as s:
            m = calculate_creator_metrics(s, "creator")
        assert m is not None
        # Only the Feb 10 video is in round 2's window
        assert m.total_views == 5000
        assert m.total_engagement == 250

    def test_video_from_later_round_excluded_from_earlier_round(self, db):
        """A post dated after round 2 started must not count toward round 1."""
        with db.get_session() as s:
            r1 = _add_campaign(s, slug="r1", sound_id="SND001",
                                start_date="2026-01-01",
                                created_at=_days_ago(60))
            r2 = _add_campaign(s, slug="r2", sound_id="SND001",
                                start_date="2026-02-01",
                                created_at=_days_ago(30))

            _add_creator(s, r1.id, username="creator")

            # Stored in r1 but posted Feb 15 (after r2 started)
            _add_video(s, r1.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-02-15T12:00:00",
                       views=88888, likes=8888)

            # Legit r1 post: Jan 20
            _add_video(s, r1.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-01-20T12:00:00",
                       views=3000, likes=150)

        with db.get_session() as s:
            m = calculate_creator_metrics(s, "creator")
        assert m is not None
        assert m.total_views == 3000

    def test_no_start_date_includes_all_videos_legacy_behaviour(self, db):
        """Campaigns without a start_date retain legacy all-videos behaviour."""
        with db.get_session() as s:
            cam = _add_campaign(s, slug="legacy", sound_id="SND001", start_date="")
            _add_creator(s, cam.id, username="creator")
            _add_video(s, cam.id, account="creator", music_id="SND001",
                       timestamp="2024-01-01T00:00:00", views=7000, likes=100)

        with db.get_session() as s:
            m = calculate_creator_metrics(s, "creator")
        assert m is not None
        assert m.total_views == 7000


# ---------------------------------------------------------------------------
# secondary sounds
# ---------------------------------------------------------------------------

class TestSecondarySound:
    def test_secondary_sound_video_in_r1_window_counts(self, db):
        """A video matched via an additional_sound that is unique to r1 counts."""
        with db.get_session() as s:
            r1 = _add_campaign(s, slug="r1", sound_id="SND001",
                                additional_sounds=["SEC001"],
                                start_date="2026-01-01",
                                created_at=_days_ago(60))
            r2 = _add_campaign(s, slug="r2", sound_id="SND001",
                                start_date="2026-02-01",
                                created_at=_days_ago(30))

            _add_creator(s, r1.id, username="creator")
            # Secondary sound video in r1's window
            _add_video(s, r1.id, account="creator",
                       music_id="SEC001",
                       timestamp="2026-01-20T00:00:00",
                       views=4000, likes=200)
            # Primary sound video in r1's window
            _add_video(s, r1.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-01-25T00:00:00",
                       views=2000, likes=100)

        with db.get_session() as s:
            m = calculate_creator_metrics(s, "creator")
        assert m is not None
        assert m.total_views == 6000  # both included

    def test_secondary_sound_video_outside_r1_window_excluded(self, db):
        """A secondary sound with no later round has no upper boundary (open window)."""
        with db.get_session() as s:
            # r1 uses SND001 (also used by r2) and SEC001 (unique to r1)
            r1 = _add_campaign(s, slug="r1", sound_id="SND001",
                                additional_sounds=["SEC001"],
                                start_date="2026-01-01",
                                created_at=_days_ago(60))
            r2 = _add_campaign(s, slug="r2", sound_id="SND001",
                                start_date="2026-02-01",
                                created_at=_days_ago(30))

            _add_creator(s, r1.id, username="creator")
            # SEC001 has no later round → open window; Feb post allowed
            _add_video(s, r1.id, account="creator",
                       music_id="SEC001",
                       timestamp="2026-02-15T00:00:00",
                       views=3000, likes=150)
            # SND001 primary IS capped at Feb 1 for r1
            _add_video(s, r1.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-02-15T00:00:00",
                       views=99000, likes=990)

        with db.get_session() as s:
            m = calculate_creator_metrics(s, "creator")
        assert m is not None
        # Only the SEC001 (open window) video should be counted for r1
        assert m.total_views == 3000


# ---------------------------------------------------------------------------
# dismissed rows
# ---------------------------------------------------------------------------

class TestDismissedRows:
    def test_dismissed_videos_not_counted(self, db):
        """Videos with dismissed_at set are excluded by the SQL pre-filter."""
        with db.get_session() as s:
            cam = _add_campaign(s, slug="dism", sound_id="SND001",
                                start_date="2026-01-01")
            _add_creator(s, cam.id, username="creator")
            _add_video(s, cam.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-01-15T00:00:00",
                       views=50000, likes=5000,
                       dismissed_at=datetime.now())
            _add_video(s, cam.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-01-20T00:00:00",
                       views=2000, likes=100)

        with db.get_session() as s:
            m = calculate_creator_metrics(s, "creator")
        assert m is not None
        assert m.total_views == 2000
        assert m.total_engagement == 100


# ---------------------------------------------------------------------------
# handle normalisation
# ---------------------------------------------------------------------------

class TestHandleNormalisation:
    def test_at_prefix_booking_merges_with_bare_booking(self, db):
        """@creator and creator booked in separate campaigns merge to one record."""
        with db.get_session() as s:
            cam1 = _add_campaign(s, slug="n1", sound_id="SND001",
                                 start_date="2026-01-01",
                                 created_at=_days_ago(60))
            cam2 = _add_campaign(s, slug="n2", sound_id="SND002",
                                 start_date="2026-01-01",
                                 created_at=_days_ago(30))

            # Booked as "@creator" in campaign 1, bare in campaign 2
            _add_creator(s, cam1.id, username="@creator", total_rate=300.0)
            _add_creator(s, cam2.id, username="creator", total_rate=400.0)

            _add_video(s, cam1.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-01-10T00:00:00",
                       views=1000, likes=50)
            _add_video(s, cam2.id, account="creator",
                       music_id="SND002",
                       timestamp="2026-01-10T00:00:00",
                       views=2000, likes=100)

        with db.get_session() as s:
            m = calculate_creator_metrics(s, "creator")
        assert m is not None
        assert m.total_campaigns == 2
        assert m.total_spend == 700.0
        assert m.total_views == 3000

    def test_at_prefix_lookup_matches_bare_booking(self, db):
        """calculate_creator_metrics("@creator") finds bare-stored bookings."""
        with db.get_session() as s:
            cam = _add_campaign(s, slug="at1", sound_id="SND001",
                                start_date="2026-01-01")
            _add_creator(s, cam.id, username="creator", total_rate=500.0)
            _add_video(s, cam.id, account="creator",
                       music_id="SND001",
                       timestamp="2026-01-15T00:00:00",
                       views=1500, likes=75)

        with db.get_session() as s:
            m = calculate_creator_metrics(s, "@creator")
        assert m is not None
        assert m.total_spend == 500.0
        assert m.total_views == 1500

    def test_generate_report_deduplicates_normalised_handles(self, db):
        """generate_efficiency_report produces one record per normalised handle."""
        with db.get_session() as s:
            cam1 = _add_campaign(s, slug="dn1", sound_id="SND001",
                                 start_date="2026-01-01",
                                 created_at=_days_ago(60))
            cam2 = _add_campaign(s, slug="dn2", sound_id="SND002",
                                 start_date="2026-01-01",
                                 created_at=_days_ago(30))

            _add_creator(s, cam1.id, username="@dupehandle", total_rate=200.0)
            _add_creator(s, cam2.id, username="dupehandle", total_rate=300.0)

            _add_video(s, cam1.id, account="dupehandle",
                       music_id="SND001",
                       timestamp="2026-01-05T00:00:00",
                       views=500)
            _add_video(s, cam2.id, account="dupehandle",
                       music_id="SND002",
                       timestamp="2026-01-05T00:00:00",
                       views=600)

        with db.get_session() as s:
            report = generate_efficiency_report(s)

        all_rows = (
            report.top_performers
            + report.undervalued_deals
            + report.overpriced_creators
        )
        # Both tier lists combined should have exactly one entry for dupehandle
        dupehandle_rows = [r for r in all_rows if r.creator_username == "dupehandle"]
        assert len(dupehandle_rows) == 1
        assert dupehandle_rows[0].total_spend == 500.0


# ---------------------------------------------------------------------------
# zero views
# ---------------------------------------------------------------------------

class TestZeroViews:
    def test_zero_views_returns_metrics_not_none(self, db):
        """A creator with spend but zero in-round views returns a metrics record
        with roi=0 (no phantom 50k/post fallback)."""
        with db.get_session() as s:
            cam = _add_campaign(s, slug="zv", sound_id="SND001",
                                start_date="2026-01-01")
            _add_creator(s, cam.id, username="ghost", total_rate=500.0)
            # Video with 0 views but within round window
            _add_video(s, cam.id, account="ghost",
                       music_id="SND001",
                       timestamp="2026-01-15T00:00:00",
                       views=0, likes=0)

        with db.get_session() as s:
            m = calculate_creator_metrics(s, "ghost")
        assert m is not None
        assert m.total_views == 0
        assert m.roi_ratio == 0
        import math
        assert math.isinf(m.cost_per_view)


# ---------------------------------------------------------------------------
# report / leaderboard parity
# ---------------------------------------------------------------------------

class TestReportLeaderboardParity:
    def test_report_and_leaderboard_agree(self, db, client):
        """The /report and /leaderboard endpoints must return the same tier
        for the same creator (they share the underlying metrics function)."""
        with db.get_session() as s:
            cam = _add_campaign(s, slug="par1", sound_id="SND001",
                                start_date="2026-01-01")
            _add_creator(s, cam.id, username="parityuser", total_rate=800.0)
            _add_video(s, cam.id, account="parityuser",
                       music_id="SND001",
                       timestamp="2026-01-10T00:00:00",
                       views=12000, likes=600)

        import json
        resp_r = client.get("/api/efficiency/report")
        assert resp_r.status_code == 200
        report = json.loads(resp_r.data)
        all_report = (
            report["top_performers"]
            + report["undervalued_deals"]
            + report["overpriced_creators"]
        )
        report_entry = next((r for r in all_report if r["creator_username"] == "parityuser"), None)
        assert report_entry is not None, "Creator missing from report"

        resp_l = client.get("/api/efficiency/leaderboard")
        assert resp_l.status_code == 200
        lb = json.loads(resp_l.data)
        all_lb = []
        for tier_list in ["elite", "high_value", "solid", "standard", "undervalued", "overpriced"]:
            all_lb.extend(lb.get(tier_list, []))
        lb_entry = next((r for r in all_lb if r["creator_username"] == "parityuser"), None)
        assert lb_entry is not None, "Creator missing from leaderboard"

        assert report_entry["tier"] == lb_entry["tier"]
        assert report_entry["total_views"] == lb_entry["total_views"]
        assert report_entry["total_spend"] == lb_entry["total_spend"]
