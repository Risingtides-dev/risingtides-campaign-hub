"""oEmbed thumbnail service for TikTok videos.

Uses TikTok's public oEmbed API to fetch video and author thumbnails,
then backfills matched videos that are missing thumbnail_url.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional
from urllib.parse import quote

import requests

from campaign_manager import db as _db

log = logging.getLogger(__name__)

OEMBED_URL = "https://www.tiktok.com/oembed"
REQUEST_TIMEOUT = 10


def fetch_oembed(video_url: str) -> Dict[str, str]:
    """Fetch thumbnail URLs from TikTok's oEmbed API.

    Args:
        video_url: Full TikTok video URL.

    Returns:
        Dict with 'thumbnail_url' and 'author_thumbnail_url' keys.
        Values are empty strings if the fetch fails.
    """
    result = {"thumbnail_url": "", "author_thumbnail_url": ""}

    if not video_url:
        return result

    try:
        resp = requests.get(
            OEMBED_URL,
            params={"url": video_url},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        result = {
            "thumbnail_url": data.get("thumbnail_url", ""),
            "author_thumbnail_url": data.get("author_thumbnail_url", ""),
        }
    except requests.RequestException as e:
        log.warning("oEmbed fetch failed for %s: %s", video_url, e)
    except (ValueError, KeyError) as e:
        log.warning("oEmbed parse failed for %s: %s", video_url, e)

    return result


def backfill_thumbnails(slug: str) -> int:
    """Backfill thumbnail_url for matched videos in a campaign using oEmbed.

    Only fetches thumbnails for videos that don't already have one.

    Args:
        slug: Campaign slug.

    Returns:
        Number of videos updated with thumbnails.
    """
    campaign_id = _db.get_campaign_id(slug)
    if not campaign_id:
        log.warning("backfill_thumbnails: campaign '%s' not found", slug)
        return 0

    videos = _db.get_matched_videos(slug)
    updated_count = 0

    for video in videos:
        if video.get("thumbnail_url"):
            continue

        url = video.get("url", "")
        if not url:
            continue

        oembed_data = fetch_oembed(url)
        thumb = oembed_data.get("thumbnail_url", "")
        if not thumb:
            continue

        # Update the video's thumbnail_url in the database
        try:
            with _db.get_session() as s:
                from campaign_manager.models import MatchedVideo
                mv = s.query(MatchedVideo).filter_by(
                    campaign_id=campaign_id
                ).filter(
                    MatchedVideo.url == url
                ).first()
                if mv:
                    mv.thumbnail_url = thumb
                    s.commit()
                    updated_count += 1
        except Exception as e:
            log.warning("Failed to update thumbnail for %s: %s", url, e)

    log.info("backfill_thumbnails(%s): updated %d/%d videos",
             slug, updated_count, len(videos))
    return updated_count
