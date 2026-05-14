"""Tests for campaign_manager.services.tides_tracker (RTA-42)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from campaign_manager.models import TidesTrackerSyncLog, TrackerName
from campaign_manager.services import tides_tracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _video(
    *,
    url: str = "https://tiktok.com/@user/video/123",
    views: int = 1000,
    likes: int = 100,
    comments: int = 10,
    shares: int = 5,
    creator: str = "user",
    engagement_rate: float = 0.05,
    followers: int = 10_000,
):
    """Build a public-API video dict for tests (snake_case shape)."""
    return {
        "video_url": url,
        "creator_username": creator,
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "engagement_rate": engagement_rate,
        "follower_count": followers,
        "posted_at": "2026-05-01T12:00:00Z",
    }


def _mock_response(status_code: int = 200, json_payload=None, raise_json: bool = False):
    """Build a fake `requests.Response` for patching `requests.get`."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = "" if json_payload is None else "<body>"
    if raise_json:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_payload if json_payload is not None else {}
    return resp


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


class TestCoercion:
    def test_int_handles_none(self):
        assert tides_tracker._coerce_int(None) == 0

    def test_int_handles_numeric_string(self):
        assert tides_tracker._coerce_int("42") == 42

    def test_int_handles_float_string(self):
        # Some payloads return numeric strings that aren't pure ints.
        assert tides_tracker._coerce_int("3.7") == 3

    def test_int_handles_garbage(self):
        assert tides_tracker._coerce_int("nope") == 0

    def test_float_handles_none(self):
        assert tides_tracker._coerce_float(None) == 0.0

    def test_float_handles_int(self):
        assert tides_tracker._coerce_float(5) == 5.0

    def test_float_handles_garbage(self):
        assert tides_tracker._coerce_float("nope") == 0.0

    def test_str_handles_none(self):
        assert tides_tracker._coerce_str(None) == ""

    def test_str_handles_int(self):
        assert tides_tracker._coerce_str(42) == "42"


class TestPick:
    def test_returns_first_matching_key(self):
        assert tides_tracker._pick({"video_url": "x"}, "video_url", "videoUrl") == "x"

    def test_falls_through_to_camelcase(self):
        assert tides_tracker._pick({"videoUrl": "x"}, "video_url", "videoUrl") == "x"

    def test_skips_explicit_none(self):
        # An explicit None on the snake key falls through to the camel key.
        d = {"video_url": None, "videoUrl": "x"}
        assert tides_tracker._pick(d, "video_url", "videoUrl") == "x"

    def test_returns_none_when_nothing_matches(self):
        assert tides_tracker._pick({}, "video_url", "url") is None


# ---------------------------------------------------------------------------
# parse_submission
# ---------------------------------------------------------------------------


class TestParseSubmission:
    def test_happy_path_snake_case(self):
        s = tides_tracker._parse_submission(_video())
        assert s.video_url == "https://tiktok.com/@user/video/123"
        assert s.creator_username == "user"
        assert s.views == 1000
        assert s.likes == 100
        assert s.comments == 10
        assert s.shares == 5
        assert s.engagement_rate == 0.05
        assert s.follower_count == 10_000
        assert s.posted_at == "2026-05-01T12:00:00Z"
        # raw is preserved so RTA-43/44 can dig into untyped fields.
        assert s.raw["video_url"] == "https://tiktok.com/@user/video/123"

    def test_camel_case_aliases_accepted(self):
        v = {
            "videoUrl": "https://tiktok.com/@x/video/1",
            "creatorUsername": "x",
            "viewCount": 50,
            "likeCount": 5,
            "commentCount": 1,
            "shareCount": 0,
            "engagementRate": 0.12,
            "followerCount": 2000,
            "createdAt": "2026-05-02T00:00:00Z",
        }
        s = tides_tracker._parse_submission(v)
        assert s.video_url == "https://tiktok.com/@x/video/1"
        assert s.creator_username == "x"
        assert s.views == 50
        assert s.engagement_rate == 0.12
        assert s.follower_count == 2000
        assert s.posted_at == "2026-05-02T00:00:00Z"

    def test_missing_fields_default_to_zeros_and_empty(self):
        s = tides_tracker._parse_submission({})
        assert s.video_url == ""
        assert s.views == 0
        assert s.engagement_rate == 0.0
        assert s.raw == {}

    def test_to_dict_excludes_raw(self):
        s = tides_tracker._parse_submission(_video())
        d = s.to_dict()
        assert "raw" not in d
        assert d["views"] == 1000


# ---------------------------------------------------------------------------
# fetch_campaign_submissions — never raises
# ---------------------------------------------------------------------------


class TestFetchCampaignSubmissions:
    def test_happy_path_returns_typed_submissions(self):
        payload = {
            "fetched_at": "2026-05-13T10:00:00Z",
            "videos": [_video(url="https://tiktok.com/@a/video/1"),
                       _video(url="https://tiktok.com/@b/video/2", creator="b")],
        }
        with patch.object(
            tides_tracker.requests, "get",
            return_value=_mock_response(200, payload),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc-123")
        assert r.ok is True
        assert r.tracker_id == "abc-123"
        assert r.count == 2
        assert r.submissions[0].video_url.endswith("/video/1")
        assert r.submissions[1].creator_username == "b"
        assert r.fetched_at == "2026-05-13T10:00:00Z"
        assert r.error_kind == ""

    def test_missing_tracker_id_short_circuits(self):
        # No HTTP call should happen for an empty input.
        with patch.object(tides_tracker.requests, "get") as get_mock:
            r = tides_tracker.fetch_campaign_submissions("")
        assert r.ok is False
        assert r.error_kind == "missing_tracker_id"
        get_mock.assert_not_called()

    def test_whitespace_tracker_id_is_missing(self):
        r = tides_tracker.fetch_campaign_submissions("   ")
        assert r.ok is False
        assert r.error_kind == "missing_tracker_id"

    def test_timeout_returns_fail_soft(self):
        with patch.object(
            tides_tracker.requests, "get",
            side_effect=requests.Timeout("timed out"),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc")
        assert r.ok is False
        assert r.error_kind == "timeout"
        assert r.submissions == []

    def test_connection_error_returns_fail_soft(self):
        with patch.object(
            tides_tracker.requests, "get",
            side_effect=requests.ConnectionError("dns fail"),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc")
        assert r.ok is False
        assert r.error_kind == "connection"

    def test_generic_request_exception_is_bucketed(self):
        with patch.object(
            tides_tracker.requests, "get",
            side_effect=requests.RequestException("weird"),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc")
        assert r.ok is False
        assert r.error_kind == "request_error"

    def test_http_404_bucketed_as_4xx(self):
        with patch.object(
            tides_tracker.requests, "get",
            return_value=_mock_response(404, {"error": "not found"}),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc")
        assert r.ok is False
        assert r.error_kind == "http_4xx"
        assert r.status_code == 404

    def test_http_503_bucketed_as_5xx(self):
        with patch.object(
            tides_tracker.requests, "get",
            return_value=_mock_response(503, {}),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc")
        assert r.ok is False
        assert r.error_kind == "http_5xx"
        assert r.status_code == 503

    def test_bad_json_returns_structured_error(self):
        with patch.object(
            tides_tracker.requests, "get",
            return_value=_mock_response(200, raise_json=True),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc")
        assert r.ok is False
        assert r.error_kind == "bad_json"

    def test_payload_without_videos_array(self):
        with patch.object(
            tides_tracker.requests, "get",
            return_value=_mock_response(200, {"unexpected": "shape"}),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc")
        assert r.ok is False
        assert r.error_kind == "bad_payload"

    def test_non_dict_videos_entries_are_skipped(self):
        # Defensive: a malformed entry in the array shouldn't kill the whole fetch.
        payload = {"videos": [_video(), "garbage", None, _video(url="https://x/video/9")]}
        with patch.object(
            tides_tracker.requests, "get",
            return_value=_mock_response(200, payload),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc")
        assert r.ok is True
        assert r.count == 2

    def test_fetched_at_falls_back_to_now_when_missing(self):
        # Payload doesn't include fetched_at — we still emit one for downstream.
        with patch.object(
            tides_tracker.requests, "get",
            return_value=_mock_response(200, {"videos": []}),
        ):
            r = tides_tracker.fetch_campaign_submissions("abc")
        assert r.ok is True
        assert r.fetched_at != ""


# ---------------------------------------------------------------------------
# pull_all_trackers — audit log + per-tracker outcomes
# ---------------------------------------------------------------------------


def _seed_tracker_names(db, tracker_ids):
    """Insert TrackerName rows so `_list_tracker_ids` returns them."""
    with db.get_session() as s:
        for tid in tracker_ids:
            s.add(TrackerName(tracker_id=tid, display_name=f"name-{tid}"))
        s.commit()


class TestPullAllTrackers:
    def test_writes_audit_row_with_aggregate_counts(self, db):
        _seed_tracker_names(db, ["t1", "t2"])

        def fake_fetch(tid):
            if tid == "t1":
                return tides_tracker.TidesTrackerFetchResult(
                    ok=True, tracker_id=tid,
                    submissions=[tides_tracker._parse_submission(_video())] * 3,
                )
            return tides_tracker.TidesTrackerFetchResult(
                ok=False, tracker_id=tid,
                error_kind="http_5xx", detail="boom",
            )

        with patch.object(tides_tracker, "fetch_campaign_submissions", side_effect=fake_fetch):
            result = tides_tracker.pull_all_trackers(triggered_by="manual:test")

        assert result.trackers_total == 2
        assert result.trackers_succeeded == 1
        assert result.trackers_failed == 1
        assert result.submissions_fetched == 3
        assert result.sync_log_id > 0

        with db.get_session() as s:
            log = s.query(TidesTrackerSyncLog).one()
            assert log.id == result.sync_log_id
            assert log.sync_type == "pull"
            assert log.trackers_total == 2
            assert log.trackers_succeeded == 1
            assert log.trackers_failed == 1
            assert log.submissions_fetched == 3
            assert log.triggered_by == "manual:test"
            assert log.finished_at is not None

            kinds = sorted(e["error_kind"] for e in (log.errors or []))
            assert kinds == ["http_5xx", "ok"]

    def test_no_trackers_still_writes_audit_row(self, db):
        # Bare DB — no TrackerName rows exist yet.
        with patch.object(tides_tracker, "fetch_campaign_submissions") as fetch_mock:
            result = tides_tracker.pull_all_trackers()
        fetch_mock.assert_not_called()
        assert result.trackers_total == 0
        assert result.sync_log_id > 0

        with db.get_session() as s:
            log = s.query(TidesTrackerSyncLog).one()
            assert log.trackers_total == 0

    def test_unexpected_exception_in_loop_does_not_kill_run(self, db):
        # `fetch_campaign_submissions` is documented to never raise, but if a
        # regression makes it raise we still want the loop + audit row.
        _seed_tracker_names(db, ["t1", "t2"])

        def boom(tid):
            if tid == "t1":
                raise RuntimeError("regression")
            return tides_tracker.TidesTrackerFetchResult(
                ok=True, tracker_id=tid, submissions=[],
            )

        with patch.object(tides_tracker, "fetch_campaign_submissions", side_effect=boom):
            result = tides_tracker.pull_all_trackers()

        assert result.trackers_failed >= 1
        assert any(
            e["error_kind"] == "unexpected_exception" for e in result.errors
        )

    def test_default_triggered_by_is_cron(self, db):
        _seed_tracker_names(db, ["t1"])
        with patch.object(
            tides_tracker, "fetch_campaign_submissions",
            return_value=tides_tracker.TidesTrackerFetchResult(
                ok=True, tracker_id="t1", submissions=[],
            ),
        ):
            tides_tracker.pull_all_trackers()
        with db.get_session() as s:
            log = s.query(TidesTrackerSyncLog).one()
            assert log.triggered_by == "cron"


# ---------------------------------------------------------------------------
# Cron tick — in-flight guard, error isolation, env interval
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_inflight_guard():
    """Ensure each test sees a clean guard, in case a prior test crashed."""
    tides_tracker._tides_tracker_pull_in_progress = False
    yield
    tides_tracker._tides_tracker_pull_in_progress = False


class TestRunTick:
    def test_tick_calls_pull_with_cron_triggered_by(self):
        with patch.object(
            tides_tracker, "pull_all_trackers",
            return_value=tides_tracker.PullResult(sync_log_id=1),
        ) as pull_mock:
            tides_tracker.run_tides_tracker_pull()
        pull_mock.assert_called_once_with(triggered_by="cron")

    def test_tick_does_not_raise_when_pull_raises(self):
        with patch.object(
            tides_tracker, "pull_all_trackers",
            side_effect=RuntimeError("explosion"),
        ):
            tides_tracker.run_tides_tracker_pull()  # must not raise

        # And the guard is cleared so the next tick can run.
        assert tides_tracker._tides_tracker_pull_in_progress is False

    def test_second_call_during_first_is_noop(self):
        import threading
        started = threading.Event()
        release = threading.Event()

        def slow_pull(**_):
            started.set()
            assert release.wait(timeout=5), "test setup deadlock"
            return tides_tracker.PullResult(sync_log_id=1)

        with patch.object(
            tides_tracker, "pull_all_trackers", side_effect=slow_pull,
        ) as pull_mock:
            t = threading.Thread(target=tides_tracker.run_tides_tracker_pull)
            t.start()
            assert started.wait(timeout=5)

            # Second invocation should see the guard and bail.
            tides_tracker.run_tides_tracker_pull()

            release.set()
            t.join(timeout=5)

            assert pull_mock.call_count == 1


class TestInterval:
    def test_default_is_30(self, monkeypatch):
        monkeypatch.delenv("TIDES_TRACKER_PULL_INTERVAL_MINUTES", raising=False)
        assert (
            tides_tracker.get_tides_tracker_interval_minutes()
            == tides_tracker.TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES
            == 30
        )

    def test_override_to_15(self, monkeypatch):
        monkeypatch.setenv("TIDES_TRACKER_PULL_INTERVAL_MINUTES", "15")
        assert tides_tracker.get_tides_tracker_interval_minutes() == 15

    def test_zero_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("TIDES_TRACKER_PULL_INTERVAL_MINUTES", "0")
        assert (
            tides_tracker.get_tides_tracker_interval_minutes()
            == tides_tracker.TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES
        )

    def test_negative_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("TIDES_TRACKER_PULL_INTERVAL_MINUTES", "-1")
        assert (
            tides_tracker.get_tides_tracker_interval_minutes()
            == tides_tracker.TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES
        )

    def test_above_max_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(
            "TIDES_TRACKER_PULL_INTERVAL_MINUTES",
            str(tides_tracker.TIDES_TRACKER_MAX_INTERVAL_MINUTES + 1),
        )
        assert (
            tides_tracker.get_tides_tracker_interval_minutes()
            == tides_tracker.TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES
        )

    def test_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("TIDES_TRACKER_PULL_INTERVAL_MINUTES", "not-an-int")
        assert (
            tides_tracker.get_tides_tracker_interval_minutes()
            == tides_tracker.TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES
        )
