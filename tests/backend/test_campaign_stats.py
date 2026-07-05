"""Tests for campaign_manager.services.campaign_stats (RTA-43)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from campaign_manager import db as _db
from campaign_manager.models import Campaign, MatchedVideo, TrackerCampaignLink, TrackerName
from campaign_manager.services import campaign_stats
from campaign_manager.services.campaign_stats import (
    SOURCE_API,
    SOURCE_API_CACHED,
    SOURCE_EMPTY,
    SOURCE_SCRAPER_FALLBACK,
    _normalize_url,
    get_campaign_stats,
    get_campaign_stats_bulk,
    invalidate_cache,
    overlay_video_stats,
)
from campaign_manager.services.tides_tracker import Submission, TidesTrackerFetchResult


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_cache()
    yield
    invalidate_cache()


def _seed_campaign_with_tracker(slug: str, tracker_id: str = "tracker-uuid-1") -> int:
    with _db.get_session() as s:
        camp = Campaign(slug=slug, title=slug, artist="A", song="S",
                        tracker_campaign_id=tracker_id)
        s.add(camp)
        s.commit()
        cid = camp.id
        # tracker_names is the canonical source for RTA-42's pull_all loop;
        # not required for get_tracker_id_for_campaign but kept for parity.
        s.add(TrackerName(tracker_id=tracker_id, display_name=slug))
        s.commit()
    return cid


def _seed_campaign_no_tracker(slug: str) -> int:
    with _db.get_session() as s:
        camp = Campaign(slug=slug, title=slug, artist="A", song="S")
        s.add(camp)
        s.commit()
        return camp.id


def _seed_matched_videos(campaign_id: int, rows):
    with _db.get_session() as s:
        for r in rows:
            s.add(MatchedVideo(campaign_id=campaign_id, **r))
        s.commit()


def _ok_fetch(tracker_id: str, submissions):
    return TidesTrackerFetchResult(
        ok=True, tracker_id=tracker_id, submissions=submissions,
        fetched_at="2026-05-14T12:00:00Z", status_code=200,
    )


def _err_fetch(tracker_id: str, kind: str = "http_5xx"):
    return TidesTrackerFetchResult(
        ok=False, tracker_id=tracker_id, error_kind=kind,
        detail="boom", status_code=500,
    )


class TestNormalizeUrl:
    def test_strips_trailing_slash(self):
        assert _normalize_url("https://tiktok.com/foo/") == "https://tiktok.com/foo"

    def test_strips_query_params(self):
        assert _normalize_url("https://tiktok.com/foo?utm=x") == "https://tiktok.com/foo"

    def test_lowercases(self):
        assert _normalize_url("HTTPS://TIKTOK.COM/Foo") == "https://tiktok.com/foo"

    def test_handles_empty(self):
        assert _normalize_url("") == ""


class TestGetCampaignStats:
    def test_no_slug_returns_empty(self, db):
        result = get_campaign_stats("")
        assert result.source == SOURCE_EMPTY
        assert result.submissions == []

    def test_no_tracker_falls_back_to_scraper(self, db):
        cid = _seed_campaign_no_tracker("no-tracker")
        _seed_matched_videos(cid, [
            dict(url="https://tt.com/v/1", account="@a", views=100, likes=10),
            dict(url="https://tt.com/v/2", account="@b", views=200, likes=20),
        ])
        result = get_campaign_stats("no-tracker")
        assert result.source == SOURCE_SCRAPER_FALLBACK
        assert result.error_kind == "no_tracker"
        assert result.total_views == 300
        assert result.total_likes == 30
        assert result.post_count == 2

    def test_no_tracker_no_videos_returns_empty(self, db):
        _seed_campaign_no_tracker("blank")
        result = get_campaign_stats("blank")
        assert result.source == SOURCE_EMPTY
        assert result.submissions == []

    def test_api_success_populates_from_submissions(self, db):
        _seed_campaign_with_tracker("alpha", "tk-1")
        submissions = [
            Submission(video_url="https://tt.com/v/x", views=1000, likes=100,
                       comments=5, shares=2, engagement_rate=0.1),
            Submission(video_url="https://tt.com/v/y", views=2000, likes=200,
                       comments=10, shares=4, engagement_rate=0.05),
        ]
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_ok_fetch("tk-1", submissions),
        ):
            result = get_campaign_stats("alpha")
        assert result.source == SOURCE_API
        assert result.tracker_id == "tk-1"
        assert result.total_views == 3000
        assert result.total_likes == 300
        assert result.total_comments == 15
        assert result.total_shares == 6
        assert result.post_count == 2
        assert result.fetched_at == "2026-05-14T12:00:00Z"
        assert result.stale_since == ""

    def test_api_failure_with_no_cache_falls_back_to_scraper(self, db):
        cid = _seed_campaign_with_tracker("beta", "tk-2")
        _seed_matched_videos(cid, [
            dict(url="https://tt.com/v/1", account="@a", views=50, likes=5),
        ])
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_err_fetch("tk-2", "http_5xx"),
        ):
            result = get_campaign_stats("beta")
        assert result.source == SOURCE_SCRAPER_FALLBACK
        assert result.error_kind == "http_5xx"
        assert result.total_views == 50

    def test_api_failure_serves_stale_cache(self, db):
        _seed_campaign_with_tracker("gamma", "tk-3")
        # Prime cache with a successful fetch.
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_ok_fetch("tk-3", [
                Submission(video_url="https://tt.com/v/a", views=999),
            ]),
        ):
            get_campaign_stats("gamma")
        # Now force a stale read by zeroing TTL + simulating API failure.
        with patch.dict("os.environ", {"TIDES_TRACKER_CACHE_TTL_SECONDS": "0"}):
            with patch.object(
                campaign_stats, "fetch_campaign_submissions",
                return_value=_err_fetch("tk-3", "timeout"),
            ):
                result = get_campaign_stats("gamma")
        assert result.source == SOURCE_API_CACHED
        assert result.total_views == 999
        assert result.error_kind == "timeout"
        assert result.stale_since != ""

    def test_cache_hit_skips_api(self, db):
        _seed_campaign_with_tracker("delta", "tk-4")
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_ok_fetch("tk-4", [Submission(video_url="https://x", views=1)]),
        ) as mocked:
            get_campaign_stats("delta")
            get_campaign_stats("delta")
            get_campaign_stats("delta")
            assert mocked.call_count == 1

    def test_force_refresh_bypasses_cache(self, db):
        _seed_campaign_with_tracker("eps", "tk-5")
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_ok_fetch("tk-5", [Submission(video_url="https://x", views=1)]),
        ) as mocked:
            get_campaign_stats("eps")
            get_campaign_stats("eps", force_refresh=True)
            assert mocked.call_count == 2

    def test_hydration_does_not_mutate_cached_submission(self, db):
        # Cache integrity: the cached Submission must stay pristine after
        # field-gap hydration so subsequent reads see the API's true
        # output, not a hydrated derivative.
        cid = _seed_campaign_with_tracker("kappa", "tk-k")
        _seed_matched_videos(cid, [
            dict(url="https://tt.com/v/p", account="@u", views=0, likes=0,
                 upload_date="2026-04-01"),
        ])
        original_sub = Submission(video_url="https://tt.com/v/p", views=500, posted_at="")
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_ok_fetch("tk-k", [original_sub]),
        ):
            result = get_campaign_stats("kappa")
        # The hydrated result reflects scraper data.
        assert result.submissions[0].posted_at == "2026-04-01"
        # The original submission passed into the cache is unchanged.
        assert original_sub.posted_at == ""

    def test_field_gap_hydrates_posted_at_from_scraper(self, db):
        cid = _seed_campaign_with_tracker("zeta", "tk-6")
        _seed_matched_videos(cid, [
            dict(url="https://tt.com/v/p", account="@u", views=0, likes=0,
                 upload_date="2026-04-01"),
        ])
        # API returns submission with empty posted_at — same URL.
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_ok_fetch("tk-6", [
                Submission(video_url="https://tt.com/v/p", views=500, posted_at=""),
            ]),
        ):
            result = get_campaign_stats("zeta")
        assert result.submissions[0].posted_at == "2026-04-01"
        assert result.submissions[0].views == 500

    def test_resolves_tracker_via_overlay_table(self, db):
        # No tracker_campaign_id on the row — but a link in the overlay.
        with _db.get_session() as s:
            s.add(Campaign(slug="omega", title="omega"))
            s.add(TrackerCampaignLink(tracker_id="tk-omega", campaign_slug="omega"))
            s.commit()
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_ok_fetch("tk-omega", [Submission(video_url="x", views=42)]),
        ):
            result = get_campaign_stats("omega")
        assert result.source == SOURCE_API
        assert result.tracker_id == "tk-omega"
        assert result.total_views == 42


class TestFallbackRoundFilter:
    """CAMP-55: scraper-fallback path must scope matched_videos to the
    campaign's ``start_date`` so a round-2 campaign doesn't roll up
    round-1 view counts when the API path is unavailable.
    """

    def test_no_tracker_fallback_excludes_pre_start_videos(self, db):
        cid = _seed_campaign_no_tracker("r2-no-tracker")
        _seed_matched_videos(cid, [
            # Round 1 post — should be filtered out.
            dict(url="https://tt.com/v/r1", account="@a",
                 timestamp="2026-04-15T14:32:00",
                 upload_date="20260415",
                 views=10_000, likes=500),
            # Round 2 post — kept.
            dict(url="https://tt.com/v/r2", account="@a",
                 timestamp="2026-05-10T09:00:00",
                 upload_date="20260510",
                 views=200, likes=20),
        ])
        result = get_campaign_stats("r2-no-tracker", start_date="2026-05-01")
        assert result.source == SOURCE_SCRAPER_FALLBACK
        assert result.error_kind == "no_tracker"
        assert result.post_count == 1
        assert result.total_views == 200
        assert result.total_likes == 20

    def test_api_failure_fallback_excludes_pre_start_videos(self, db):
        cid = _seed_campaign_with_tracker("r2-api-down", "tk-r2")
        _seed_matched_videos(cid, [
            dict(url="https://tt.com/v/r1a", account="@a",
                 timestamp="2026-04-10T10:00:00", upload_date="20260410",
                 views=5_000, likes=100),
            dict(url="https://tt.com/v/r2a", account="@a",
                 timestamp="2026-05-05T10:00:00", upload_date="20260505",
                 views=120, likes=12),
        ])
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_err_fetch("tk-r2", "http_5xx"),
        ):
            result = get_campaign_stats("r2-api-down", start_date="2026-05-01")
        assert result.source == SOURCE_SCRAPER_FALLBACK
        assert result.error_kind == "http_5xx"
        assert result.post_count == 1
        assert result.total_views == 120

    def test_fallback_keeps_videos_with_no_post_date(self, db):
        """Fail-open: legacy rows missing timestamp + upload_date stay visible.

        Mirrors ``video_posted_before_start`` semantics — hiding a real
        match because metadata is incomplete is worse than the duplicate-
        in-Cobrand symptom this filter exists to prevent.
        """
        cid = _seed_campaign_no_tracker("r2-legacy")
        _seed_matched_videos(cid, [
            dict(url="https://tt.com/v/legacy", account="@a", views=100, likes=10),
        ])
        result = get_campaign_stats("r2-legacy", start_date="2026-05-01")
        assert result.source == SOURCE_SCRAPER_FALLBACK
        assert result.post_count == 1
        assert result.total_views == 100

    def test_fallback_with_no_start_date_keeps_all_videos(self, db):
        """Default behaviour (no start_date passed) matches pre-CAMP-55."""
        cid = _seed_campaign_no_tracker("r1-only")
        _seed_matched_videos(cid, [
            dict(url="https://tt.com/v/old", account="@a",
                 timestamp="2026-01-01T00:00:00", upload_date="20260101",
                 views=999, likes=99),
            dict(url="https://tt.com/v/new", account="@a",
                 timestamp="2026-05-15T00:00:00", upload_date="20260515",
                 views=1, likes=0),
        ])
        result = get_campaign_stats("r1-only")
        assert result.source == SOURCE_SCRAPER_FALLBACK
        assert result.post_count == 2
        assert result.total_views == 1000

    def test_fallback_uses_upload_date_when_timestamp_missing(self, db):
        cid = _seed_campaign_no_tracker("r2-upload-date-only")
        _seed_matched_videos(cid, [
            dict(url="https://tt.com/v/r1", account="@a",
                 upload_date="20260420", views=999),
            dict(url="https://tt.com/v/r2", account="@a",
                 upload_date="20260520", views=42),
        ])
        result = get_campaign_stats(
            "r2-upload-date-only", start_date="2026-05-01",
        )
        assert result.post_count == 1
        assert result.total_views == 42

    def test_api_success_ignores_start_date(self, db):
        """When the API path serves the result, ``start_date`` is a no-op.

        The tracker is round-scoped server-side, so we don't double-
        filter; the scraper rows only get touched for field-gap
        hydration of ``posted_at``/``follower_count``.
        """
        cid = _seed_campaign_with_tracker("api-ok", "tk-api-ok")
        _seed_matched_videos(cid, [
            # A "round 1" scraper row — would be filtered if we ran it
            # through video_posted_before_start.
            dict(url="https://tt.com/v/api", account="@a",
                 timestamp="2026-04-10T00:00:00", upload_date="20260410"),
        ])
        with patch.object(
            campaign_stats, "fetch_campaign_submissions",
            return_value=_ok_fetch("tk-api-ok", [
                Submission(video_url="https://tt.com/v/api", views=777,
                           posted_at=""),
            ]),
        ):
            result = get_campaign_stats("api-ok", start_date="2026-05-01")
        # API path serves the submission; pre-start scraper row contributes
        # only its posted_at to field-gap hydration.
        assert result.source == SOURCE_API
        assert result.post_count == 1
        assert result.total_views == 777
        # ``posted_at`` is hydrated from the scraper row as-is — the API
        # path doesn't re-filter by date because the tracker is already
        # round-scoped server-side.
        assert result.submissions[0].posted_at == "20260410"


class TestGetCampaignStatsBulk:
    def test_threads_start_date_per_slug_into_fallback(self, db):
        cid_a = _seed_campaign_no_tracker("bulk-a")
        cid_b = _seed_campaign_no_tracker("bulk-b")
        _seed_matched_videos(cid_a, [
            dict(url="https://tt.com/v/a-r1", account="@a",
                 timestamp="2026-04-10T00:00:00", upload_date="20260410",
                 views=1000),
            dict(url="https://tt.com/v/a-r2", account="@a",
                 timestamp="2026-05-10T00:00:00", upload_date="20260510",
                 views=10),
        ])
        _seed_matched_videos(cid_b, [
            dict(url="https://tt.com/v/b-pre", account="@b",
                 timestamp="2026-03-01T00:00:00", upload_date="20260301",
                 views=5000),
            dict(url="https://tt.com/v/b-post", account="@b",
                 timestamp="2026-06-01T00:00:00", upload_date="20260601",
                 views=20),
        ])
        out = get_campaign_stats_bulk(
            ["bulk-a", "bulk-b"],
            start_date_by_slug={
                "bulk-a": "2026-05-01",
                "bulk-b": "2026-05-15",
            },
        )
        assert out["bulk-a"].total_views == 10
        assert out["bulk-b"].total_views == 20

    def test_missing_slug_in_start_date_map_falls_back_open(self, db):
        cid = _seed_campaign_no_tracker("bulk-c")
        _seed_matched_videos(cid, [
            dict(url="https://tt.com/v/c1", account="@c",
                 timestamp="2026-01-01T00:00:00", upload_date="20260101",
                 views=999),
        ])
        out = get_campaign_stats_bulk(["bulk-c"], start_date_by_slug={})
        # Missing → empty string → no filter → row kept.
        assert out["bulk-c"].total_views == 999


class TestOverlayVideoStats:
    def test_empty_inputs(self):
        assert overlay_video_stats([], []) == []

    def test_overlays_views_likes_when_url_matches(self):
        rows = [
            dict(url="https://tt.com/v/1", account="@a", views=10, likes=1,
                 song="Old Town"),
        ]
        subs = [
            Submission(video_url="https://tt.com/v/1", views=999, likes=99,
                       comments=5, shares=2, engagement_rate=0.07),
        ]
        out = overlay_video_stats(rows, subs)
        assert out[0]["views"] == 999
        assert out[0]["likes"] == 99
        assert out[0]["comments"] == 5
        assert out[0]["shares"] == 2
        assert out[0]["engagement_rate"] == 0.07
        # Scraper-only fields preserved.
        assert out[0]["song"] == "Old Town"

    def test_unmatched_rows_keep_scraper_numbers(self):
        rows = [
            dict(url="https://tt.com/v/A", views=5, likes=1),
            dict(url="https://tt.com/v/B", views=7, likes=2),
        ]
        subs = [Submission(video_url="https://tt.com/v/A", views=100, likes=10)]
        out = overlay_video_stats(rows, subs)
        assert out[0]["views"] == 100
        assert out[1]["views"] == 7
        # New keys present on both rows.
        assert "comments" in out[1]
        assert "shares" in out[1]

    def test_url_normalization_matches_querystring_variants(self):
        rows = [dict(url="https://tt.com/v/1?utm=tiktok", views=5)]
        subs = [Submission(video_url="https://tt.com/v/1/", views=42)]
        out = overlay_video_stats(rows, subs)
        assert out[0]["views"] == 42

    def test_does_not_mutate_input(self):
        rows = [dict(url="https://tt.com/v/1", views=10)]
        subs = [Submission(video_url="https://tt.com/v/1", views=999)]
        _ = overlay_video_stats(rows, subs)
        assert rows[0]["views"] == 10  # input untouched


class TestLivePostsSource:
    """live_posts (delivery count) sources from the tracker when it attests,
    scraper-side posts_done otherwise. (Jake's Claude request, 2026-07-01)"""

    def _creators(self):
        return [
            {"username": "a", "status": "active", "posts_done": 2},
            {"username": "b", "status": "active", "posts_done": 3},
            {"username": "c", "status": "removed", "posts_done": 9},
        ]

    def _result(self, source, n_subs):
        from campaign_manager.services.campaign_stats import (
            CampaignStatsResult, Submission,
        )
        subs = [Submission(video_url=f"https://t/{i}") for i in range(n_subs)]
        return CampaignStatsResult(slug="s", source=source, submissions=subs)

    def test_tracker_api_wins(self):
        from campaign_manager.blueprints.campaigns import _stats_from_result
        stats = _stats_from_result({}, self._creators(), self._result("api", 8))
        assert stats["live_posts"] == 8  # tracker count, not 5

    def test_cached_tracker_wins(self):
        from campaign_manager.blueprints.campaigns import _stats_from_result
        stats = _stats_from_result({}, self._creators(), self._result("api_cached", 7))
        assert stats["live_posts"] == 7

    def test_no_tracker_falls_back_to_posts_done(self):
        from campaign_manager.blueprints.campaigns import _stats_from_result
        stats = _stats_from_result({}, self._creators(), self._result("scraper_fallback", 4))
        assert stats["live_posts"] == 5  # 2+3, removed creator excluded
