"""Apify Instagram Reels scraper service.

Instagram blocks anonymous scraping (Instaloader returns 401 "Please wait a
few minutes" even for large public accounts, and yt-dlp has no profile
extractor), so IG creators are scraped through the apify/instagram-reel-scraper
actor instead. One actor run covers every IG creator in a refresh, which keeps
Apify spend proportional to reel count rather than creator count.

Items are normalized to the same video dict shape the TikTok scraper emits so
matching, date filtering and matched_videos storage work unchanged.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

log = logging.getLogger(__name__)

ACTOR_ID = "apify/instagram-reel-scraper"
DEFAULT_RESULTS_LIMIT = 50


@dataclass(frozen=True)
class InstagramScrapeResult:
    videos: List[dict] = field(default_factory=list)
    # username (lowercase) -> {status, video_count, error}
    outcomes: Dict[str, dict] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


def clean_username(raw: str) -> str:
    """Normalize '@handle', 'handle', or an instagram.com profile URL to 'handle'."""
    u = (raw or "").strip()
    if "instagram.com/" in u:
        u = u.split("instagram.com/", 1)[1].split("/", 1)[0].split("?", 1)[0]
    return u.lstrip("@").strip().lower()


def _get_client():
    from apify_client import ApifyClient

    token = os.environ.get("APIFY_API_TOKEN", "")
    if not token:
        from campaign_manager.config import Config
        token = Config.APIFY_API_TOKEN
    if not token:
        raise RuntimeError("APIFY_API_TOKEN is not set")
    return ApifyClient(token)


def _dataset_id(run) -> str:
    """apify-client 2.x returns a dict; 3.x returns a pydantic model."""
    if isinstance(run, dict):
        return run.get("defaultDatasetId", "")
    return getattr(run, "default_dataset_id", "") or ""


def _as_dict(item) -> dict:
    if isinstance(item, dict):
        return item
    dump = getattr(item, "model_dump", None)
    return dump() if dump else {}


def _post_url(item: dict) -> str:
    code = item.get("shortCode") or ""
    if code:
        # Reels are "clips"; /reel/ is the link Cobrand and creators share.
        kind = "reel" if item.get("productType") == "clips" else "p"
        return f"https://www.instagram.com/{kind}/{code}/"
    return item.get("url") or ""


def normalize_reel(item: dict) -> dict:
    """Map an apify/instagram-reel-scraper item to the shared video dict schema."""
    music = item.get("musicInfo") or {}
    ts_raw = item.get("timestamp") or ""
    timestamp, upload_date = "", ""
    if ts_raw:
        try:
            dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            timestamp = dt.isoformat()
            upload_date = dt.strftime("%Y%m%d")
        except ValueError:
            timestamp = ""

    audio_id = str(music.get("audio_id") or "")
    owner = (item.get("ownerUsername") or "").lower()
    views = item.get("videoPlayCount") or item.get("videoViewCount") or 0

    return {
        "url": _post_url(item),
        "video_id": str(item.get("id") or ""),
        "shortcode": item.get("shortCode") or "",
        "music_id": audio_id,
        "extracted_sound_id": audio_id,
        "song": music.get("song_name") or "",
        "artist": music.get("artist_name") or "",
        "is_original_sound": bool(music.get("uses_original_audio", False)),
        "caption": item.get("caption") or "",
        "account": f"@{owner}" if owner else "",
        "views": views,
        "likes": item.get("likesCount") or 0,
        "timestamp": timestamp,
        "upload_date": upload_date,
        "platform": "instagram",
    }


def _build_outcomes(usernames: Iterable[str], videos: List[dict]) -> Dict[str, dict]:
    counts: Dict[str, int] = {}
    for v in videos:
        acct = v["account"].lstrip("@")
        counts[acct] = counts.get(acct, 0) + 1
    return {
        u: {"status": "ok" if counts.get(u) else "empty",
            "video_count": counts.get(u, 0), "error": None}
        for u in usernames
    }


def scrape_instagram_reels(
    usernames: Iterable[str],
    start_date: Optional[datetime] = None,
    results_limit: int = DEFAULT_RESULTS_LIMIT,
) -> InstagramScrapeResult:
    """Scrape recent reels for IG creators in a single Apify actor run.

    Never raises: an actor/dataset failure marks every creator as `error`
    so one bad run can't sink the cron, matching the TikTok scraper contract.
    """
    names = sorted({clean_username(u) for u in usernames if clean_username(u)})
    if not names:
        return InstagramScrapeResult()

    run_input = {"username": names, "resultsLimit": results_limit}
    if start_date is not None:
        run_input["onlyPostsNewerThan"] = start_date.strftime("%Y-%m-%d")

    try:
        client = _get_client()
        log.info("Apify IG: scraping %d creators (limit %d each)", len(names), results_limit)
        run = client.actor(ACTOR_ID).call(run_input=run_input)
        if not run:
            raise RuntimeError("actor call returned no run")
        items = client.dataset(_dataset_id(run)).list_items().items
    except Exception as e:
        log.error("Apify IG scrape failed: %s", e)
        err = f"instagram scrape failed: {e}"
        return InstagramScrapeResult(
            outcomes={u: {"status": "error", "video_count": 0, "error": err} for u in names},
            errors=[err],
        )

    videos: List[dict] = []
    for raw in items:
        item = _as_dict(raw)
        if item.get("error"):
            # Private / missing profiles come back as error items.
            log.warning("Apify IG item error: %s", item.get("error"))
            continue
        try:
            video = normalize_reel(item)
        except Exception as e:
            log.warning("Failed to normalize Apify IG item: %s", e)
            continue
        if video["url"] and video["account"]:
            videos.append(video)

    log.info("Apify IG: got %d reels from %d creators", len(videos), len(names))
    return InstagramScrapeResult(videos=videos, outcomes=_build_outcomes(names, videos))
