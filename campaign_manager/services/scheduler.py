"""APScheduler-based daily scraping scheduler.

Runs two jobs at 6 AM EST:
1. campaign_refresh — scrapes all active campaigns via yt-dlp + HTML extraction, runs matching
2. internal_scrape — scrapes all internal creators via yt-dlp, updates caches

Results log to cron_log table and post to Slack.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Set
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from campaign_manager import db as _db

log = logging.getLogger(__name__)


# ── Scraper imports (yt-dlp + HTML extraction, free) ────────────────
def _import_scraper():
    """Lazy-import master_tracker functions. Returns (scrape_tiktok_account, extract_sound_ids_parallel, match_video_to_sounds) or raises ImportError."""
    from src.scrapers.master_tracker import (
        scrape_tiktok_account,
        extract_sound_ids_parallel,
        match_video_to_sounds,
    )
    return scrape_tiktok_account, extract_sound_ids_parallel, match_video_to_sounds


def _scrape_creator_accounts(usernames, start_date=None, max_workers=5):
    """Scrape multiple TikTok creator accounts in parallel using yt-dlp.

    Returns (all_videos, accounts_scraped, errors).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    scrape_tiktok_account, _, _ = _import_scraper()

    all_videos = []
    accounts_scraped = 0
    errors = []

    def _scrape_one(username):
        for attempt in range(2):
            try:
                videos = scrape_tiktok_account(
                    f"@{username}",
                    start_date=start_date,
                    limit=500,
                    use_cache=True,
                )
                return username, videos, None
            except Exception as e:
                if attempt == 0:
                    continue
                return username, [], str(e)
        return username, [], "max retries"

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scrape_one, u): u for u in usernames}
        for future in as_completed(futures):
            username, videos, error = future.result()
            if error:
                errors.append(f"@{username}: {error}")
            else:
                all_videos.extend(videos)
                accounts_scraped += 1

    return all_videos, accounts_scraped, errors


def _enhance_sound_ids(videos, max_workers=10):
    """Extract sound IDs via HTML for videos that don't have them."""
    _, extract_sound_ids_parallel, _ = _import_scraper()

    needing = [v for v in videos if not v.get("extracted_sound_id")]
    if not needing:
        return videos

    try:
        enhanced = extract_sound_ids_parallel(needing, max_workers=max_workers)
        enhanced_dict = {v["url"]: v for v in enhanced}
        return [enhanced_dict.get(v.get("url"), v) for v in videos]
    except Exception as e:
        log.warning("Sound ID extraction failed: %s", e)
        return videos
EST = ZoneInfo("America/New_York")

_scheduler: Optional[BackgroundScheduler] = None
_running_jobs: Set[str] = set()
_running_lock = threading.Lock()


# ── Scheduler lifecycle ──────────────────────────────────────────────

def init_scheduler(database_url: str, hour: int = 6, minute: int = 0):
    """Initialize and start the APScheduler BackgroundScheduler.

    Only one gunicorn worker runs the scheduler (enforced by file lock in create_app).
    """
    global _scheduler

    if _scheduler is not None:
        log.warning("Scheduler already initialized, skipping")
        return

    # Fix Railway's postgres:// prefix for SQLAlchemy
    url = database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    jobstores = {
        "default": SQLAlchemyJobStore(url=url),
    }

    _scheduler = BackgroundScheduler(
        jobstores=jobstores,
        timezone=EST,
    )

    # Stagger internal scrape by 2 minutes, handle minute overflow
    internal_minute = (minute + 2) % 60
    internal_hour = hour + ((minute + 2) // 60)
    if internal_hour >= 24:
        internal_hour = internal_hour % 24

    _scheduler.add_job(
        run_campaign_refresh,
        "cron",
        hour=hour,
        minute=minute,
        id="campaign_refresh",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.add_job(
        run_internal_scrape,
        "cron",
        hour=internal_hour,
        minute=internal_minute,
        id="internal_scrape",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    log.info("Scheduler started: campaign_refresh at %02d:%02d, internal_scrape at %02d:%02d EST",
             hour, minute, internal_hour, internal_minute)


def get_scheduler_status() -> dict:
    """Return scheduler state and next run times."""
    if not _scheduler:
        return {"enabled": False, "running": False, "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })

    return {
        "enabled": True,
        "running": _scheduler.running,
        "jobs": jobs,
    }


def toggle_scheduler(enabled: bool):
    """Pause or resume the scheduler."""
    if not _scheduler:
        return

    if enabled:
        _scheduler.resume()
        log.info("Scheduler resumed")
    else:
        _scheduler.pause()
        log.info("Scheduler paused")


def trigger_job(job_type: str):
    """Manually trigger a job right now. Prevents concurrent runs of the same job."""
    with _running_lock:
        if job_type in _running_jobs:
            log.warning("Job %s is already running, skipping trigger", job_type)
            return
        _running_jobs.add(job_type)

    try:
        if job_type == "campaign_refresh":
            run_campaign_refresh()
        elif job_type == "internal_scrape":
            run_internal_scrape()
        else:
            raise ValueError(f"Unknown job type: {job_type}")
    finally:
        with _running_lock:
            _running_jobs.discard(job_type)


# ── Job 1: Campaign Refresh ──────────────────────────────────────────

def run_campaign_refresh():
    """Refresh all active campaigns: scrape creators via yt-dlp, run matching, update stats."""
    log.info("CRON: starting campaign_refresh")
    log_id = _db.create_cron_log("campaign_refresh")

    campaigns_total = 0
    campaigns_refreshed = 0
    campaigns_failed = 0
    total_new_matches = 0
    total_videos_checked = 0
    discovered_sound_ids = []
    errors = []
    per_campaign = {}

    try:
        campaigns = _db.list_campaigns(status="active")
        campaigns_total = len(campaigns)

        # Improvement #4: Deduplicate creators across campaigns
        # Scrape each unique creator once, share results across all their campaigns
        all_usernames = set()
        for meta in campaigns:
            campaign_creators = _db.get_creators(meta.get("slug", ""))
            for c in campaign_creators:
                if c.get("platform", "tiktok") == "tiktok" and c.get("status") == "active":
                    uname = c.get("username", "")
                    if uname:
                        all_usernames.add(uname)

        # Pre-scrape all unique creators + extract sound IDs
        shared_videos = {}  # username -> [videos]
        if all_usernames:
            log.info("CRON: pre-scraping %d unique creators across %d campaigns",
                     len(all_usernames), campaigns_total)
            all_scraped, _, _ = _scrape_creator_accounts(
                list(all_usernames), start_date=None, max_workers=5
            )
            # Extract sound IDs for all videos at once (much more efficient)
            all_scraped = _enhance_sound_ids(all_scraped, max_workers=10)
            # Index by account
            for v in all_scraped:
                acct = (v.get("account", "") or "").lstrip("@").lower()
                if acct:
                    shared_videos.setdefault(acct, []).append(v)

        for meta in campaigns:
            slug = meta.get("slug", "")
            try:
                result = _refresh_single_campaign(slug, meta, shared_videos=shared_videos)
                campaigns_refreshed += 1
                total_new_matches += result.get("new_matches", 0)
                total_videos_checked += result.get("videos_checked", 0)
                discovered_sound_ids.extend(result.get("discovered_sound_ids", []))
                per_campaign[slug] = {
                    "new_matches": result.get("new_matches", 0),
                    "total_matches": result.get("total_matches", 0),
                }
            except Exception as e:
                campaigns_failed += 1
                errors.append(f"{slug}: {e}")
                log.error("CRON: campaign %s failed: %s", slug, e)

        summary = {
            "campaigns_total": campaigns_total,
            "campaigns_refreshed": campaigns_refreshed,
            "campaigns_failed": campaigns_failed,
            "total_new_matches": total_new_matches,
            "total_videos_checked": total_videos_checked,
            "discovered_sound_ids": discovered_sound_ids,
            "errors": errors[:10],
            "per_campaign": per_campaign,
        }

        status = "completed"
        _db.finish_cron_log(log_id, status, summary)
        _post_campaign_refresh_slack(summary)
        _post_active_sounds_slack()
        log.info("CRON: campaign_refresh done — %d/%d refreshed, %d new matches",
                 campaigns_refreshed, campaigns_total, total_new_matches)

    except Exception as e:
        _db.finish_cron_log(log_id, "failed", {"error": str(e), "errors": errors[:10]})
        _post_failure_slack("campaign_refresh", str(e))
        log.error("CRON: campaign_refresh failed: %s", e)


def _refresh_single_campaign(slug: str, meta: dict, shared_videos: dict = None) -> dict:
    """Refresh a single campaign using yt-dlp + HTML sound extraction (free).

    Pipeline:
    1. Get creator videos (from shared pre-scrape cache or scrape individually)
    2. Match videos using shared multi-strategy matching
    3. Auto-discover original sounds from campaign creators
    4. Merge with existing matches (updates view counts for known videos)

    Args:
        shared_videos: Optional dict of {username: [videos]} pre-scraped by run_campaign_refresh.
                       When provided, skips per-campaign scraping (dedup optimization).
    """
    from campaign_manager.services.matching import (
        build_sound_sets, match_videos, discover_original_sounds,
        merge_matched_videos, update_creator_post_counts,
    )

    _, _, match_video_to_sounds = _import_scraper()

    creators = _db.get_creators(slug)
    existing_videos = _db.get_matched_videos(slug)

    sound_ids, sound_keys, core_song_words = build_sound_sets(meta)
    artist = meta.get("artist", "")

    # Collect TikTok creator usernames
    tiktok_creators = [c for c in creators if c.get("platform", "tiktok") == "tiktok" and c.get("status") == "active"]
    usernames = [c.get("username", "") for c in tiktok_creators if c.get("username")]

    if not usernames:
        return {"new_matches": 0, "total_matches": len(existing_videos), "videos_checked": 0}

    # Step 1: Get videos — use shared cache if available, otherwise scrape
    if shared_videos is not None:
        # Pull this campaign's creators from the pre-scraped cache
        all_videos = []
        for uname in usernames:
            all_videos.extend(shared_videos.get(uname.lower(), []))
    else:
        # Fallback: scrape individually (used by manual trigger_job)
        scrape_start = None
        start_date_str = meta.get("start_date", "")
        if start_date_str:
            try:
                scrape_start = datetime.strptime(start_date_str, "%Y-%m-%d")
            except ValueError:
                pass
        all_videos, _, scrape_errors = _scrape_creator_accounts(
            usernames, start_date=scrape_start, max_workers=5
        )
        if scrape_errors:
            for err in scrape_errors[:5]:
                log.warning("CRON: scrape error for %s: %s", slug, err)
        all_videos = _enhance_sound_ids(all_videos, max_workers=10)

    # Filter by campaign start_date
    start_date_str = meta.get("start_date", "")
    if start_date_str:
        try:
            scrape_start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            all_videos = _filter_by_date(all_videos, scrape_start_date)
        except ValueError:
            pass

    # Step 3: Match using shared multi-strategy logic
    matched = match_videos(all_videos, sound_ids, sound_keys, core_song_words, artist, match_fn=match_video_to_sounds)

    # Step 4: Auto-discover original sounds from campaign creators
    extra_matched, discovered_sound_ids = discover_original_sounds(
        all_videos, matched, sound_ids, usernames, artist
    )
    matched.extend(extra_matched)

    # Auto-add discovered sounds to campaign
    if discovered_sound_ids:
        current_additional = list(meta.get("additional_sounds") or [])
        for sid in discovered_sound_ids:
            if sid not in current_additional:
                current_additional.append(sid)
        updated_meta = dict(meta)
        updated_meta["additional_sounds"] = current_additional
        _db.save_campaign(slug, updated_meta)

    # Step 5: Merge — updates view/like counts for existing matches + adds new ones
    all_matched, new_count = merge_matched_videos(existing_videos, matched)

    # Serialize timestamps
    for v in all_matched:
        if isinstance(v.get("timestamp"), datetime):
            v["timestamp"] = v["timestamp"].isoformat()

    _db.replace_matched_videos(slug, all_matched)

    # Update creator post counts
    updated_creators = update_creator_post_counts(creators, all_matched)
    _db.save_creators(slug, updated_creators)

    # Update campaign stats (now with fresh view counts!)
    total_views = sum(v.get("views", 0) or 0 for v in all_matched)
    total_likes = sum(v.get("likes", 0) or 0 for v in all_matched)
    _db.update_campaign_stats(slug, total_views, total_likes)

    _db.save_scrape_log(slug, {
        "accounts_scraped": len(usernames),
        "videos_checked": len(all_videos),
        "new_matches": new_count,
        "total_matches": len(all_matched),
    })

    return {
        "new_matches": new_count,
        "total_matches": len(all_matched),
        "videos_checked": len(all_videos),
        "discovered_sound_ids": discovered_sound_ids,
    }


def _filter_by_date(videos, start_date):
    """Filter videos to only those on or after start_date."""
    filtered = []
    for v in videos:
        ts = v.get("timestamp", "")
        if ts and isinstance(ts, str):
            try:
                vdt = datetime.fromisoformat(ts).date()
                if vdt < start_date:
                    continue
            except Exception:
                pass
        filtered.append(v)
    return filtered


# ── Job 2: Internal Scrape ───────────────────────────────────────────

def run_internal_scrape():
    """Scrape all internal creators, update caches and song groupings."""
    log.info("CRON: starting internal_scrape")
    log_id = _db.create_cron_log("internal_scrape")

    try:
        creators = _db.get_internal_creators()
        if not creators:
            _db.finish_cron_log(log_id, "completed", {"accounts_total": 0, "errors": []})
            return

        # Scrape via yt-dlp (free) instead of Apify
        all_videos, accounts_ok, scrape_errors = _scrape_creator_accounts(
            creators, start_date=None, max_workers=5
        )
        if scrape_errors:
            for err in scrape_errors[:5]:
                log.warning("CRON: internal scrape error: %s", err)

        # Extract real sound IDs for better song grouping
        all_videos = _enhance_sound_ids(all_videos, max_workers=10)

        # Filter to last 48 hours
        cutoff = datetime.now(EST) - timedelta(hours=48)
        filtered = []
        for v in all_videos:
            ts = v.get("timestamp", "")
            if ts and isinstance(ts, str):
                try:
                    vdt = datetime.fromisoformat(ts)
                    if vdt.tzinfo is None:
                        vdt = vdt.replace(tzinfo=timezone.utc)
                    if vdt < cutoff.astimezone(timezone.utc):
                        continue
                except Exception:
                    pass
            filtered.append(v)

        # Group by account
        by_account = {}
        for v in all_videos:  # use all_videos for cache, filtered for results
            acct = (v.get("account", "") or "").lstrip("@").lower()
            if acct:
                by_account.setdefault(acct, []).append(v)

        # Merge into per-account caches
        accounts_successful = 0
        accounts_failed = 0
        for creator in creators:
            try:
                creator_lower = creator.lower()
                creator_videos = by_account.get(creator_lower, [])
                _db.merge_internal_cache(creator_lower, creator_videos)
                if creator_videos:
                    accounts_successful += 1
            except Exception as e:
                accounts_failed += 1
                log.warning("CRON: internal cache merge failed for %s: %s", creator, e)

        # Group filtered videos by song
        def _normalize_key(s: str) -> str:
            return re.sub(r"[^\w\s]", "", s.lower()).strip()

        song_groups = {}
        for v in filtered:
            s = v.get("song", "") or ""
            a = v.get("artist", "") or ""
            if not s:
                continue
            key = f"{_normalize_key(s)} - {_normalize_key(a)}"
            song_groups.setdefault(key, {"song": s, "artist": a, "videos": []})
            song_groups[key]["videos"].append(v)

        songs_list = sorted(song_groups.values(), key=lambda x: len(x["videos"]), reverse=True)
        unique_songs = len(songs_list)

        # Save results
        _db.save_internal_results({
            "hours": 48,
            "start_dt": cutoff.replace(tzinfo=None).isoformat(),
            "end_dt": datetime.now(EST).replace(tzinfo=None).isoformat(),
            "accounts_total": len(creators),
            "accounts_successful": accounts_successful,
            "accounts_failed": accounts_failed,
            "total_videos": len(filtered),
            "total_videos_unfiltered": len(all_videos),
            "unique_songs": unique_songs,
            "songs": songs_list[:100],  # cap at 100 to avoid bloating DB
        })

        summary = {
            "accounts_total": len(creators),
            "accounts_successful": accounts_successful,
            "accounts_failed": accounts_failed,
            "total_videos": len(filtered),
            "unique_songs": unique_songs,
            "errors": [],
        }

        _db.finish_cron_log(log_id, "completed", summary)
        _post_internal_scrape_slack(summary)
        log.info("CRON: internal_scrape done — %d accounts, %d videos, %d songs",
                 len(creators), len(filtered), unique_songs)

    except Exception as e:
        _db.finish_cron_log(log_id, "failed", {"error": str(e)})
        _post_failure_slack("internal_scrape", str(e))
        log.error("CRON: internal_scrape failed: %s", e)


# ── Slack Notifications ──────────────────────────────────────────────

def _get_slack_client():
    """Get the Slack WebClient from the existing slack-bolt App."""
    try:
        from campaign_manager.services.slack_bot import _slack_app
        if _slack_app and _slack_app.client:
            return _slack_app.client
    except Exception:
        pass
    return None


def _get_cron_channel() -> str:
    """Get the Slack channel for cron notifications."""
    return (os.environ.get("SLACK_CRON_CHANNEL")
            or os.environ.get("SLACK_BOOKING_CHANNEL")
            or "")


def _post_campaign_refresh_slack(summary: dict):
    """Post campaign refresh results to Slack."""
    client = _get_slack_client()
    channel = _get_cron_channel()
    if not client or not channel:
        return

    now = datetime.now(EST).strftime("%-I:%M %p EST")
    refreshed = summary.get("campaigns_refreshed", 0)
    total = summary.get("campaigns_total", 0)
    new_matches = summary.get("total_new_matches", 0)
    failed = summary.get("campaigns_failed", 0)

    lines = [f"*Daily campaign refresh complete* ({now})"]
    lines.append(f"Campaigns: {refreshed}/{total} refreshed, {new_matches} new matches found")
    if failed:
        lines.append(f":warning: {failed} campaign(s) failed")
        for err in summary.get("errors", [])[:3]:
            lines.append(f"  - {err}")

    try:
        client.chat_postMessage(channel=channel, text="\n".join(lines))
    except Exception as e:
        log.error("CRON: Slack post failed: %s", e)


def _post_internal_scrape_slack(summary: dict):
    """Post internal scrape results to Slack."""
    client = _get_slack_client()
    channel = _get_cron_channel()
    if not client or not channel:
        return

    now = datetime.now(EST).strftime("%-I:%M %p EST")
    accounts = summary.get("accounts_total", 0)
    videos = summary.get("total_videos", 0)
    songs = summary.get("unique_songs", 0)

    text = f"*Daily internal scrape complete* ({now})\nInternal: {accounts} accounts, {videos} videos, {songs} unique songs"

    try:
        client.chat_postMessage(channel=channel, text=text)
    except Exception as e:
        log.error("CRON: Slack post failed: %s", e)


def _post_active_sounds_slack():
    """Post active campaign sounds to the dedicated sounds channel."""
    channel = os.environ.get("SLACK_SOUNDS_CHANNEL", "")
    if not channel:
        return
    try:
        from campaign_manager.services.slack_sounds import post_sounds_to_slack
        result = post_sounds_to_slack(channel)
        if result.get("ok"):
            log.info("CRON: sounds posted to %s — %s", channel, result.get("message", result.get("sound_count")))
        else:
            log.warning("CRON: sounds post issue: %s", result.get("error"))
    except Exception as e:
        log.error("CRON: sounds post failed: %s", e)


def _post_failure_slack(job_type: str, error: str):
    """Post a failure notification to Slack."""
    client = _get_slack_client()
    channel = _get_cron_channel()
    if not client or not channel:
        return

    now = datetime.now(EST).strftime("%-I:%M %p EST")
    text = f":x: *Daily scrape failed* ({now})\nJob: `{job_type}`\nError: {error}"

    try:
        client.chat_postMessage(channel=channel, text=text)
    except Exception as e:
        log.error("CRON: Slack failure post failed: %s", e)
