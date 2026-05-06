"""TidesTracker API client.

Talks to the TidesTracker service via its `/api/campaigns` endpoint.
TidesTracker is the source of truth for tracker data; Campaign Hub only
maintains a local "folder" overlay (groups + assignments).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import requests as _requests
from flask import current_app


class TidesTrackerError(Exception):
    """Raised when the TidesTracker API call fails or is unconfigured."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


# Pinned to the canonical TidesTracker domain so the integration can't
# silently break when a Vercel subdomain alias drifts to an old build.
# Env var overrides only for dev/staging.
TIDESTRACKER_PUBLIC_URL = "https://risingtides-tracker.com/"
TIDESTRACKER_DEFAULT_API = "https://risingtides-tracker.com/api"


def _config() -> Tuple[str, str, str]:
    api = current_app.config.get("TIDESTRACKER_API_URL", "") or TIDESTRACKER_DEFAULT_API
    key = current_app.config.get("TIDESTRACKER_SERVICE_KEY", "")
    base = current_app.config.get("TIDESTRACKER_BASE_URL", "") or TIDESTRACKER_PUBLIC_URL
    if not key:
        raise TidesTrackerError(
            "TidesTracker not configured. Set TIDESTRACKER_SERVICE_KEY.",
            status_code=500,
        )
    # Force the canonical domain even if a stale env var still points at the
    # raw Vercel subdomain — that subdomain has historically pinned to old
    # deployments and missed feature deploys.
    if "frontend-tidestracker.vercel.app" in api:
        api = TIDESTRACKER_DEFAULT_API
    return api, key, base


def tracker_url_for(tracker_id: str) -> str:
    """Public deep link to a specific tracker.

    TidesTracker exposes auth-free public dashboards at /<uuid>
    (see api/public/[campaignId].ts on the TidesTracker side), so the
    UUID itself is the access token.
    """
    if not tracker_id:
        return ""
    return f"{TIDESTRACKER_PUBLIC_URL.rstrip('/')}/{tracker_id}"


def create_tracker_campaign(
    name: str,
    slug: str,
    cobrand_share_url: str,
    client_id: Optional[str] = None,
) -> Tuple[str, str]:
    """Call the TidesTracker API to create a campaign.

    Returns (tracker_campaign_id, tracker_url).
    Raises TidesTrackerError on configuration issues or HTTP failure.
    """
    api, key, base = _config()

    if not cobrand_share_url:
        raise TidesTrackerError("cobrand_share_url is required", status_code=400)

    try:
        resp = _requests.post(
            f"{api}/campaigns",
            json={
                "name": name,
                "slug": slug,
                "cobrand_share_link": cobrand_share_url,
                "client_id": client_id,
            },
            headers={
                "Content-Type": "application/json",
                "x-service-key": key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
    except _requests.RequestException as e:
        raise TidesTrackerError(f"Failed to create tracker: {e}", status_code=502)

    tracker_campaign_id = (result.get("campaign") or {}).get("id", "") or ""
    tracker_url = f"{base}/{tracker_campaign_id}" if base and tracker_campaign_id else ""
    return tracker_campaign_id, tracker_url


def normalize_video_url(url: str) -> str:
    """Normalize a TikTok/IG URL for cross-system comparison.

    Scraper stores URLs as `https://www.tiktok.com/@user/video/<id>`.
    TidesTracker public API returns `https://tiktok.com/@user/video/<id>` (no www).
    Lowercase, strip www, strip trailing slash. The video ID at the end is
    the real join key — everything before it is normalized.
    """
    if not url:
        return ""
    u = url.strip().lower()
    if u.startswith("https://www."):
        u = "https://" + u[len("https://www."):]
    elif u.startswith("http://www."):
        u = "http://" + u[len("http://www."):]
    if u.endswith("/"):
        u = u[:-1]
    # Drop query strings — they don't change which video this is
    if "?" in u:
        u = u.split("?", 1)[0]
    return u


def extract_video_id(url: str) -> str:
    """Pull the trailing numeric video ID out of a TikTok URL.

    Used as a backup join key in case URL normalization differs in
    unexpected ways (mobile vs web URLs, redirects, etc.).
    """
    if not url:
        return ""
    import re
    m = re.search(r"/video/(\d+)", url)
    return m.group(1) if m else ""


# Per-tracker cache for the public submissions list.
# In-process, 5-minute TTL — saves hammering risingtides-tracker.com on
# every cron run. Cron runs once daily so we mostly miss the cache, but
# the manual refresh button + Scrape Tasks queue may hit the same tracker
# multiple times in a session.
import time as _time
_tracker_videos_cache: Dict[str, Tuple[float, Dict]] = {}
_TRACKER_CACHE_TTL = 300  # seconds


def get_tracked_videos(tracker_id: str, force: bool = False) -> Dict:
    """Fetch the list of videos already submitted to Cobrand for this tracker.

    Returns a dict:
        {
            "ok": bool,
            "tracker_id": str,
            "fetched_at": iso str,
            "count": int,
            "urls": Set[str]      # normalized URLs
            "video_ids": Set[str] # numeric video IDs (backup join key)
            "raw_videos": List[Dict]  # full payload from TidesTracker
        }

    Hits the auth-free TidesTracker public endpoint:
        GET https://risingtides-tracker.com/api/public/<tracker_id>

    Returns ok=False if tracker_id is missing, the request fails, or the
    payload doesn't contain a videos array. Callers should treat that as
    "we don't know what's in Cobrand for this campaign — show all matches
    in the queue conservatively."
    """
    if not tracker_id:
        return {
            "ok": False, "tracker_id": "", "count": 0,
            "urls": set(), "video_ids": set(), "raw_videos": [],
            "error": "no tracker_id",
        }

    now = _time.time()
    if not force:
        cached = _tracker_videos_cache.get(tracker_id)
        if cached and (now - cached[0]) < _TRACKER_CACHE_TTL:
            return cached[1]

    url = f"{TIDESTRACKER_PUBLIC_URL.rstrip('/')}/api/public/{tracker_id}"
    try:
        resp = _requests.get(url, timeout=15, headers={"Accept": "application/json"})
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        result = {
            "ok": False, "tracker_id": tracker_id, "count": 0,
            "urls": set(), "video_ids": set(), "raw_videos": [],
            "error": str(e),
        }
        # Don't cache failures — retry next call
        return result

    videos = payload.get("videos") or []
    urls: set = set()
    vids: set = set()
    for v in videos:
        u = v.get("video_url") or ""
        if u:
            urls.add(normalize_video_url(u))
            vid = extract_video_id(u)
            if vid:
                vids.add(vid)

    result = {
        "ok": True,
        "tracker_id": tracker_id,
        "fetched_at": payload.get("fetched_at") or "",
        "count": len(videos),
        "urls": urls,
        "video_ids": vids,
        "raw_videos": videos,
    }
    _tracker_videos_cache[tracker_id] = (now, result)
    return result


def is_video_tracked(tracker_id: str, video_url: str) -> bool:
    """Return True if this video URL is already submitted to Cobrand for
    the given tracker. Uses normalized URL match first, video-ID match as
    a fallback for edge cases (mobile URLs, etc.).

    If tracker_id is missing or the public fetch fails, returns False —
    we conservatively let the link show up in the queue rather than hide it.
    """
    if not tracker_id or not video_url:
        return False
    cache = get_tracked_videos(tracker_id)
    if not cache["ok"]:
        return False
    norm = normalize_video_url(video_url)
    if norm in cache["urls"]:
        return True
    vid = extract_video_id(video_url)
    if vid and vid in cache["video_ids"]:
        return True
    return False


def list_tracker_campaigns(client_id: Optional[str] = None) -> List[Dict]:
    """Fetch all active campaigns from TidesTracker via the service-key API.

    Returns the raw list of campaign dicts as returned by the API:
        [{ id, client_id, name, slug, cobrand_share_link, is_active,
           created_at, client: { id, name, slug } | None }, ...]
    """
    api, key, _base = _config()

    params = {}
    if client_id:
        params["client_id"] = client_id

    try:
        resp = _requests.get(
            f"{api}/campaigns",
            headers={"x-service-key": key},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
    except _requests.RequestException as e:
        raise TidesTrackerError(f"Failed to list trackers: {e}", status_code=502)

    return result.get("campaigns") or []
