"""Creator Library stats: performance windows and the rate-memory rule.

These are the two places the Library can silently lie to a booker — a stat
window that quietly mixes stale and fresh data, or a rate that resolves to
the wrong number when you add someone to a campaign. Both are pure
functions so they can be pinned down exactly.
"""
from __future__ import annotations

from datetime import date, datetime

from campaign_manager.services.creator_library_stats import (
    VIRAL_THRESHOLD,
    build_windows,
    dedupe_posts,
    effective_rate,
)

TODAY = date(2026, 8, 10)


def _posts(*pairs):
    """(days_ago, views) -> [(date, views)]"""
    return [(date.fromordinal(TODAY.toordinal() - d), v) for d, v in pairs]


# ── windows ────────────────────────────────────────────────────────────

def test_window_splits_on_recency():
    posts = _posts((5, 100), (20, 200), (45, 300), (80, 400), (200, 500))
    w = build_windows(posts, TODAY)

    assert w["w30"]["posts"] == 2      # 5d, 20d
    assert w["w60"]["posts"] == 3      # + 45d
    assert w["w90"]["posts"] == 4      # + 80d
    assert w["wall"]["posts"] == 5     # + 200d


def test_window_boundary_is_inclusive():
    """A post exactly 60 days old belongs to the 60-day window."""
    w = build_windows(_posts((60, 999)), TODAY)
    assert w["w60"]["posts"] == 1
    assert w["w30"] is None


def test_empty_window_is_none_not_zero():
    """No posts must read as 'no data' (dash), never as a real zero —
    a 0 would rank a creator as free rather than unknown."""
    w = build_windows(_posts((200, 500)), TODAY)
    assert w["w30"] is None
    assert w["wall"]["posts"] == 1


def test_median_resists_a_viral_outlier():
    """The whole reason we rank on median: one viral post must not
    drag the headline number up."""
    posts = _posts((1, 10_000), (2, 12_000), (3, 11_000), (4, 5_000_000))
    w = build_windows(posts, TODAY)["w30"]

    assert w["median"] == 11_500
    assert w["avg"] > 1_000_000
    assert w["peak"] == 5_000_000


def test_totals_and_percentiles():
    posts = _posts((1, 1_000), (2, 2_000), (3, 3_000), (4, 4_000))
    w = build_windows(posts, TODAY)["w30"]

    assert w["total"] == 10_000
    assert w["median"] == 2_500
    assert w["p25"] <= w["median"] <= w["peak"]


def test_viral_rate_counts_posts_over_100k():
    """Jake's threshold: 100k, not a million."""
    assert VIRAL_THRESHOLD == 100_000

    posts = _posts((1, 99_999), (2, 100_000), (3, 250_000), (4, 1_000))
    w = build_windows(posts, TODAY)["w30"]

    assert w["viral_rate"] == 50.0     # 2 of 4 at or above 100k


def test_projected_cpm_uses_the_rate_and_typical_views():
    """$50 a post against a typical 25k views is a $2 CPM."""
    posts = _posts((1, 25_000), (2, 25_000))
    w = build_windows(posts, TODAY, rate=50.0)["w30"]

    assert w["pcpm"] == 2.0
    assert w["floor"] >= w["pcpm"]     # worst case is never rosier


def test_no_rate_means_no_cpm_rather_than_a_wrong_one():
    w = build_windows(_posts((1, 10_000)), TODAY, rate=None)["w30"]
    assert w["pcpm"] is None
    assert w["floor"] is None


def test_zero_views_does_not_divide_by_zero():
    w = build_windows(_posts((1, 0), (2, 0)), TODAY, rate=50.0)["w30"]
    assert w["total"] == 0
    assert w["pcpm"] is None          # undefined, not infinity


# ── dedupe ─────────────────────────────────────────────────────────────

def test_dedupe_counts_a_post_matched_to_many_campaigns_once():
    """The same video submitted under two campaigns was inflating totals."""
    rows = [
        ("https://www.tiktok.com/@a/video/111", date(2026, 8, 1), 500),
        ("https://www.tiktok.com/@a/video/111", date(2026, 8, 1), 500),
        ("https://www.tiktok.com/@a/video/222", date(2026, 8, 2), 700),
    ]
    out = dedupe_posts(rows)

    assert len(out) == 2
    assert sum(v for _, v in out) == 1200


def test_dedupe_keeps_the_highest_view_count_seen():
    """Two trackers can report the same post at different freshness;
    the larger number is the later observation."""
    rows = [
        ("https://www.tiktok.com/@a/video/111", date(2026, 8, 1), 500),
        ("https://www.tiktok.com/@a/video/111", date(2026, 8, 1), 900),
    ]
    assert dedupe_posts(rows) == [(date(2026, 8, 1), 900)]


# ── rate memory ────────────────────────────────────────────────────────

def test_manual_rate_wins_when_there_are_no_bookings():
    rate, src = effective_rate(
        override=35.0, override_at=datetime(2026, 8, 1),
        last_rate=None, last_booked_at=None,
    )
    assert (rate, src) == (35.0, "override")


def test_last_booking_is_used_when_nothing_was_set_by_hand():
    rate, src = effective_rate(
        override=None, override_at=None,
        last_rate=20.0, last_booked_at=date(2026, 7, 1),
    )
    assert (rate, src) == (20.0, "booking")


def test_manual_rate_survives_an_older_booking():
    """Jake sets $40 today; a booking from last month must not undo it."""
    rate, src = effective_rate(
        override=40.0, override_at=datetime(2026, 8, 5),
        last_rate=20.0, last_booked_at=date(2026, 7, 1),
    )
    assert (rate, src) == (40.0, "override")


def test_a_newer_booking_supersedes_the_manual_rate():
    """Jake's rule: 'if it changes to something else use the most recent.'"""
    rate, src = effective_rate(
        override=40.0, override_at=datetime(2026, 7, 1),
        last_rate=25.0, last_booked_at=date(2026, 8, 5),
    )
    assert (rate, src) == (25.0, "booking")


def test_no_rate_anywhere_reports_none():
    rate, src = effective_rate(None, None, None, None)
    assert rate is None and src == "none"


def test_same_day_booking_and_override_keeps_the_manual_rate():
    """A tie goes to the human — they typed it knowing the booking."""
    rate, src = effective_rate(
        override=40.0, override_at=datetime(2026, 8, 5, 14, 0),
        last_rate=25.0, last_booked_at=date(2026, 8, 5),
    )
    assert (rate, src) == (40.0, "override")
