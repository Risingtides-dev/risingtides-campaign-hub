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
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

log = logging.getLogger(__name__)

ACTOR_ID = "apify/instagram-reel-scraper"
DEFAULT_RESULTS_LIMIT = 50
# Keep request-triggered refreshes comfortably inside gunicorn --timeout 120.
REQUEST_WAIT_BUDGET_SECS = 75
SCHEDULER_WAIT_BUDGET_SECS = 600
_RUNNING_STATUSES = {"READY", "RUNNING"}
_TIMEOUT_ERROR = (
    "Instagram scrape still running on Apify — skipped this refresh; "
    "the nightly refresh will include it"
)


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


def _run_value(run, dict_key: str, attr: str) -> str:
    value = run.get(dict_key, "") if isinstance(run, dict) else getattr(run, attr, "")
    return str(getattr(value, "value", value) or "")


def _timeout_result(names: List[str]) -> InstagramScrapeResult:
    return InstagramScrapeResult(
        outcomes={
            u: {"status": "error", "video_count": 0, "error": _TIMEOUT_ERROR}
            for u in names
        },
        errors=[_TIMEOUT_ERROR],
    )


def _abort_run(client, run) -> None:
    run_id = _run_value(run, "id", "id")
    if not run_id or not hasattr(client, "run"):
        return
    try:
        client.run(run_id).abort(timeout=timedelta(seconds=1))
    except Exception as exc:
        log.warning("Apify IG: could not abort timed-out run %s: %s", run_id, exc)


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
    wait_budget_secs: float = REQUEST_WAIT_BUDGET_SECS,
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
        started_at = time.monotonic()
        budget = max(float(wait_budget_secs), 0.001)
        actor = client.actor(ACTOR_ID)
        try:
            run = actor.start(
                run_input=run_input,
                run_timeout=timedelta(seconds=budget),
                timeout=timedelta(seconds=budget),
            )
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower():
                return _timeout_result(names)
            raise
        if not run:
            raise RuntimeError("actor start returned no run")
        remaining = budget - (time.monotonic() - started_at)
        if remaining <= 0:
            _abort_run(client, run)
            return _timeout_result(names)
        run_client = client.run(_run_value(run, "id", "id"))
        try:
            run = run_client.wait_for_finish(
                wait_duration=timedelta(seconds=remaining),
                timeout=timedelta(seconds=remaining),
            )
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower():
                _abort_run(client, run)
                return _timeout_result(names)
            raise
        if not run:
            raise RuntimeError("actor wait returned no run")
        status = _run_value(run, "status", "status").upper()
        if status in _RUNNING_STATUSES:
            _abort_run(client, run)
            log.warning("Apify IG: run exceeded %.1fs budget", budget)
            return _timeout_result(names)
        if status and status != "SUCCEEDED":
            raise RuntimeError(f"actor run ended with status {status}")

        remaining = budget - (time.monotonic() - started_at)
        if remaining <= 0:
            return _timeout_result(names)
        try:
            items = client.dataset(_dataset_id(run)).list_items(
                timeout=timedelta(seconds=remaining)
            ).items
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower():
                log.warning("Apify IG: dataset read exceeded %.1fs total budget", budget)
                return _timeout_result(names)
            raise
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
