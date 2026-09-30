"""Chartmetric API client — Spotify popularity ("pop score") per campaign song.

Auth: a long-lived refresh token (CHARTMETRIC_REFRESH_TOKEN env var) is
exchanged for a 1-hour access token, cached in-process and renewed early.
Chartmetric rate-limits to roughly 1 request/second, so every call goes
through a shared throttle and 429s are retried once after a pause.

Chartmetric's search ranks poorly (a query for "Espresso" doesn't return the
Sabrina Carpenter track), so tracks are resolved from an exact identifier the
user pastes: a Spotify track link/URI, a Chartmetric track link, or an ISRC.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://api.chartmetric.com/api"
TOKEN_REFRESH_MARGIN_S = 300
MIN_REQUEST_INTERVAL_S = 1.1
REQUEST_TIMEOUT_S = 20
RESPONSE_CACHE_TTL_S = 60 * 60  # popularity updates daily; hourly is plenty

_SPOTIFY_TRACK_RE = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z]+/)?track/|spotify:track:)([A-Za-z0-9]{22})")
_CHARTMETRIC_TRACK_RE = re.compile(r"chartmetric\.com/track(?:/|\?id=)(\d+)")
_ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")


class ChartmetricError(Exception):
    """User-presentable Chartmetric failure."""


@dataclass(frozen=True)
class TrackRef:
    kind: str  # "spotify" | "chartmetric" | "isrc"
    value: str


@dataclass(frozen=True)
class TrackSnapshot:
    chartmetric_id: int
    name: str
    artists: Tuple[str, ...]
    spotify_popularity: Optional[int]
    chartmetric_score: Optional[float]
    spotify_streams: Optional[int]
    image_url: str


def parse_track_link(raw: str) -> TrackRef:
    """Identify a track from a Spotify link/URI, Chartmetric link, or ISRC."""
    text = (raw or "").strip()
    if not text:
        raise ChartmetricError("Paste a Spotify track link, Chartmetric track link, or ISRC.")
    m = _SPOTIFY_TRACK_RE.search(text)
    if m:
        return TrackRef("spotify", m.group(1))
    m = _CHARTMETRIC_TRACK_RE.search(text)
    if m:
        return TrackRef("chartmetric", m.group(1))
    compact = text.replace("-", "").upper()
    if _ISRC_RE.match(compact):
        return TrackRef("isrc", compact)
    raise ChartmetricError(
        "That doesn't look like a Spotify track link, Chartmetric track link, or ISRC."
    )


class ChartmetricClient:
    def __init__(self, refresh_token: str, session: Optional[requests.Session] = None):
        if not refresh_token:
            raise ChartmetricError("CHARTMETRIC_REFRESH_TOKEN is not set.")
        self._refresh_token = refresh_token
        self._http = session or requests.Session()
        self._lock = threading.Lock()
        self._access_token = ""
        self._token_expires_at = 0.0
        self._last_request_at = 0.0
        self._cache: Dict[str, Tuple[float, object]] = {}

    # ── plumbing ────────────────────────────────────────────────────
    def _token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - TOKEN_REFRESH_MARGIN_S:
            return self._access_token
        res = self._http.post(
            f"{BASE_URL}/token",
            json={"refreshtoken": self._refresh_token},
            timeout=REQUEST_TIMEOUT_S,
        )
        if res.status_code != 200:
            log.error("Chartmetric token exchange failed: %s %s", res.status_code, res.text[:200])
            raise ChartmetricError("Chartmetric login failed — the refresh token may be expired.")
        body = res.json()
        self._access_token = body["token"]
        self._token_expires_at = time.time() + float(body.get("expires_in", 3600))
        return self._access_token

    def _throttle(self) -> None:
        wait = MIN_REQUEST_INTERVAL_S - (time.time() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    def _get(self, path: str, params: Optional[dict] = None):
        cache_key = f"{path}?{sorted((params or {}).items())}"
        hit = self._cache.get(cache_key)
        if hit and time.time() - hit[0] < RESPONSE_CACHE_TTL_S:
            return hit[1]

        with self._lock:
            for attempt in range(2):
                self._throttle()
                res = self._http.get(
                    f"{BASE_URL}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._token()}"},
                    timeout=REQUEST_TIMEOUT_S,
                )
                if res.status_code == 429 and attempt == 0:
                    time.sleep(2.0)
                    continue
                if res.status_code == 401 and attempt == 0:
                    self._access_token = ""  # force re-auth once
                    continue
                break

        if res.status_code == 404:
            raise ChartmetricError("Chartmetric couldn't find that track.")
        if res.status_code != 200:
            log.error("Chartmetric GET %s failed: %s %s", path, res.status_code, res.text[:200])
            raise ChartmetricError(f"Chartmetric request failed ({res.status_code}).")
        obj = res.json().get("obj")
        self._cache[cache_key] = (time.time(), obj)
        return obj

    # ── public API ──────────────────────────────────────────────────
    def resolve_track_id(self, ref: TrackRef) -> int:
        if ref.kind == "chartmetric":
            return int(ref.value)
        rows = self._get(f"/track/{ref.kind}/{ref.value}/get-ids") or []
        for row in rows:
            ids = row.get("chartmetric_ids") or []
            if ids:
                return int(ids[0])
        raise ChartmetricError("Chartmetric doesn't have that track yet.")

    def track_snapshot(self, chartmetric_id: int) -> TrackSnapshot:
        obj = self._get(f"/track/{int(chartmetric_id)}") or {}
        stats = obj.get("cm_statistics") or {}
        pop = stats.get("sp_popularity")
        return TrackSnapshot(
            chartmetric_id=int(chartmetric_id),
            name=obj.get("name") or "",
            artists=tuple(a.get("name", "") for a in obj.get("artists") or []),
            spotify_popularity=int(pop) if pop is not None else None,
            chartmetric_score=stats.get("score"),
            spotify_streams=stats.get("sp_streams"),
            image_url=obj.get("image_url") or "",
        )

    def popularity_history(self, chartmetric_id: int, since: Optional[date] = None) -> List[dict]:
        """Daily Spotify popularity as [{"date": "YYYY-MM-DD", "value": int}].

        A song often has several Spotify IDs (single, album, deluxe); the
        series with the most recent, highest reading is the one people see.
        """
        series_list = self._get(
            f"/track/{int(chartmetric_id)}/spotify/stats/most-history",
            {"type": "popularity", **({"since": since.isoformat()} if since else {})},
        ) or []
        best = _pick_primary_series(series_list)
        points = [
            {"date": p["timestp"][:10], "value": int(p["value"])}
            for p in best
            if p.get("timestp") and p.get("value") is not None
        ]
        if since is not None:
            cutoff = since.isoformat()
            points = [p for p in points if p["date"] >= cutoff]
        return sorted(points, key=lambda p: p["date"])

    def streams_history(self, chartmetric_id: int, since: Optional[date] = None) -> List[dict]:
        """Cumulative Spotify streams as sorted date/value readings."""
        series_list = self._get(
            f"/track/{int(chartmetric_id)}/spotify/stats/most-history",
            {"type": "streams", **({"since": since.isoformat()} if since else {})},
        ) or []
        best = _pick_primary_series(series_list)
        points = [
            {"date": p["timestp"][:10], "value": int(p["value"])}
            for p in best if p.get("timestp") and p.get("value") is not None
        ]
        if since is not None:
            cutoff = since.isoformat()
            points = [p for p in points if p["date"] >= cutoff]
        return sorted(points, key=lambda p: p["date"])


def _pick_primary_series(series_list: List[dict]) -> List[dict]:
    def rank(series: dict):
        data = series.get("data") or []
        if not data:
            return ("", -1)
        last = max(data, key=lambda p: p.get("timestp") or "")
        return (last.get("timestp") or "", last.get("value") or 0)

    candidates = [s for s in series_list if s.get("data")]
    return max(candidates, key=rank)["data"] if candidates else []


_client: Optional[ChartmetricClient] = None
_client_lock = threading.Lock()


def get_client() -> ChartmetricClient:
    """Process-wide client so the access token and throttle are shared."""
    global _client
    with _client_lock:
        if _client is None:
            _client = ChartmetricClient(os.environ.get("CHARTMETRIC_REFRESH_TOKEN", ""))
        return _client
