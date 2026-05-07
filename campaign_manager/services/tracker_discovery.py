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
        try:
            manual_links = _db.get_tracker_campaign_links()  # {tracker_id: slug}
        except Exception:
            manual_links = {}
        manually_linked_tids = {tid for tid, s in manual_links.items() if s == slug}

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
