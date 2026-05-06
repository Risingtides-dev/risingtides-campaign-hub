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
import re
import time
from typing import Dict, List, Optional, Set, Tuple

import requests as _requests

from campaign_manager.services.tidestracker import (
    list_tracker_campaigns,
    TIDESTRACKER_PUBLIC_URL,
)


# Cache: in-process, module-level. Cleared on process restart.
_sound_to_trackers_cache: Optional[Dict[str, List[Dict]]] = None
_cache_timestamp: float = 0.0
_CACHE_TTL = 600  # 10 minutes — cron runs daily but ad-hoc refreshes need fresh-ish data


def _extract_promo_data(share_url: str) -> Optional[dict]:
    """Fetch a Cobrand share page and pull the embedded promotion JSON."""
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

    for t in trackers:
        tid = t.get("id")
        share = t.get("cobrand_share_link") or ""
        name = t.get("name") or ""
        if not tid:
            continue

        promo = _extract_promo_data(share)
        if not promo:
            continue

        promo_name = promo.get("name") or name
        for activation in promo.get("activations") or []:
            seg = activation.get("segment") or {}
            for sound in seg.get("social_sounds") or []:
                sid = str(sound.get("id_platform") or "")
                title = sound.get("title") or ""
                if not sid:
                    continue
                sound_map.setdefault(sid, []).append({
                    "tracker_id": tid,
                    "tracker_name": name or promo_name,
                    "tracker_slug": t.get("slug", ""),
                    "tracker_is_active": t.get("is_active", True),
                    "promo_name": promo_name,
                    "activation_name": activation.get("name") or "",
                    "sound_title": title,
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


def find_trackers_for_campaign(meta: dict) -> List[Dict]:
    """Return list of tracker entries whose sound IDs overlap with this
    campaign's sound IDs.

    Each entry is a tracker dict from build_sound_to_trackers_map() with
    one extra field: `matched_sound_ids` — the specific sound IDs that
    overlap. Useful for surfacing exactly why a tracker was matched.
    """
    sound_map = build_sound_to_trackers_map()
    camp_sounds = _campaign_sound_ids(meta)
    if not camp_sounds:
        return []

    seen_trackers: Set[str] = set()
    matches: List[Dict] = []
    for cs in camp_sounds:
        for hit in sound_map.get(cs, []):
            tid = hit["tracker_id"]
            # Dedup — a tracker covering multiple of the campaign's sounds
            # only appears once, but we accumulate all matched sound IDs
            existing = next((m for m in matches if m["tracker_id"] == tid), None)
            if existing:
                if cs not in existing["matched_sound_ids"]:
                    existing["matched_sound_ids"].append(cs)
            else:
                entry = dict(hit)
                entry["matched_sound_ids"] = [cs]
                matches.append(entry)
                seen_trackers.add(tid)
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
