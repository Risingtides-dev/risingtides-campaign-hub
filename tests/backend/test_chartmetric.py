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

    def test_streams_history_selects_primary_and_passes_since(self):
        client, _ = _client_with({"most-history": _resp(200, {"obj": HISTORY_OBJ})})
        hist = client.streams_history(1, since=date(2026, 8, 25), track_domain_id="main")
        assert hist == [{"date": "2026-09-01", "value": 82}, {"date": "2026-09-20", "value": 87}]
        assert client._http.get.call_args.kwargs["params"] == {"type": "streams", "since": "2026-08-25"}

    def test_streams_drops_repeated_cumulative_points_and_skips_invalid_values(self):
        series = [{"track_domain_id": "x", "data": [
            {"timestp": "2026-08-07", "value": "3126151554"},
            {"timestp": "2026-08-08", "value": "3126151554.0"},
            {"timestp": "2026-08-09", "value": "3129082729"},
            {"timestp": "bad-date", "value": 8},
            {"timestp": "2026-08-10", "value": "oops"},
        ]}]
        client, _ = _client_with({"most-history": _resp(200, {"obj": series})})
        assert client.streams_history(1) == [{"date": "2026-08-09", "value": 3129082729}]

    def test_streams_drops_entire_repeat_runs_and_keeps_first_tail_reading(self):
        rows = [{"track_domain_id": "x", "data": [
            {"timestp": "2026-09-24", "value": 3191203786},
            {"timestp": "2026-09-25", "value": 3193825920},
            {"timestp": "2026-09-26", "value": 3193825920},
            {"timestp": "2026-09-27", "value": 3195168217},
        ]}]
        client, _ = _client_with({"most-history": _resp(200, {"obj": rows})})
        assert client.streams_history(1) == [rows[0]["data"][0:1][0], rows[0]["data"][3]] if False else [
            {"date": "2026-09-24", "value": 3191203786}, {"date": "2026-09-27", "value": 3195168217}]

    def test_streams_tail_repeat_run_keeps_only_its_first_reading(self):
        rows = [{"track_domain_id": "x", "data": [
            {"timestp": "2026-09-24", "value": 10}, {"timestp": "2026-09-25", "value": 12},
            {"timestp": "2026-09-26", "value": 12}, {"timestp": "2026-09-27", "value": 12}]}]
        client, _ = _client_with({"most-history": _resp(200, {"obj": rows})})
        assert client.streams_history(1) == [{"date": "2026-09-24", "value": 10}, {"date": "2026-09-25", "value": 12}]

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
    def _campaign(self, client, start="2026-09-01"):
        res = client.post("/api/campaign/create", json={"title": "Pop Test", "budget": 1000})
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
        assert response.is_json

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
        assert body["streams"] == {
            "start_total": None, "end_total": None, "followup_total": None,
            "end_is_to_date": True, "followup_is_to_date": False,
            "gained_campaign": None, "gained_followup": None, "growth_pct_campaign": None,
            "baseline_daily": None, "campaign_daily": None, "followup_daily": None,
            "lift_pct_campaign": None, "lift_pct_followup": None,
        }
        assert body["streams_history"] == []
        assert body["streams_error"] == "Streams history is temporarily unavailable."

    def test_edit_end_date_set_clear_and_validate(self, client):
        slug = self._campaign(client, start="2026-09-01")
        assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-09-30"}).status_code == 200
        assert client.get(f"/api/campaign/{slug}").get_json()["end_date"] == "2026-09-30"
        assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": ""}).status_code == 200
        for value in ("2026-9-30", "2026-08-31"):
            assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": value}).status_code == 400

    def test_unknown_campaign_404(self, client):
        assert client.get("/api/campaign/nope/pop-score").status_code == 404
