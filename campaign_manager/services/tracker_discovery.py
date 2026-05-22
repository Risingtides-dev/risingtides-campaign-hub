"""Auto-discover the campaign↔tracker relationship via shared sound IDs.

A campaign and a TidesTracker are "the same thing" if their sound IDs
overlap. This is a real semantic relationship — at the Cobrand level,
they're tracking submissions to specific TikTok sounds, and a campaign
in Campaign Hub is identified by its `sound_id` + `additional_sounds`.

This module replaces the manual `tracker_campaign_links` overlay table
as the primary source of truth. The table can stay as a manual override
for edge cases where sound IDs don't match (e.g., a new "original sound"
re-upload).

Discovery process:
    1. Fetch all trackers from TidesTracker API
    2. For each tracker, fetch its Cobrand share page (parses __NEXT_DATA__)
    3. Extract the activation's `social_sounds[].id_platform` — these are
       TikTok sound IDs the tracker covers
    4. Build sound_id -> [tracker_id, ...] map
    5. For each campaign, look up its sound IDs in the map → set of trackers

Cached for the duration of a process / cron run, refresh once per call.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Set, Tuple

import requests as _requests

from campaign_manager.services.tidestracker import (
    list_tracker_campaigns,
    TIDESTRACKER_PUBLIC_URL,
)

logger = logging.getLogger(__name__)


# Cache: in-process, module-level. Cleared on process restart.
_sound_to_trackers_cache: Optional[Dict[str, List[Dict]]] = None
_cache_timestamp: float = 0.0
_CACHE_TTL = 600  # 10 minutes — cron runs daily but ad-hoc refreshes need fresh-ish data


# ── Sound-ID fetch: prefer Tides Tracker public API, fall back to scrape ──
#
# Up to 2026-05-22 every gunicorn worker scraped 89 Cobrand share pages
# to build the sound map — ~8s on a cold worker, repeated on each
# 10-minute cache expiry. The tidestracker repo now exposes the same
# sound IDs at `/api/public/<id>?type=sounds` (served through Vercel's
# edge cache), so we call that instead.
#
# The fallback path stays so this PR is safe to merge before the
# tidestracker endpoint deploys — and so a tidestracker outage doesn't
# black-hole the Campaign Hub. After ~one week of clean API traffic we
# can drop `_extract_promo_data` and its fallback wiring.
TIDES_PUBLIC_BASE = os.environ.get(
    "TIDES_TRACKER_PUBLIC_BASE_URL",
    "https://risingtides-tracker.com",
).rstrip("/")
TIDES_SOUNDS_API_TIMEOUT = float(os.environ.get("TIDES_SOUNDS_API_TIMEOUT", "8"))

# When True (default), try the tidestracker API; on any failure for a
# given tracker, fall back to scraping its Cobrand share page directly.
# Flip to "false" to force the legacy scrape — useful if the API is
# returning bad data and we need to roll back without redeploying.
USE_TIDES_SOUNDS_API = os.environ.get(
    "USE_TIDES_SOUNDS_API", "true"
).lower() in ("1", "true", "yes")

# Module-level flag flipped by the first 404 we see. Without this we'd
# pay one wasted HTTP request per tracker per cache rebuild during the
# window between merging this code and deploying the tidestracker
# endpoint. Process-local — a fresh worker re-probes once.
_tides_sounds_api_available: Optional[bool] = None
_tides_sounds_api_lock = threading.Lock()


def _fetch_sounds_via_tides_api(tracker_id: str) -> Optional[List[Dict]]:
    """Fetch the configured sound IDs for a tracker via tidestracker public API.

    Returns:
        - list of {sound_id, sound_title, platform, activation_name} on success
        - None on any failure (timeout, non-200, bad JSON, missing 'sounds').
          Caller falls back to the Cobrand share-page scrape.

    Side effect: on the first 404 we see, sets the module-level
    `_tides_sounds_api_available=False` so subsequent calls in this
    worker skip the network round-trip and go straight to fallback.
    Cleared on process restart.
    """
    global _tides_sounds_api_available
    if not tracker_id:
        return None
    if _tides_sounds_api_available is False:
        return None
    url = f"{TIDES_PUBLIC_BASE}/api/public/{tracker_id}?type=sounds"
    try:
        resp = _requests.get(
            url,
            timeout=TIDES_SOUNDS_API_TIMEOUT,
            headers={"Accept": "application/json"},
        )
    except _requests.RequestException as e:
        logger.debug("tides sounds API request failed for %s: %s", tracker_id, e)
        return None
    if resp.status_code == 404:
        # 404 here means the endpoint itself isn't deployed yet (route
        # missing). 4xx on a known route would still 200 with success:false.
        # Latch off and stop probing until process restart.
        with _tides_sounds_api_lock:
            if _tides_sounds_api_available is None:
                logger.info(
                    "tides sounds API returned 404 — endpoint not deployed yet, "
                    "falling back to Cobrand share-page scrape until process restart"
                )
                _tides_sounds_api_available = False
        return None
    if resp.status_code != 200:
        logger.debug(
            "tides sounds API returned %s for %s", resp.status_code, tracker_id
        )
        return None
    try:
        payload = resp.json()
    except ValueError:
        return None
    if not isinstance(payload, dict) or not payload.get("success"):
        return None
    sounds = payload.get("sounds")
    if not isinstance(sounds, list):
        return None
    # First success after a None probe flips us to True so future calls
    # skip the latch check at the top.
    if _tides_sounds_api_available is None:
        with _tides_sounds_api_lock:
            if _tides_sounds_api_available is None:
                _tides_sounds_api_available = True
    return sounds


def _extract_promo_data(share_url: str) -> Optional[dict]:
    """Fallback: fetch a Cobrand share page and pull the embedded promotion JSON.

    Kept as a safety net behind `_fetch_sounds_via_tides_api()`. See
    the module-level comment above the import block for the migration plan.
    """
    if not share_url or "music.cobrand.com" not in share_url:
        return None
    try:
        resp = _requests.get(
            share_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        m = re.findall(
            r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
            resp.text,
            re.DOTALL,
        )
        if not m:
            return None
        d = json.loads(m[0])
        return d.get("props", {}).get("pageProps", {}).get("promotion") or None
    except Exception:
        return None


def _sounds_for_tracker(t: Dict) -> Tuple[str, List[Dict], Optional[dict]]:
    """Resolve the sound IDs for one tracker.

    Returns (tracker_id, sounds_list, promo_or_none) where:
      - `sounds_list` is the normalised list of {sound_id, sound_title,
        platform, activation_name} either from the tidestracker API or
        synthesised from the scraped promo JSON
      - `promo_or_none` is the raw promo dict if we fell back to
        scraping (only used to preserve `promo_name` in the legacy
        path); always None when the API call succeeded

    Pulling this out of the loop body keeps `build_sound_to_trackers_map`
    readable and lets the ThreadPoolExecutor fan-out work either path
    identically.
    """
    tid = t.get("id") or ""
    if not tid:
        return ("", [], None)

    if USE_TIDES_SOUNDS_API:
        sounds = _fetch_sounds_via_tides_api(tid)
        if sounds is not None:
            # Empty list is a valid answer — a tracker can have no
            # sounds attached yet. We still return success so the
            # fallback scrape doesn't fire.
            return (tid, sounds, None)

    # Fallback to share-page scrape. Normalise to the same shape the
    # API returns so the caller doesn't branch on source.
    share = t.get("cobrand_share_link") or ""
    promo = _extract_promo_data(share)
    if not promo:
        return (tid, [], None)
    synthesised: List[Dict] = []
    for activation in promo.get("activations") or []:
        seg = activation.get("segment") or {}
        for sound in seg.get("social_sounds") or []:
            sid = str(sound.get("id_platform") or "")
            if not sid:
                continue
            synthesised.append({
                "sound_id": sid,
                "sound_title": sound.get("title") or "",
                "platform": (sound.get("platform") or "tiktok").lower(),
                "activation_name": activation.get("name") or "",
            })
    return (tid, synthesised, promo)


def build_sound_to_trackers_map(force_refresh: bool = False) -> Dict[str, List[Dict]]:
    """Build the map: sound_id -> list of trackers that cover it.

    Each tracker entry includes id, name, promo_name, activation_name,
    sound_title, and the cobrand_share_link, so callers can resolve
    "given this sound ID, who tracks it and where do I look?"

    Returns the cached map unless force_refresh=True or TTL expired.
    """
    global _sound_to_trackers_cache, _cache_timestamp
    now = time.time()
    if (
        not force_refresh
        and _sound_to_trackers_cache is not None
        and (now - _cache_timestamp) < _CACHE_TTL
    ):
        return _sound_to_trackers_cache

    sound_map: Dict[str, List[Dict]] = {}

    try:
        trackers = list_tracker_campaigns()
    except Exception:
        trackers = []

    # Exclude soft-deleted (archived) trackers so they don't show up as
    # auto-suggestions on campaigns or as manual-link candidates anywhere.
    try:
        from campaign_manager import db as _db
        archived_ids = set(_db.get_tracker_archives().keys()) if _db.is_active() else set()
    except Exception:
        archived_ids = set()

    # Fan out the per-tracker sound-ID lookups in parallel. Each one
    # tries the tidestracker public API first (sub-second when warm at
    # Vercel's edge; ~1s cold) and only falls back to scraping the
    # Cobrand share page (~1-2s/each) if the API returns nothing.
    #
    # History: pre-API, every tracker scraped a Cobrand share page
    # with a 15s timeout — sequential was ~25s wall time (CAMP-50), and
    # even after parallelising to 20 workers it was ~8s cold on every
    # gunicorn worker. The API path moves that work out of the request
    # critical path.
    fetchable = [
        t for t in trackers
        if t.get("id") and t["id"] not in archived_ids
    ]
    sounds_by_tid: Dict[str, Tuple[List[Dict], Optional[dict]]] = {}
    if fetchable:
        with ThreadPoolExecutor(max_workers=20) as ex:
            for tid, sounds, promo in ex.map(_sounds_for_tracker, fetchable):
                if tid:
                    sounds_by_tid[tid] = (sounds, promo)

    for t in fetchable:
        tid = t["id"]
        share = t.get("cobrand_share_link") or ""
        name = t.get("name") or ""

        sounds, promo = sounds_by_tid.get(tid, ([], None))
        if not sounds:
            continue

        # `promo_name` came from the scraped promo JSON in the legacy
        # path. The API doesn't return it (the activation_name is on
        # each sound), so fall through to the tracker name for the
        # API-served case. Keeps the response shape stable for callers.
        promo_name = (promo or {}).get("name") or name

        for sound in sounds:
            sid = str(sound.get("sound_id") or "")
            if not sid:
                continue
            sound_map.setdefault(sid, []).append({
                "tracker_id": tid,
                "tracker_name": name or promo_name,
                "tracker_slug": t.get("slug", ""),
                "tracker_is_active": t.get("is_active", True),
                "promo_name": promo_name,
                "activation_name": sound.get("activation_name") or "",
                "sound_title": sound.get("sound_title") or "",
                "cobrand_share_link": share,
            })

    _sound_to_trackers_cache = sound_map
    _cache_timestamp = now
    return sound_map


def _campaign_sound_ids(meta: dict) -> List[str]:
    """Extract clean numeric sound IDs from a campaign's metadata.

    Strips placeholders like "-", embedded URLs (some campaigns have
    pasted full TikTok video URLs into additional_sounds — extract the
    trailing numeric ID).
    """
    out: List[str] = []
    primary = (meta.get("sound_id") or "").strip()
    if primary and primary != "-" and len(primary) >= 5:
        out.append(primary)
    for s in (meta.get("additional_sounds") or []):
        s = (s or "").strip()
        if s.startswith("http"):
            m = re.search(r"/(\d{15,})", s)
            if not m:
                continue
            s = m.group(1)
        if s and s != "-" and len(s) >= 5 and s not in out:
            out.append(s)
    return out


def find_trackers_for_campaign(
    meta: dict,
    *,
    manual_links: Optional[Dict[str, str]] = None,
    archived_tids: Optional[Set[str]] = None,
) -> List[Dict]:
    """Return list of tracker entries linked to this campaign.

    Two sources, unioned:
      1. Sound-ID overlap (auto): the campaign and tracker reference the
         same TikTok sound ID.
      2. Manual override (`tracker_campaign_links` table): a human pinned
         this tracker to this campaign on the TidesTrackers tab. Used for
         cases where sound IDs don't overlap (e.g. re-uploaded original
         sounds, or trackers covering multi-sound rounds).

    Each entry has:
      - the tracker's metadata (id, name, share link, etc.)
      - `matched_sound_ids`: which campaign sounds overlap (may be empty
        if the link is manual-only)
      - `link_source`: "sound_id" | "manual" | "both"

    Bulk callers (e.g. `list_trackers` looping over all campaigns) can
    pre-resolve `manual_links` and `archived_tids` once and pass them in
    to skip the per-campaign DB roundtrip. See CAMP-50.
    """
    from campaign_manager import db as _db

    sound_map = build_sound_to_trackers_map()
    camp_sounds = _campaign_sound_ids(meta)
    slug = (meta.get("slug") or "").strip()

    matches: List[Dict] = []

    # Source 1: sound-ID overlap
    for cs in camp_sounds:
        for hit in sound_map.get(cs, []):
            tid = hit["tracker_id"]
            existing = next((m for m in matches if m["tracker_id"] == tid), None)
            if existing:
                if cs not in existing["matched_sound_ids"]:
                    existing["matched_sound_ids"].append(cs)
            else:
                entry = dict(hit)
                entry["matched_sound_ids"] = [cs]
                entry["link_source"] = "sound_id"
                matches.append(entry)

    # Source 2: manual links (overlay table)
    if slug:
        if manual_links is None:
            try:
                manual_links = _db.get_tracker_campaign_links()  # {tracker_id: slug}
            except Exception:
                manual_links = {}
        if archived_tids is None:
            try:
                archived_tids = set(_db.get_tracker_archives().keys())
            except Exception:
                archived_tids = set()
        manually_linked_tids = {
            tid
            for tid, s in manual_links.items()
            if s == slug and tid not in archived_tids
        }

        # Build a quick tracker_id -> first hit lookup so we can fill in
        # tracker metadata for manual links that don't have a sound match
        tid_to_hit: Dict[str, Dict] = {}
        for hits in sound_map.values():
            for hit in hits:
                tid_to_hit.setdefault(hit["tracker_id"], hit)

        for tid in manually_linked_tids:
            existing = next((m for m in matches if m["tracker_id"] == tid), None)
            if existing:
                # Already auto-matched — promote source to "both"
                existing["link_source"] = "both"
                continue
            hit = tid_to_hit.get(tid)
            if hit:
                entry = dict(hit)
                entry["matched_sound_ids"] = []
                entry["link_source"] = "manual"
                matches.append(entry)
            else:
                # Manual link to a tracker we couldn't fetch metadata for —
                # still surface it so the cron can hit its public API.
                matches.append({
                    "tracker_id": tid,
                    "tracker_name": "",
                    "tracker_slug": "",
                    "tracker_is_active": True,
                    "promo_name": "",
                    "activation_name": "",
                    "sound_title": "",
                    "cobrand_share_link": "",
                    "matched_sound_ids": [],
                    "link_source": "manual",
                })

    return matches


def discovery_report() -> Dict:
    """Run a full discovery pass: which campaigns map to which trackers.

    Returns:
        {
            "campaigns_total": int,
            "active_total": int,
            "matched": [{slug, title, sounds, trackers: [{id,name,...}]}, ...],
            "unmatched": [{slug, title, sounds}, ...],
            "orphan_trackers": [{tracker_id, name, sounds}, ...],
            "generated_at": iso str,
        }

    Used by the Scrape Tasks tab to show "campaigns missing a tracker"
    so the team can fix them, and by the cron to know which trackers
    to query for cross-checking.
    """
    from datetime import datetime
    from campaign_manager import db as _db

    sound_map = build_sound_to_trackers_map()
    campaigns = _db.list_campaigns(status="active")

    matched: List[Dict] = []
    unmatched: List[Dict] = []
    matched_tracker_ids: Set[str] = set()

    for meta in campaigns:
        completion = meta.get("completion_status") or ""
        if completion == "completed":
            continue  # only show booked/none in the active scope
        slug = meta.get("slug", "")
        sounds = _campaign_sound_ids(meta)
        trackers = find_trackers_for_campaign(meta)
        for t in trackers:
            matched_tracker_ids.add(t["tracker_id"])

        entry = {
            "slug": slug,
            "title": meta.get("title") or meta.get("name") or slug,
            "artist": meta.get("artist") or "",
            "song": meta.get("song") or "",
            "completion_status": completion,
            "sound_ids": sounds,
            "trackers": trackers,
        }
        if trackers:
            matched.append(entry)
        else:
            unmatched.append(entry)

    # Orphan trackers — exist but match no active campaign
    all_tracker_ids: Set[str] = set()
    tracker_summaries: Dict[str, Dict] = {}
    for sid, hits in sound_map.items():
        for hit in hits:
            tid = hit["tracker_id"]
            all_tracker_ids.add(tid)
            if tid not in tracker_summaries:
                tracker_summaries[tid] = {
                    "tracker_id": tid,
                    "name": hit["tracker_name"],
                    "promo_name": hit["promo_name"],
                    "is_active": hit["tracker_is_active"],
                    "sound_ids": [],
                    "share_url": hit["cobrand_share_link"],
                }
            if sid not in tracker_summaries[tid]["sound_ids"]:
                tracker_summaries[tid]["sound_ids"].append(sid)

    orphans = [
        tracker_summaries[tid]
        for tid in all_tracker_ids
        if tid not in matched_tracker_ids
    ]

    return {
        "generated_at": datetime.now().isoformat(),
        "active_total": len(matched) + len(unmatched),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "orphan_count": len(orphans),
        "matched": matched,
        "unmatched": unmatched,
        "orphan_trackers": orphans,
    }
