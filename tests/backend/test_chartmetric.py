"""Chartmetric pop-score client + campaign endpoints (HTTP fully faked)."""
from __future__ import annotations

from datetime import date
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
        hist = client.streams_history(1, since=date(2026, 8, 25))
        assert hist == [{"date": "2026-09-01", "value": 82}, {"date": "2026-09-20", "value": 87}]
        assert client._http.get.call_args.kwargs["params"] == {"type": "streams", "since": "2026-08-25"}

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

    def test_edit_end_date_set_clear_and_validate(self, client):
        slug = self._campaign(client, start="2026-09-01")
        assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": "2026-09-30"}).status_code == 200
        assert client.get(f"/api/campaign/{slug}").get_json()["end_date"] == "2026-09-30"
        assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": ""}).status_code == 200
        for value in ("2026-9-30", "2026-08-31"):
            assert client.post(f"/api/campaign/{slug}/edit", json={"end_date": value}).status_code == 400

    def test_unknown_campaign_404(self, client):
        assert client.get("/api/campaign/nope/pop-score").status_code == 404
