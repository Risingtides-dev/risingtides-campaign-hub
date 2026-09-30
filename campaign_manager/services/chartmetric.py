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
import unicodedata
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
    def _token(self, deadline=None) -> str:
        if self._access_token and time.time() < self._token_expires_at - TOKEN_REFRESH_MARGIN_S:
            return self._access_token
        timeout = self._request_timeout(deadline)
        res = self._http.post(
            f"{BASE_URL}/token",
            json={"refreshtoken": self._refresh_token},
            timeout=timeout,
        )
        if res.status_code != 200:
            # Avoid logging response bodies from an authentication endpoint.
            log.error("Chartmetric token exchange failed: %s", res.status_code)
            raise ChartmetricError("Chartmetric login failed — the refresh token may be expired.")
        body = res.json()
        self._access_token = body["token"]
        self._token_expires_at = time.time() + float(body.get("expires_in", 3600))
        return self._access_token

    def _throttle(self, deadline=None) -> None:
        wait = MIN_REQUEST_INTERVAL_S - (time.time() - self._last_request_at)
        if wait > 0:
            if deadline is not None and time.monotonic() + wait >= deadline:
                raise TimeoutError("Chartmetric request deadline exceeded")
            time.sleep(wait)
        self._last_request_at = time.time()

    @staticmethod
    def _request_timeout(deadline):
        remaining = REQUEST_TIMEOUT_S if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Chartmetric request deadline exceeded")
        return min(REQUEST_TIMEOUT_S, remaining)

    def _get(self, path: str, params: Optional[dict] = None, deadline=None):
        cache_key = f"{path}?{sorted((params or {}).items())}"
        hit = self._cache.get(cache_key)
        if hit and time.time() - hit[0] < RESPONSE_CACHE_TTL_S:
            return hit[1]

        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("Chartmetric request deadline exceeded")
        acquired = self._lock.acquire() if remaining is None else self._lock.acquire(timeout=remaining)
        if not acquired:
            raise TimeoutError("Chartmetric request deadline exceeded")
        try:
            for attempt in range(2):
                self._throttle(deadline)
                res = self._http.get(
                    f"{BASE_URL}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._token(deadline)}"},
                    timeout=self._request_timeout(deadline),
                )
                if res.status_code == 429 and attempt == 0:
                    if deadline is not None and time.monotonic() + 2.0 + MIN_REQUEST_INTERVAL_S >= deadline:
                        break
                    time.sleep(2.0)
                    continue
                if res.status_code == 401 and attempt == 0:
                    if deadline is not None and time.monotonic() + MIN_REQUEST_INTERVAL_S >= deadline:
                        break
                    self._access_token = ""  # force re-auth once
                    continue
                break
        finally:
            self._lock.release()

        if res.status_code == 404:
            raise ChartmetricError("Chartmetric couldn't find that track.")
        if res.status_code != 200:
            # Response bodies can contain credentials returned by misconfigured proxies.
            log.error("Chartmetric GET %s failed: %s", path, res.status_code)
            raise ChartmetricError(f"Chartmetric request failed ({res.status_code}).")
        obj = res.json().get("obj")
        self._cache[cache_key] = (time.time(), obj)
        return obj

    # ── public API ──────────────────────────────────────────────────
    def search_track(self, song: str, artist: str, deadline=None) -> Optional[int]:
        """Resolve an exact title through exact-name artist profiles and their tracks."""
        from campaign_manager.services.matching import _is_generic_song_title

        if not song or not song.strip() or not artist or not artist.strip() or _is_generic_song_title(song):
            return None

        def norm(value):
            value = unicodedata.normalize("NFKD", value or "").casefold()
            return " ".join("".join(ch if ch.isalnum() else " " for ch in value).split())

        target_song, target_artist = norm(song), norm(artist)
        obj = self._get("/search", {"q": artist, "type": "artists", "limit": 10}, deadline=deadline) or {}
        rows = obj.get("artists", []) if isinstance(obj, dict) else []
        artist_ids = []
        for row in rows:
            if isinstance(row, dict) and norm(row.get("name")) == target_artist:
                try:
                    artist_ids.append(int(row["id"]))
                except (KeyError, TypeError, ValueError):
                    continue
        candidates = {}
        for artist_id in artist_ids:
            for page in range(15):
                tracks = self._get(f"/artist/{artist_id}/tracks", {"limit": 100, "offset": page * 100}, deadline=deadline)
                tracks = tracks if isinstance(tracks, list) else []
                for row in tracks:
                    if not isinstance(row, dict) or norm(row.get("name")) != target_song:
                        continue
                    names = row.get("artist_names") or []
                    if target_artist not in {norm(name) for name in names}:
                        continue
                    try:
                        track_id = int(row["id"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    stats = row.get("cm_statistics") or {}
                    streams = stats.get("sp_streams")
                    popularity = stats.get("sp_popularity")
                    candidates[track_id] = (
                        int(streams) if streams is not None else None,
                        float(popularity) if popularity is not None else None,
                    )
                if len(tracks) < 100:
                    break
        if not candidates:
            return None
        # Missing metrics rank below known metrics; id is the deterministic tie-break.
        return min(candidates, key=lambda track_id: (
            -(candidates[track_id][0] if candidates[track_id][0] is not None else -1),
            -(candidates[track_id][1] if candidates[track_id][1] is not None else -1),
            track_id,
        ))

    def resolve_track_id(self, ref: TrackRef, deadline=None) -> int:
        if ref.kind == "chartmetric":
            return int(ref.value)
        rows = self._get(f"/track/{ref.kind}/{ref.value}/get-ids", deadline=deadline) or []
        for row in rows:
            ids = row.get("chartmetric_ids") or []
            if ids:
                return int(ids[0])
        raise ChartmetricError("Chartmetric doesn't have that track yet.")

    def track_snapshot(self, chartmetric_id: int, deadline=None) -> TrackSnapshot:
        obj = self._get(f"/track/{int(chartmetric_id)}", deadline=deadline) or {}
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

    def popularity_history(self, chartmetric_id: int, since: Optional[date] = None, deadline=None) -> List[dict]:
        """Daily Spotify popularity as [{"date": "YYYY-MM-DD", "value": int}].

        A song often has several Spotify IDs (single, album, deluxe); the
        series with the most recent, highest reading is the one people see.
        """
        series_list = self._get(
            f"/track/{int(chartmetric_id)}/spotify/stats/most-history",
            {"type": "popularity", **({"since": since.isoformat()} if since else {})}, deadline=deadline,
        ) or []
        best = _pick_primary_series(series_list)
        points = _clean_points(best)
        if since is not None:
            cutoff = since.isoformat()
            points = [p for p in points if p["date"] >= cutoff]
        return sorted(points, key=lambda p: p["date"])

    def popularity_track_domain_id(self, chartmetric_id: int, since: Optional[date] = None, deadline=None):
        series_list = self._get(
            f"/track/{int(chartmetric_id)}/spotify/stats/most-history",
            {"type": "popularity", **({"since": since.isoformat()} if since else {})}, deadline=deadline,
        ) or []
        return _pick_primary_object(series_list).get("track_domain_id")

    def streams_history(self, chartmetric_id: int, since: Optional[date] = None, track_domain_id=None, deadline=None) -> List[dict]:
        """Cumulative Spotify streams as sorted date/value readings."""
        series_list = self._get(
            f"/track/{int(chartmetric_id)}/spotify/stats/most-history",
            {"type": "streams", **({"since": since.isoformat()} if since else {})}, deadline=deadline,
        ) or []
        preferred = [s for s in series_list if isinstance(s, dict) and s.get("track_domain_id") == track_domain_id] if track_domain_id is not None else []
        best = (max(preferred, key=lambda s: _latest(s)[1]) if preferred else _pick_primary_object(series_list))
        points = _clean_points(best.get("data") or [])
        points.sort(key=lambda p: p["date"])
        if since is not None:
            cutoff = since.isoformat()
            points = [p for p in points if p["date"] >= cutoff]
        return sorted(points, key=lambda p: p["date"])

    def tiktok_posts_history(self, chartmetric_id: int, since: Optional[date] = None, deadline=None) -> List[dict]:
        """Cumulative TikTok videos using a track, as sorted readings."""
        rows = self._get(f"/track/{int(chartmetric_id)}/tiktok/stats/most-history",
                         {"type": "posts", **({"since": since.isoformat()} if since else {})}, deadline=deadline) or []
        best = _pick_primary_object(rows)
        points = _clean_points(best.get("data") or [])
        if since is not None:
            points = [p for p in points if p["date"] >= since.isoformat()]
        return sorted(points, key=lambda p: p["date"])


def _pick_primary_series(series_list: List[dict]) -> List[dict]:
    return _pick_primary_object(series_list).get("data", [])


def _latest(series):
    data = _clean_points(series.get("data") or [])
    last = max(data, key=lambda p: p["date"]) if data else {}
    return (last.get("date", ""), last.get("value") or 0)


def _pick_primary_object(series_list):
    candidates = [s for s in series_list if isinstance(s, dict) and s.get("data")]
    if not candidates:
        return {}
    newest = max(_latest(s)[0] for s in candidates)
    recent = [s for s in candidates if _latest(s)[0] and _date_gap(newest, _latest(s)[0]) <= 3]
    if not recent:
        recent = candidates
    return max(recent, key=lambda s: _latest(s)[1])


def _date_gap(a, b):
    try:
        return (date.fromisoformat(a) - date.fromisoformat(b)).days
    except ValueError:
        return 99999


def _clean_points(data):
    points = []
    for p in data:
        if not isinstance(p, dict):
            continue
        stamp = p.get("timestp")
        try:
            day = stamp[:10]
            if date.fromisoformat(day).isoformat() != day:
                continue
            value = int(float(p.get("value")))
        except Exception:
            continue
        points.append({"date": day, "value": value})
    return points


_client: Optional[ChartmetricClient] = None
_client_lock = threading.Lock()


def get_client() -> ChartmetricClient:
    """Process-wide client so the access token and throttle are shared."""
    global _client
    with _client_lock:
        if _client is None:
            _client = ChartmetricClient(os.environ.get("CHARTMETRIC_REFRESH_TOKEN", ""))
        return _client
