"""Chartmetric pop-score client + campaign endpoints (HTTP fully faked)."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from campaign_manager.services import chartmetric as cm


def _resp(status=200, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    r.text = str(body)
    return r


TRACK_OBJ = {
    "name": "Espresso",
    "artists": [{"name": "Sabrina Carpenter"}],
    "image_url": "img",
    "cm_statistics": {"sp_popularity": 87, "score": 99.3, "sp_streams": 3196473434},
}
HISTORY_OBJ = [
    {"track_domain_id": "old", "data": [
        {"timestp": "2026-09-01T00:00:00.000Z", "value": 40},
    ]},
    {"track_domain_id": "main", "data": [
        {"timestp": "2026-08-20T00:00:00.000Z", "value": 80},
        {"timestp": "2026-09-01T00:00:00.000Z", "value": 82},
        {"timestp": "2026-09-20T00:00:00.000Z", "value": 87},
    ]},
]


def _client_with(routes):
    """routes: path-substring -> response; token exchange always succeeds."""
    http = MagicMock()
    http.post.return_value = _resp(200, {"token": "acc", "expires_in": 3600})

    def fake_get(url, params=None, headers=None, timeout=None):
        for key, res in routes.items():
            if key in url:
                return res
        return _resp(404)

    http.get.side_effect = fake_get
    return cm.ChartmetricClient("refresh", session=http), http


@pytest.fixture(autouse=True)
def no_throttle():
    with patch.object(cm, "MIN_REQUEST_INTERVAL_S", 0), patch.object(cm.time, "sleep"):
        yield


class TestParseTrackLink:
    @pytest.mark.parametrize("raw,kind,value", [
        ("https://open.spotify.com/track/2qSkIjg1o9h3YT9RAgYN75?si=abc", "spotify", "2qSkIjg1o9h3YT9RAgYN75"),
        ("https://open.spotify.com/intl-de/track/2qSkIjg1o9h3YT9RAgYN75", "spotify", "2qSkIjg1o9h3YT9RAgYN75"),
        ("spotify:track:2qSkIjg1o9h3YT9RAgYN75", "spotify", "2qSkIjg1o9h3YT9RAgYN75"),
        ("https://app.chartmetric.com/track?id=118981138", "chartmetric", "118981138"),
        ("https://app.chartmetric.com/track/118981138/", "chartmetric", "118981138"),
        ("USUM72403305", "isrc", "USUM72403305"),
        ("us-um7-24-03305", "isrc", "USUM72403305"),
    ])
    def test_accepted_formats(self, raw, kind, value):
        assert cm.parse_track_link(raw) == cm.TrackRef(kind, value)

    @pytest.mark.parametrize("raw", ["", "https://open.spotify.com/album/abc", "espresso"])
    def test_rejects_unknown(self, raw):
        with pytest.raises(cm.ChartmetricError):
            cm.parse_track_link(raw)


class TestClient:
    def test_resolves_spotify_to_chartmetric_id(self):
        client, _ = _client_with({"/get-ids": _resp(200, {"obj": [{"chartmetric_ids": [118981138]}]})})
        assert client.resolve_track_id(cm.TrackRef("spotify", "x" * 22)) == 118981138

    def test_unknown_track_raises(self):
        client, _ = _client_with({"/get-ids": _resp(200, {"obj": [{"chartmetric_ids": []}]})})
        with pytest.raises(cm.ChartmetricError):
            client.resolve_track_id(cm.TrackRef("isrc", "USUM72403305"))

    def test_snapshot_reads_popularity(self):
        client, _ = _client_with({"/track/118981138": _resp(200, {"obj": TRACK_OBJ})})
        snap = client.track_snapshot(118981138)
        assert snap.spotify_popularity == 87
        assert snap.artists == ("Sabrina Carpenter",)

    def test_history_picks_primary_series_and_filters_since(self):
        client, _ = _client_with({"most-history": _resp(200, {"obj": HISTORY_OBJ})})
        hist = client.popularity_history(1, since=date(2026, 8, 25))
        assert hist == [{"date": "2026-09-01", "value": 82}, {"date": "2026-09-20", "value": 87}]
        assert client._http.get.call_args.kwargs["params"] == {"type": "popularity", "since": "2026-08-25"}

    def test_reading_on_exact_since_date_is_retained_and_empty_payloads_are_safe(self):
        exact = [{"track_domain_id": "x", "data": [{"timestp": "2026-08-25", "value": 4}]}]
        client, _ = _client_with({"most-history": _resp(200, {"obj": exact})})
        assert client.streams_history(1, since=date(2026, 8, 25)) == [{"date": "2026-08-25", "value": 4}]
        for payload in (None, [], {"obj": None}, {"obj": [{"data": []}]}, {"obj": [{"data": [{"timestp": "bad", "value": "x"}]}]}):
            empty, _ = _client_with({"most-history": _resp(200, payload)})
            assert empty.streams_history(1) == []

    def test_streams_history_selects_primary_and_passes_since(self):
        client, _ = _client_with({"most-history": _resp(200, {"obj": HISTORY_OBJ})})
        hist = client.streams_history(1, since=date(2026, 8, 25), track_domain_id="main")
        assert hist == [{"date": "2026-09-01", "value": 82}, {"date": "2026-09-20", "value": 87}]
        assert client._http.get.call_args.kwargs["params"] == {"type": "streams", "since": "2026-08-25"}

    def test_popularity_track_domain_id_uses_real_client_series_selection(self):
        client, _ = _client_with({"most-history": _resp(200, {"obj": HISTORY_OBJ})})
        assert client.popularity_track_domain_id(1) == "main"

    def test_streams_keeps_repeated_cumulative_points_and_skips_invalid_values(self):
        series = [{"track_domain_id": "x", "data": [
            {"timestp": "2026-08-07", "value": "3126151554"},
            {"timestp": "2026-08-08", "value": "3126151554.0"},
            {"timestp": "2026-08-09", "value": "3129082729"},
            {"timestp": "bad-date", "value": 8},
            {"timestp": "2026-08-10", "value": "oops"},
        ]}]
        client, _ = _client_with({"most-history": _resp(200, {"obj": series})})
        assert client.streams_history(1) == [{"date": "2026-08-07", "value": 3126151554}, {"date": "2026-08-08", "value": 3126151554}, {"date": "2026-08-09", "value": 3129082729}]

    def test_tiktok_posts_history_picks_newest_valid_series_and_filters_since(self):
        rows = [
            {"track_domain_id": None, "data": [{"timestp": "2026-08-01", "value": 4}]},
            {"track_domain_id": None, "data": [{"timestp": "2026-08-10", "value": 8}, {"timestp": "bad", "value": 9}]},
        ]
        client, _ = _client_with({"most-history": _resp(200, {"obj": rows})})
        assert client.tiktok_posts_history(1, since=date(2026, 8, 5)) == [{"date": "2026-08-10", "value": 8}]

    def test_streams_keeps_entire_repeat_runs(self):
        rows = [{"track_domain_id": "x", "data": [
            {"timestp": "2026-09-24", "value": 3191203786},
            {"timestp": "2026-09-25", "value": 3193825920},
            {"timestp": "2026-09-26", "value": 3193825920},
            {"timestp": "2026-09-27", "value": 3195168217},
        ]}]
        client, _ = _client_with({"most-history": _resp(200, {"obj": rows})})
        assert client.streams_history(1) == [
            {"date": "2026-09-24", "value": 3191203786}, {"date": "2026-09-25", "value": 3193825920},
            {"date": "2026-09-26", "value": 3193825920}, {"date": "2026-09-27", "value": 3195168217}]

    def test_streams_tail_repeat_run_keeps_every_reading(self):
        rows = [{"track_domain_id": "x", "data": [
            {"timestp": "2026-09-24", "value": 10}, {"timestp": "2026-09-25", "value": 12},
            {"timestp": "2026-09-26", "value": 12}, {"timestp": "2026-09-27", "value": 12}]}]
        client, _ = _client_with({"most-history": _resp(200, {"obj": rows})})
        assert client.streams_history(1) == [{"date": "2026-09-24", "value": 10}, {"date": "2026-09-25", "value": 12}, {"date": "2026-09-26", "value": 12}, {"date": "2026-09-27", "value": 12}]

    def test_series_selection_tolerates_one_day_gap_and_streams_follow_popularity_release(self):
        rows = [
            {"track_domain_id": "pop", "data": [{"timestp": "2026-09-10", "value": 900}]},
            {"track_domain_id": "stream", "data": [{"timestp": "2026-09-11", "value": 1000}]},
        ]
        client, _ = _client_with({"most-history": _resp(200, {"obj": rows})})
        assert cm._pick_primary_series(rows) is rows[1]["data"]
        client.popularity_history(1)
        assert client.streams_history(1, track_domain_id="pop") == [{"date": "2026-09-10", "value": 900}]

    @pytest.mark.parametrize("lag,eligible", [(3, True), (4, False)])
    def test_series_selection_recency_window_boundary(self, lag, eligible):
        newest = date(2026, 9, 10)
        rows = [
            {"track_domain_id": "latest", "data": [{"timestp": newest.isoformat(), "value": 50}]},
            {"track_domain_id": "strong", "data": [{"timestp": (newest - timedelta(days=lag)).isoformat(), "value": 99}]},
        ]
        selected = cm._pick_primary_object(rows)
        assert selected["track_domain_id"] == ("strong" if eligible else "latest")

    def test_token_reused_and_responses_cached(self):
        client, http = _client_with({"/track/1": _resp(200, {"obj": TRACK_OBJ})})
        client.track_snapshot(1)
        client.track_snapshot(1)
        assert http.post.call_count == 1
        assert http.get.call_count == 1

    def test_retries_once_on_429(self):
        client, http = _client_with({})
        http.get.side_effect = [_resp(429), _resp(200, {"obj": TRACK_OBJ})]
        assert client.track_snapshot(1).spotify_popularity == 87

    def test_bad_refresh_token_raises_friendly_error(self):
        client, http = _client_with({})
        http.post.return_value = _resp(401, {"error": "bad"})
        with pytest.raises(cm.ChartmetricError, match="refresh token"):
            client.track_snapshot(1)

    def test_missing_refresh_token(self):
        with pytest.raises(cm.ChartmetricError):
            cm.ChartmetricClient("")


@pytest.mark.integration
class TestPopScoreEndpoints:
    def _campaign(self, client, start="2026-09-01", title="Pop Test"):
        res = client.post("/api/campaign/create", json={"title": title, "budget": 1000})
        slug = res.get_json()["slug"]
        client.post(f"/api/campaign/{slug}/edit", json={"title": "Pop Test", "start_date": start})
        return slug

    def _fake(self):
        fake = MagicMock()
        fake.resolve_track_id.return_value = 118981138
        fake.track_snapshot.return_value = cm.TrackSnapshot(
            118981138, "Espresso", ("Sabrina Carpenter",), 87, 99.3, 3196473434, "img")
        fake.popularity_history.return_value = [
            {"date": "2026-08-20", "value": 80},
            {"date": "2026-09-01", "value": 82},
            {"date": "2026-09-20", "value": 87},
        ]
        fake.popularity_track_domain_id.return_value = "main"
        fake.streams_history.return_value = [
            {"date": "2026-08-18", "value": 100},
            {"date": "2026-09-01", "value": 170},
            {"date": "2026-09-20", "value": 360},
        ]
        return fake

    def test_unlinked_campaign(self, client):
        slug = self._campaign(client)
        assert client.get(f"/api/campaign/{slug}/pop-score").get_json() == {"linked": False}

    def test_link_then_read_score_with_lift(self, client):
        slug = self._campaign(client)
        fake = self._fake()
        with patch.object(cm, "get_client", return_value=fake):
            res = client.post(f"/api/campaign/{slug}/pop-score/track",
                              json={"link": "https://open.spotify.com/track/2qSkIjg1o9h3YT9RAgYN75"})
            assert res.status_code == 200
            body = client.get(f"/api/campaign/{slug}/pop-score").get_json()
        assert body["spotify_popularity"] == 87
        assert body["baseline"] == 82
        assert body["change_since_start"] == 5
        assert len(body["history"]) == 3
        assert body["end_date"] == ""
        assert body["followup_days"] == 28
        assert body["phase"] == "live"
        assert body["streams"]["start_total"] == 170
        assert body["streams_history"][1]["daily"] == 5.0

    def test_history_uses_21_day_lead_and_retains_baseline_before_14_day_window(self, client):
        slug = self._campaign(client, start="2026-09-01")
        fake = self._fake()
        fake.popularity_history.return_value = [{"date": "2026-08-11", "value": 50}, {"date": "2026-09-01", "value": 60}]
        fake.streams_history.return_value = [{"date": "2026-08-11", "value": 100}, {"date": "2026-09-01", "value": 310}]
        with patch.object(cm, "get_client", return_value=fake):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "USUM72403305"})
            body = client.get(f"/api/campaign/{slug}/pop-score").get_json()
        expected_since = date(2026, 8, 11)
        fake.popularity_history.assert_called_once_with(118981138, since=expected_since)
        fake.streams_history.assert_called_once_with(118981138, since=expected_since, track_domain_id="main")
        assert body["streams"]["baseline_daily"] == 10.0

    def test_calculation_exception_is_json_502(self, client):
        slug = self._campaign(client)
        with patch.object(cm, "get_client", return_value=self._fake()), patch("campaign_manager.blueprints.chartmetric.calculate_attribution", side_effect=RuntimeError("bad")):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "USUM72403305"})
            response = client.get(f"/api/campaign/{slug}/pop-score")
        assert response.status_code == 502
        assert response.get_json() == {"linked": True, "link": "USUM72403305", "error": "Couldn't calculate song attribution."}

    def test_real_client_streams_follow_the_popularity_release_end_to_end(self, client):
        slug = self._campaign(client)
        series = [
            {"track_domain_id": "old", "data": [{"timestp": "2026-09-01", "value": 1}]},
            {"track_domain_id": "main", "data": [{"timestp": "2026-09-01", "value": 80}]},
        ]
        http_routes = {
            "/track/118981138/spotify/stats/most-history": _resp(200, {"obj": series}),
            "/track/118981138": _resp(200, {"obj": TRACK_OBJ}),
        }
        real, http = _client_with(http_routes)
        with patch.object(cm, "get_client", return_value=real):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "https://app.chartmetric.com/track/118981138"})
            body = client.get(f"/api/campaign/{slug}/pop-score").get_json()
        stream_calls = [call for call in http.get.call_args_list if (call.kwargs.get("params") or {}).get("type") == "streams"]
        assert stream_calls and stream_calls[-1].kwargs["params"] == {"type": "streams", "since": "2026-08-11"}
        assert body["linked"] is True
        assert body["streams"]["start_total"] == 80

    def test_release_selection_when_popularity_track_is_not_highest_stream_series(self, client):
        slug = self._campaign(client, title="release-selection pin")
        def get(url, params=None, headers=None, timeout=None):
            if url.endswith("/track/118981138"):
                return _resp(200, {"obj": TRACK_OBJ})
            kind = (params or {}).get("type")
            if kind == "popularity":
                rows = [
                    {"track_domain_id": "pop-release", "data": [{"timestp": "2026-09-01", "value": 80}]},
                    {"track_domain_id": "alt-release", "data": [{"timestp": "2026-09-01", "value": 20}]},
                ]
            else:
                rows = [
                    {"track_domain_id": "pop-release", "data": [{"timestp": "2026-09-01", "value": 5}]},
                    {"track_domain_id": "alt-release", "data": [{"timestp": "2026-09-01", "value": 900}]},
                ]
            return _resp(200, {"obj": rows})
        http = MagicMock()
        http.post.return_value = _resp(200, {"token": "acc", "expires_in": 3600})
        http.get.side_effect = get
        real = cm.ChartmetricClient("refresh", session=http)
        with patch.object(cm, "get_client", return_value=real):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "https://app.chartmetric.com/track/118981138"})
            body = client.get(f"/api/campaign/{slug}/pop-score").get_json()
        assert body["popularity"]["start"] == 80
        assert body["streams"]["start_total"] == 5
        assert body["streams"]["start_total"] != 900

    def test_end_date_endpoint_returns_followup_lift_and_gains(self, client):
        slug = self._campaign(client)
        fake = self._fake()
        with patch.object(cm, "get_client", return_value=fake):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "USUM72403305"})
            client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-09-20"})
            body = client.get(f"/api/campaign/{slug}/pop-score").get_json()
        assert body["followup_end"] == "2026-10-18"
        assert body["streams"]["gained_campaign"] == 190
        assert body["streams"]["lift_pct_campaign"] is not None

    def test_finished_without_end_has_distinct_phase(self, client):
        slug = self._campaign(client)
        fake = self._fake()
        with patch.object(cm, "get_client", return_value=fake):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "USUM72403305"})
            with patch("campaign_manager.blueprints.chartmetric._load", return_value={"track_id": 118981138, "link": "USUM72403305", "start_date": "2026-09-01", "end_date": "", "completion_status": "completed"}):
                body = client.get(f"/api/campaign/{slug}/pop-score").get_json()
        assert body["phase"] == "finished_no_end"
        assert body["end_date"] == ""

    def test_post_events_are_campaign_scoped_and_dates_normalized(self, client):
        from campaign_manager import db
        first, second = self._campaign(client), self._campaign(client, title="Second Pop Test")
        db.save_matched_videos(first, [
            {"url": "https://tiktok/a", "upload_date": "20260901"},
            {"url": "https://tiktok/b", "upload_date": "2026-09-01T12:00:00"},
            {"url": "https://tiktok/blank", "upload_date": ""},
            {"url": "https://tiktok/old", "upload_date": "2026-08-01"},
            {"url": "https://tiktok/future", "upload_date": (date.today() + timedelta(days=1)).isoformat()},
        ])
        db.save_matched_videos(second, [{"url": "https://tiktok/other", "upload_date": "2026-09-01"}])
        fake = self._fake()
        with patch.object(cm, "get_client", return_value=fake):
            client.post(f"/api/campaign/{first}/pop-score/track", json={"link": "USUM72403305"})
            client.post(f"/api/campaign/{second}/pop-score/track", json={"link": "USUM72403305"})
            events = client.get(f"/api/campaign/{first}/pop-score").get_json()["post_events"]
        assert events == [{"date": "2026-09-01", "count": 2}]

    def test_two_campaigns_alternating_through_one_real_client_stay_segmented(self, client):
        from campaign_manager import db
        a, b = self._campaign(client, "2026-09-01"), self._campaign(client, "2026-09-10", title="Second Pop Test")
        db.save_matched_videos(a, [{"url": "https://tiktok/a", "upload_date": "2026-09-02"}])
        db.save_matched_videos(b, [{"url": "https://tiktok/b", "upload_date": "2026-09-11"}])
        snapshots = {
            111: {"obj": {**TRACK_OBJ, "cm_statistics": {"sp_popularity": 11, "sp_streams": 111}}},
            222: {"obj": {**TRACK_OBJ, "cm_statistics": {"sp_popularity": 22, "sp_streams": 222}}},
        }
        calls = []
        http = MagicMock()
        http.post.return_value = _resp(200, {"token": "acc", "expires_in": 3600})
        def get(url, params=None, headers=None, timeout=None):
            track_id = 111 if "/111" in url else 222
            calls.append((track_id, params or {}))
            if url.endswith(f"/track/{track_id}"):
                return _resp(200, snapshots[track_id])
            kind = (params or {}).get("type")
            base = "2026-08-15" if track_id == 111 else "2026-08-20"
            value = track_id
            body = {"obj": [{"track_domain_id": "release", "data": [
                {"timestp": base, "value": value},
                {"timestp": "2026-09-01" if track_id == 111 else "2026-09-10", "value": value + 10},
            ]}]}
            if kind == "posts":
                body["obj"][0]["track_domain_id"] = None
            return _resp(200, body)
        http.get.side_effect = get
        real = cm.ChartmetricClient("refresh", session=http)
        with patch.object(cm, "get_client", return_value=real):
            for slug, track_id in ((a, 111), (b, 222), (a, 111), (b, 222)):
                client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": f"https://app.chartmetric.com/track/{track_id}"})
                # track linking does not fetch histories; endpoint fetches each independently.
                body = client.get(f"/api/campaign/{slug}/pop-score").get_json()
                assert body["chartmetric_track_id"] == track_id
                assert body["streams"]["start_total"] == track_id + 10
                assert body["streams"]["now"] == track_id + 10
                assert body["streams_history"][0]["total"] == track_id
                assert body["post_events"] == [{"date": "2026-09-02" if track_id == 111 else "2026-09-11", "count": 1}]
                expected_since = date(2026, 8, 11) if track_id == 111 else date(2026, 8, 20)
                assert any(t == track_id and p.get("since") == expected_since.isoformat() for t, p in calls)

    def test_invalid_link_rejected(self, client):
        slug = self._campaign(client)
        res = client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "not a link"})
        assert res.status_code == 400

    def test_empty_link_unlinks(self, client):
        slug = self._campaign(client)
        with patch.object(cm, "get_client", return_value=self._fake()):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "USUM72403305"})
        client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": ""})
        assert client.get(f"/api/campaign/{slug}/pop-score").get_json() == {"linked": False}

    def test_chartmetric_outage_returns_502_with_message(self, client):
        slug = self._campaign(client)
        fake = self._fake()
        with patch.object(cm, "get_client", return_value=fake):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "USUM72403305"})
            fake.track_snapshot.side_effect = cm.ChartmetricError("Chartmetric request failed (500).")
            res = client.get(f"/api/campaign/{slug}/pop-score")
        assert res.status_code == 502
        assert "Chartmetric" in res.get_json()["error"]

    def test_streams_outage_keeps_popularity_response(self, client):
        slug = self._campaign(client)
        fake = self._fake()
        fake.streams_history.side_effect = cm.ChartmetricError("unavailable")
        with patch.object(cm, "get_client", return_value=fake):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "USUM72403305"})
            body = client.get(f"/api/campaign/{slug}/pop-score").get_json()
        assert body["linked"] is True
        assert body["popularity"]["start"] == 82
        assert body["streams"]["start_total"] is None
        assert body["streams"]["end_total"] is None
        assert body["streams"]["gained_campaign"] is None
        assert body["streams"]["baseline_daily"] is None
        assert body["streams_history"] == []
        assert body["streams_error"] == "Streams history is temporarily unavailable."

    def test_empty_or_invalid_chartmetric_series_returns_200_with_null_metrics(self, client):
        slug = self._campaign(client, title="empty history pin")
        fake = self._fake()
        fake.streams_history.return_value = []
        fake.tiktok_posts_history.return_value = []
        with patch.object(cm, "get_client", return_value=fake):
            client.post(f"/api/campaign/{slug}/pop-score/track", json={"link": "USUM72403305"})
            response = client.get(f"/api/campaign/{slug}/pop-score")
        assert response.status_code == 200
        body = response.get_json()
        assert body["streams_history"] == body["ugc_history"] == []
        assert body["streams"]["now"] is None and body["ugc"]["now"] is None

    def test_edit_end_date_set_clear_and_validate(self, client):
        slug = self._campaign(client, start="2026-09-01")
        assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-09-30"}).status_code == 200
        assert client.get(f"/api/campaign/{slug}").get_json()["end_date"] == "2026-09-30"
        assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": ""}).status_code == 200
        for value in ("2026-9-30", "2026-08-31"):
            assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": value}).status_code == 400

    def test_finish_sets_today_once_and_reopen_keeps_the_end_date(self, client):
        slug = self._campaign(client, start="2026-09-01")
        response = client.post(f"/api/campaign/{slug}/edit", json={"completion_status": "completed"})
        assert response.status_code == 200
        assert client.get(f"/api/campaign/{slug}").get_json()["end_date"] == date.today().isoformat()
        client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-09-20"})
        client.post(f"/api/campaign/{slug}/edit", json={"completion_status": "none"})
        assert client.get(f"/api/campaign/{slug}").get_json()["end_date"] == "2026-09-20"

    @pytest.mark.parametrize("legacy_start", ["", "not-a-date", "2026-09-01T00:00:00"])
    def test_finish_with_blank_or_unparseable_legacy_start_succeeds(self, client, legacy_start):
        slug = self._campaign(client)
        from campaign_manager.blueprints import campaigns as campaigns_bp
        legacy = {"title": "Legacy", "name": "Legacy", "start_date": legacy_start, "end_date": ""}
        with patch.object(campaigns_bp._db, "is_active", return_value=True), \
             patch.object(campaigns_bp._db, "get_campaign", return_value=legacy), \
             patch.object(campaigns_bp._db, "save_campaign") as save:
            response = client.post(f"/api/campaign/{slug}/edit", json={"completion_status": "completed"})
        assert response.status_code == 200
        assert save.call_args.args[1]["end_date"] == date.today().isoformat()

    def test_legacy_edit_shape_pins(self, client):
        from campaign_manager.blueprints import campaigns as campaigns_bp
        slug = self._campaign(client, title="Legacy edit test")
        legacy = {"title": "Preserve me", "name": "Preserve me", "start_date": "legacy-time", "end_date": "also-legacy", "additional_sounds": ["keep"]}
        with patch.object(campaigns_bp._db, "is_active", return_value=True), \
             patch.object(campaigns_bp._db, "get_campaign", return_value=legacy), \
             patch.object(campaigns_bp._db, "save_campaign") as save:
            assert client.post(f"/api/campaign/{slug}/edit", json={"budget": 20}).status_code == 200
            saved = save.call_args.args[1]
            assert saved["title"] == "Preserve me" and saved["additional_sounds"] == ["keep"]
            assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": 7}).status_code == 400
            assert client.post(f"/api/campaign/{slug}/edit", json={"start_date": "2026-9-1"}).status_code == 400
            assert client.post(f"/api/campaign/{slug}/edit", json={"start_date": "2026-10-01"}).status_code == 400
            assert client.post(f"/api/campaign/{slug}/edit", json=None).status_code == 200
            assert client.post(f"/api/campaign/{slug}/edit", json=[]).status_code == 200
        saved["additional_sounds"] = ["keep"]
        with patch.object(campaigns_bp._db, "is_active", return_value=True), \
             patch.object(campaigns_bp._db, "get_campaign", return_value=saved), \
             patch.object(campaigns_bp._db, "save_campaign") as save:
            assert client.post(f"/api/campaign/{slug}/edit", json={"additional_sounds": "wrong-shape"}).status_code == 200
            assert save.call_args.args[1]["additional_sounds"] == ["keep"]

    def test_moving_start_past_stored_end_is_rejected(self, client):
        slug = self._campaign(client, title="End boundary pin")
        client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-09-20"})
        response = client.post(f"/api/campaign/{slug}/edit", json={"start_date": "2026-09-21"})
        assert response.status_code == 400

    def test_finish_never_overwrites_existing_end_date(self, client):
        slug = self._campaign(client, start="2026-09-01")
        client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-09-20"})
        client.post(f"/api/campaign/{slug}/edit", json={"completion_status": "completed"})
        assert client.get(f"/api/campaign/{slug}").get_json()["end_date"] == "2026-09-20"

    def test_edit_header_payload_and_bad_start_date_shapes(self, client):
        slug = self._campaign(client)
        from campaign_manager.blueprints import campaigns as campaigns_bp
        legacy = {"title": "Old", "name": "Old", "start_date": "2026-09-01T00:00:00", "end_date": "2026-09-20", "budget": 10}
        with patch.object(campaigns_bp._db, "is_active", return_value=True), \
             patch.object(campaigns_bp._db, "get_campaign", return_value=legacy), \
             patch.object(campaigns_bp._db, "save_campaign"):
            unchanged = client.post(f"/api/campaign/{slug}/edit", json={"title": "Old", "start_date": legacy["start_date"], "end_date": legacy["end_date"], "additional_sounds": []})
            assert unchanged.status_code == 200
        for value in (None, 123):
            response = client.post(f"/api/campaign/{slug}/edit", json={"start_date": value})
            assert response.status_code == 400
        assert client.post(f"/api/campaign/{slug}/edit", json={"start_date": ""}).status_code == 200
        with patch.object(campaigns_bp._db, "is_active", return_value=True), \
             patch.object(campaigns_bp._db, "get_campaign", return_value={"title": "No start", "start_date": "", "end_date": ""}), \
             patch.object(campaigns_bp._db, "save_campaign"):
            missing_start = client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-09-20"})
        assert missing_start.status_code == 400
        assert "start_date" in missing_start.get_json()["error"]
        assert client.post(f"/api/campaign/{slug}/edit", json={"additional_sounds": "not a list"}).status_code == 200

    def test_unknown_campaign_404(self, client):
        assert client.get("/api/campaign/nope/pop-score").status_code == 404
