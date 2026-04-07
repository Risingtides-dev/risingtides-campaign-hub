"""Shared video matching and merge logic for campaign scraping.

Used by both the scheduler (daily cron) and the manual refresh endpoint
to ensure consistent matching behavior.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Set, Tuple


def core_song_name(s: str) -> str:
    """Normalize a song title for fuzzy matching.

    Strips feat/ft/promo/remix suffixes so 'FEVER DREAM (feat. X) Promo'
    matches 'FEVER DREAM'.
    """
    s = re.sub(r"\s*\(feat\..*?\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\(ft\..*?\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*feat\..*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+promo\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+remix\s*$", "", s, flags=re.IGNORECASE)
    return s.strip().lower()


def build_sound_sets(meta: dict) -> Tuple[Set[str], Set[str], Set[str]]:
    """Build matching sets from campaign metadata.

    Returns (sound_ids, sound_keys, core_song_words).
    """
    sound_ids: Set[str] = set()
    if meta.get("sound_id"):
        sound_ids.add(str(meta["sound_id"]))
    for sid in (meta.get("additional_sounds") or []):
        if sid:
            sound_ids.add(str(sid))

    artist = meta.get("artist", "")
    song = meta.get("song", "")

    sound_keys: Set[str] = set()
    if song and artist:
        sound_keys.add(f"{song.lower().strip()} - {artist.lower().strip()}")
        core = core_song_name(song)
        sound_keys.add(f"{core} - {artist.lower().strip()}")

    core_song_words: Set[str] = set()
    if song:
        core = core_song_name(song)
        core_song_words = {w for w in core.split() if len(w) > 2}

    return sound_ids, sound_keys, core_song_words


def match_videos(
    all_videos: List[Dict],
    sound_ids: Set[str],
    sound_keys: Set[str],
    core_song_words: Set[str],
    artist: str,
    match_fn=None,
) -> List[Dict]:
    """Match videos to campaign sounds using multi-strategy matching.

    Strategies (in order):
    1. master_tracker's match_video_to_sounds (sound_id + song+artist key)
    2. Fuzzy: core word overlap + artist name match

    Args:
        all_videos: Scraped video dicts.
        sound_ids: Numeric sound IDs to match against.
        sound_keys: Normalized "song - artist" keys.
        core_song_words: Core words from song title (len > 2).
        artist: Campaign artist name.
        match_fn: Optional match_video_to_sounds function from master_tracker.
    """
    matched = []
    artist_lower = artist.lower().strip() if artist else ""

    for video in all_videos:
        # Strategy 1: multi-strategy matching from master_tracker
        if match_fn and match_fn(video, sound_ids, sound_keys):
            matched.append(video)
            continue

        # Strategy 1b: direct sound_id check (if no match_fn)
        if not match_fn:
            vid_sid = video.get("extracted_sound_id") or video.get("music_id", "")
            if vid_sid and vid_sid in sound_ids:
                matched.append(video)
                continue

        # Strategy 2: fuzzy word overlap + artist match
        v_song = video.get("song", "") or ""
        v_artist = (video.get("artist", "") or "").lower().strip()
        if core_song_words and v_song:
            v_words = set(core_song_name(v_song).split())
            overlap = core_song_words & v_words
            if overlap and artist_lower and artist_lower in v_artist:
                matched.append(video)

    return matched


def discover_original_sounds(
    all_videos: List[Dict],
    matched: List[Dict],
    sound_ids: Set[str],
    usernames: List[str],
    artist: str,
) -> Tuple[List[Dict], List[str]]:
    """Auto-discover original sound IDs from campaign creator videos.

    When a creator posts using "original sound" but the artist matches,
    capture the sound ID and add the video to matches.

    Returns (additional_matched, discovered_sound_ids).
    """
    if not artist:
        return [], []

    campaign_artist_lower = artist.lower().strip()
    creator_set = {u.lower() for u in usernames}
    matched_urls = {v.get("url") for v in matched}

    additional = []
    discovered = []

    for video in all_videos:
        if video.get("url") in matched_urls:
            continue
        vid_account = (video.get("account", "") or "").lstrip("@").lower()
        if vid_account not in creator_set:
            continue

        vid_song = (video.get("song", "") or "").lower()
        vid_artist = (video.get("artist", "") or "").lower().strip()
        vid_music_id = video.get("extracted_sound_id") or video.get("music_id", "")
        is_orig = video.get("is_original_sound", False) or vid_song.startswith("original sound")

        if is_orig and vid_artist == campaign_artist_lower and vid_music_id and vid_music_id not in sound_ids:
            additional.append(video)
            discovered.append(vid_music_id)
            sound_ids.add(vid_music_id)
            matched_urls.add(video.get("url"))

    return additional, discovered


def merge_matched_videos(
    existing: List[Dict],
    newly_matched: List[Dict],
) -> Tuple[List[Dict], int]:
    """Merge newly matched videos with existing ones.

    - New URLs are appended.
    - Existing URLs get their view/like counts UPDATED with fresh data.

    Returns (merged_list, new_match_count).
    """
    # Index fresh data by URL for stat updates
    fresh_by_url = {}
    for v in newly_matched:
        url = v.get("url")
        if url:
            fresh_by_url[url] = v

    # Update existing videos with fresh stats
    updated_existing = []
    for v in existing:
        url = v.get("url", "")
        if url in fresh_by_url:
            fresh = fresh_by_url.pop(url)
            # Create updated copy with fresh stats but keep existing metadata
            updated = dict(v)
            updated["views"] = fresh.get("views", v.get("views", 0))
            updated["likes"] = fresh.get("likes", v.get("likes", 0))
            # Also update sound info if we now have it
            if fresh.get("extracted_sound_id") and not v.get("extracted_sound_id"):
                updated["extracted_sound_id"] = fresh["extracted_sound_id"]
            if fresh.get("extracted_song_title") and not v.get("extracted_song_title"):
                updated["extracted_song_title"] = fresh["extracted_song_title"]
            updated_existing.append(updated)
        else:
            updated_existing.append(v)

    # Remaining in fresh_by_url are genuinely new matches
    new_matches = list(fresh_by_url.values())
    merged = updated_existing + new_matches

    return merged, len(new_matches)


def update_creator_post_counts(
    creators: List[Dict],
    matched_videos: List[Dict],
) -> List[Dict]:
    """Update posts_matched and posts_done for each creator based on matched videos."""
    account_counts: Dict[str, int] = {}
    for v in matched_videos:
        acct = (v.get("account", "") or "").lstrip("@").lower()
        if acct:
            account_counts[acct] = account_counts.get(acct, 0) + 1

    updated = []
    for c in creators:
        c = dict(c)  # immutable — new copy
        uname = c.get("username", "").lower()
        c["posts_matched"] = account_counts.get(uname, 0)
        c["posts_done"] = account_counts.get(uname, 0)
        updated.append(c)

    return updated
