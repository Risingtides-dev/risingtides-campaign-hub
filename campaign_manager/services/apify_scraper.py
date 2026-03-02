"""Apify TikTok scraper service.

Wraps the clockworks/tiktok-scraper actor to fetch TikTok videos
with full musicMeta (musicId, musicName, musicAuthor, musicOriginal).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import List

from apify_client import ApifyClient

log = logging.getLogger(__name__)

APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")
ACTOR_ID = "clockworks/tiktok-scraper"


def _get_client() -> ApifyClient:
    token = APIFY_API_TOKEN
    if not token:
        from campaign_manager.config import Config
        token = Config.APIFY_API_TOKEN
    if not token:
        raise RuntimeError("APIFY_API_TOKEN is not set")
    return ApifyClient(token)


def _normalize_video(item: dict) -> dict:
    """Normalize an Apify TikTok video item to the existing video dict format."""
    music = item.get("musicMeta") or {}
    author = item.get("authorMeta") or {}

    # Parse timestamp
    ts_iso = item.get("createTimeISO", "")
    timestamp = ""
    if ts_iso:
        try:
            timestamp = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).isoformat()
        except Exception:
            timestamp = ts_iso

    # Upload date in YYYYMMDD format (used by internal scraper cache)
    upload_date = ""
    if ts_iso:
        try:
            upload_date = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).strftime("%Y%m%d")
        except Exception:
            pass

    music_id = str(music.get("musicId", "")) if music.get("musicId") else ""

    return {
        "url": item.get("webVideoUrl") or "",
        "video_id": str(item.get("id", "")),
        "music_id": music_id,
        "extracted_sound_id": music_id,
        "song": music.get("musicName") or "",
        "artist": music.get("musicAuthor") or "",
        "is_original_sound": bool(music.get("musicOriginal", False)),
        "account": f"@{author.get('name', '')}" if author.get("name") else "",
        "views": item.get("playCount") or 0,
        "likes": item.get("diggCount") or 0,
        "timestamp": timestamp,
        "upload_date": upload_date,
        "platform": "tiktok",
    }


def scrape_profiles(
    usernames: List[str],
    results_per_page: int = 100,
) -> List[dict]:
    """Scrape TikTok profiles via Apify clockworks/tiktok-scraper.

    Args:
        usernames: List of TikTok usernames (with or without @).
        results_per_page: Max results per profile.

    Returns:
        List of normalized video dicts matching the existing schema.
    """
    if not usernames:
        return []

    # Build profile URLs
    profiles = []
    for u in usernames:
        u = u.strip().lstrip("@")
        if u:
            profiles.append(f"https://www.tiktok.com/@{u}")

    if not profiles:
        return []

    client = _get_client()

    run_input = {
        "profiles": profiles,
        "resultsPerPage": results_per_page,
        "shouldDownloadCovers": False,
        "shouldDownloadVideos": False,
        "shouldDownloadSubtitles": False,
    }

    try:
        log.info("Apify: scraping %d profiles (max %d per page)", len(profiles), results_per_page)
        run = client.actor(ACTOR_ID).call(run_input=run_input)
        if not run:
            log.error("Apify actor call returned None")
            return []
    except Exception as e:
        log.error("Apify actor call failed: %s", e)
        return []

    # Fetch results from the default dataset
    try:
        dataset_items = client.dataset(run["defaultDatasetId"]).list_items().items
    except Exception as e:
        log.error("Apify dataset fetch failed: %s", e)
        return []

    videos = []
    for item in dataset_items:
        try:
            video = _normalize_video(item)
            if video.get("url"):
                videos.append(video)
        except Exception as e:
            log.warning("Failed to normalize Apify item: %s", e)
            continue

    log.info("Apify: got %d videos from %d profiles", len(videos), len(profiles))
    return videos


def scrape_by_sound(
    sound_id: str,
    results_per_page: int = 500,
) -> List[dict]:
    """Scrape TikTok videos by sound ID via Apify.

    Args:
        sound_id: Numeric TikTok sound ID.
        results_per_page: Max results to fetch.

    Returns:
        List of normalized video dicts.
    """
    if not sound_id:
        return []

    sound_url = f"https://www.tiktok.com/music/sound-{sound_id}"
    client = _get_client()

    run_input = {
        "sounds": [sound_url],
        "resultsPerPage": results_per_page,
        "shouldDownloadCovers": False,
        "shouldDownloadVideos": False,
        "shouldDownloadSubtitles": False,
    }

    try:
        log.info("Apify: scraping sound %s (max %d)", sound_id, results_per_page)
        run = client.actor(ACTOR_ID).call(run_input=run_input)
        if not run:
            log.error("Apify actor call (sound) returned None")
            return []
    except Exception as e:
        log.error("Apify actor call (sound) failed: %s", e)
        return []

    try:
        dataset_items = client.dataset(run["defaultDatasetId"]).list_items().items
    except Exception as e:
        log.error("Apify dataset fetch (sound) failed: %s", e)
        return []

    videos = []
    for item in dataset_items:
        try:
            video = _normalize_video(item)
            if video.get("url"):
                videos.append(video)
        except Exception as e:
            log.warning("Failed to normalize Apify item: %s", e)
            continue

    log.info("Apify: got %d videos for sound %s", len(videos), sound_id)
    return videos
