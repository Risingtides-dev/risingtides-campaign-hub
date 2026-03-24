"""APScheduler-based daily scraping scheduler.

Runs two jobs at 6 AM EST:
1. campaign_refresh — scrapes all active campaigns via Apify, runs matching
2. internal_scrape — scrapes all internal creators via Apify, updates caches

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
from campaign_manager.services.apify_scraper import scrape_profiles

log = logging.getLogger(__name__)
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
    """Refresh all active campaigns: scrape creators via Apify, run matching, update stats."""
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

        for meta in campaigns:
            slug = meta.get("slug", "")
            try:
                result = _refresh_single_campaign(slug, meta)
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


def _core_song_name(s: str) -> str:
    """Normalize a song title for fuzzy matching — matches campaigns.py logic."""
    s = re.sub(r"\s*\(feat\..*?\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\(ft\..*?\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*feat\..*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+promo\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+remix\s*$", "", s, flags=re.IGNORECASE)
    return s.strip().lower()


def _refresh_single_campaign(slug: str, meta: dict) -> dict:
    """Refresh a single campaign. Returns result dict with new_matches, total_matches, etc."""
    creators = _db.get_creators(slug)
    existing_videos = _db.get_matched_videos(slug)

    # Build sound set
    sound_ids = set()
    if meta.get("sound_id"):
        sound_ids.add(str(meta["sound_id"]))
    for sid in (meta.get("additional_sounds") or []):
        if sid:
            sound_ids.add(str(sid))

    # Build song+artist keys for secondary matching
    artist = meta.get("artist", "")
    song = meta.get("song", "")
    sound_keys = set()
    if song and artist:
        sound_keys.add(f"{_core_song_name(song)} - {artist.lower().strip()}")

    # Collect TikTok creator usernames
    tiktok_creators = [c for c in creators if c.get("platform", "tiktok") == "tiktok" and c.get("status") == "active"]
    usernames = [c.get("username", "") for c in tiktok_creators if c.get("username")]

    if not usernames:
        return {"new_matches": 0, "total_matches": len(existing_videos), "videos_checked": 0}

    # Scrape via Apify
    all_videos = scrape_profiles(usernames, results_per_page=100)

    # Filter by campaign start_date (same as interactive refresh)
    start_date_str = meta.get("start_date", "")
    if start_date_str:
        try:
            scrape_start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            filtered = []
            for v in all_videos:
                ts = v.get("timestamp", "")
                if ts and isinstance(ts, str):
                    try:
                        vdt = datetime.fromisoformat(ts).date()
                        if vdt < scrape_start:
                            continue
                    except Exception:
                        pass
                filtered.append(v)
            all_videos = filtered
        except ValueError:
            pass  # invalid start_date format, skip filtering

    # Match videos
    matched = []
    discovered_sound_ids = []

    core_song_words = set()
    if song:
        core = _core_song_name(song)
        core_song_words = {w for w in core.split() if len(w) > 2}

    for video in all_videos:
        vid_music_id = video.get("music_id", "")

        # Primary: musicId set lookup
        if vid_music_id and vid_music_id in sound_ids:
            matched.append(video)
            continue

        # Secondary: song+artist key
        v_song = video.get("song", "") or ""
        v_artist = video.get("artist", "") or ""
        if v_song and v_artist:
            v_key = f"{v_song.lower().strip()} - {v_artist.lower().strip()}"
            if v_key in sound_keys:
                matched.append(video)
                continue

        # Fuzzy: core word overlap + artist match
        if core_song_words and v_song:
            v_words = set(_core_song_name(v_song).split())
            overlap = core_song_words & v_words
            if overlap and artist and artist.lower().strip() in v_artist.lower():
                matched.append(video)
                continue

    # Auto-discovery for original sounds
    if artist:
        campaign_artist_lower = artist.lower().strip()
        creator_set = {u.lower() for u in usernames}
        matched_urls = {v.get("url") for v in matched}
        for video in all_videos:
            if video.get("url") in matched_urls:
                continue
            vid_account = (video.get("account", "") or "").lstrip("@").lower()
            if vid_account not in creator_set:
                continue
            vid_song = (video.get("song", "") or "").lower()
            vid_artist = (video.get("artist", "") or "").lower().strip()
            vid_music_id = video.get("music_id", "")
            is_orig = video.get("is_original_sound", False) or vid_song.startswith("original sound")
            if is_orig and vid_artist == campaign_artist_lower and vid_music_id and vid_music_id not in sound_ids:
                matched.append(video)
                discovered_sound_ids.append(vid_music_id)
                sound_ids.add(vid_music_id)

    # Auto-add discovered sounds to campaign
    if discovered_sound_ids:
        current_additional = list(meta.get("additional_sounds") or [])
        for sid in discovered_sound_ids:
            if sid not in current_additional:
                current_additional.append(sid)
        updated_meta = dict(meta)
        updated_meta["additional_sounds"] = current_additional
        _db.save_campaign(slug, updated_meta)

    # Merge matched videos (dedup by URL) and replace all (updates view/like counts)
    existing_urls = {v.get("url") for v in existing_videos}
    new_matches = [v for v in matched if v.get("url") and v["url"] not in existing_urls]
    all_matched = existing_videos + new_matches
    _db.replace_matched_videos(slug, all_matched)

    # Update creator posts_matched
    account_counts = {}
    for v in all_matched:
        acct = (v.get("account", "") or "").lstrip("@").lower()
        if acct:
            account_counts[acct] = account_counts.get(acct, 0) + 1

    updated_creators = []
    for c in creators:
        c = dict(c)
        uname = c.get("username", "").lower()
        c["posts_matched"] = account_counts.get(uname, 0)
        c["posts_done"] = account_counts.get(uname, 0)
        updated_creators.append(c)
    _db.save_creators(slug, updated_creators)

    # Update campaign stats
    total_views = sum(v.get("views", 0) or 0 for v in all_matched)
    total_likes = sum(v.get("likes", 0) or 0 for v in all_matched)
    _db.update_campaign_stats(slug, total_views, total_likes)

    # Save scrape log
    _db.save_scrape_log(slug, {
        "accounts_scraped": len(usernames),
        "videos_checked": len(all_videos),
        "new_matches": len(new_matches),
        "total_matches": len(all_matched),
    })

    return {
        "new_matches": len(new_matches),
        "total_matches": len(all_matched),
        "videos_checked": len(all_videos),
        "discovered_sound_ids": discovered_sound_ids,
    }


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

        all_videos = scrape_profiles(creators, results_per_page=50)

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
