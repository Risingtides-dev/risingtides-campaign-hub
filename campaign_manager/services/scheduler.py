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


# ── Scraper imports (yt-dlp discovery only — RTA-44) ────────────────
def _import_scraper():
    """Lazy-import master_tracker functions.

    Returns (scrape_tiktok_account, match_video_to_sounds). Sound-ID HTML
    enrichment was removed in RTA-44 — performance stats now come from the
    Tides Tracker public API via campaign_stats. Matching falls back to
    yt-dlp's `music_id` field plus song/artist text keys.
    """
    from src.scrapers.master_tracker import (
        scrape_tiktok_account,
        match_video_to_sounds,
    )
    return scrape_tiktok_account, match_video_to_sounds


# Concurrency caps — kept low to avoid burst-rate-limit from TikTok.
# 216 creators × parallelism × 500-video pulls used to mean ~108k metadata
# requests in a few minutes from one Railway IP, which TikTok responded to
# by serving empty 200s (silent block). 2 parallel + 50-video cap brings
# total request volume way down, and the per-request jitter spreads the
# burst out further.
DEFAULT_MAX_WORKERS = 2
DEFAULT_VIDEO_LIMIT = 50


def _scrape_creator_accounts(usernames, start_date=None, max_workers=DEFAULT_MAX_WORKERS):
    """Scrape multiple TikTok creator accounts in parallel using yt-dlp.

    Returns (all_videos, accounts_scraped, errors). Legacy shape — preserved
    for backwards compatibility. New code should call _scrape_creator_accounts_v2
    which also returns per-creator outcomes.
    """
    all_videos, accounts_scraped, errors, _outcomes = _scrape_creator_accounts_v2(
        usernames, start_date=start_date, max_workers=max_workers
    )
    return all_videos, accounts_scraped, errors


def _scrape_creator_accounts_v2(usernames, start_date=None, max_workers=DEFAULT_MAX_WORKERS):
    """Scrape creator accounts and report per-creator outcomes.

    Returns (all_videos, accounts_scraped, errors, outcomes) where outcomes is
    a dict {username: {"status": str, "video_count": int, "error": str|None}}.

    Status values:
        ok            — videos returned (>0)
        empty         — yt-dlp succeeded but returned 0 videos. Could mean
                        the creator has no posts since start_date, OR could
                        mean we got rate-limited and yt-dlp silently returned
                        nothing. Not distinguishable per-creator but a high
                        rate of `empty` across the run is the rate-limit
                        signal.
        error         — yt-dlp raised an exception
        max_retries   — both attempts failed

    This is the observability layer that fixes the "133/133 refreshed,
    0 new matches" lie. The cron summary now reports the outcome
    distribution so a run dominated by `empty` is visibly degraded.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    scrape_tiktok_account, _ = _import_scraper()

    all_videos = []
    accounts_scraped = 0
    errors = []
    outcomes: dict = {}

    def _scrape_one(username):
        # Per-creator jitter (0.5-2s) to spread the burst — 216 creators
        # at max_workers=2 still means ~100 sequential pairs in fast
        # succession otherwise.
        import random
        import time
        time.sleep(random.uniform(0.5, 2.0))

        last_err: Optional[str] = None
        for attempt in range(2):
            try:
                videos = scrape_tiktok_account(
                    f"@{username}",
                    start_date=start_date,
                    limit=DEFAULT_VIDEO_LIMIT,
                    use_cache=True,
                )
                return username, videos, None
            except Exception as e:
                last_err = str(e)
                if attempt == 0:
                    # Backoff before retry — TikTok 429s can take 30s+ to clear
                    time.sleep(random.uniform(5.0, 10.0))
                    continue
                return username, [], last_err
        return username, [], last_err or "max_retries"

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scrape_one, u): u for u in usernames}
        for future in as_completed(futures):
            username, videos, error = future.result()
            if error:
                errors.append(f"@{username}: {error}")
                outcomes[username] = {
                    "status": "error",
                    "video_count": 0,
                    "error": error,
                }
            else:
                all_videos.extend(videos)
                accounts_scraped += 1
                outcomes[username] = {
                    "status": "ok" if videos else "empty",
                    "video_count": len(videos),
                    "error": None,
                }

    return all_videos, accounts_scraped, errors, outcomes


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

    # Notion sync (RTA-10): pull master pages -> resolve memberships every N
    # minutes. Lives in notion_sync.py (not this module) so the test suite
    # can exercise it without importing apscheduler. `coalesce=True` collapses
    # missed ticks on long-pauses; `next_run_time=None` defers the first run
    # until one full interval has elapsed (same hands-off behavior as the
    # cron-style jobs above — no surprise scrape on app boot).
    from campaign_manager.services.notion_sync import (
        get_notion_sync_interval_minutes,
        run_notion_sync,
    )
    notion_interval = get_notion_sync_interval_minutes()
    _scheduler.add_job(
        run_notion_sync,
        "interval",
        minutes=notion_interval,
        id="notion_sync",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
        next_run_time=None,
    )

    # Tides Tracker pull (RTA-42): hit the public stats API for every
    # tracker in `tracker_names` every N minutes (default 30). Same
    # cron knobs as notion_sync — `coalesce=True` + `max_instances=1`,
    # first run deferred one interval so a deploy never produces a
    # surprise stats fetch.
    from campaign_manager.services.tides_tracker import (
        get_tides_tracker_interval_minutes,
        run_tides_tracker_pull,
    )
    tides_interval = get_tides_tracker_interval_minutes()
    _scheduler.add_job(
        run_tides_tracker_pull,
        "interval",
        minutes=tides_interval,
        id="tides_tracker_pull",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
        next_run_time=None,
    )

    _scheduler.start()
    log.info(
        "Scheduler started: campaign_refresh at %02d:%02d, internal_scrape at "
        "%02d:%02d EST, notion_sync every %d minutes, "
        "tides_tracker_pull every %d minutes",
        hour, minute, internal_hour, internal_minute, notion_interval,
        tides_interval,
    )


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
        campaigns = _db.list_campaigns(status="active", exclude_completed=True)
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

        # Bound the pre-scrape by the earliest active campaign start_date.
        # Previously this passed start_date=None which pulled full video history
        # (up to 500 videos per creator) every run -- way more than needed and
        # risked TikTok rate limiting. Now yt-dlp terminates early once it
        # walks past the oldest active campaign's start.
        earliest_start = None
        for meta in campaigns:
            start_str = (meta.get("start_date") or "").strip()
            if not start_str:
                continue
            try:
                d = datetime.strptime(start_str, "%Y-%m-%d")
            except ValueError:
                continue
            if earliest_start is None or d < earliest_start:
                earliest_start = d

        # Pre-scrape all unique creators + extract sound IDs.
        # Uses v2 scraper to capture per-creator outcomes for observability.
        shared_videos = {}  # username -> [videos]
        scrape_outcomes: dict = {}  # username -> {status, video_count, error}
        if all_usernames:
            log.info(
                "CRON: pre-scraping %d unique creators across %d campaigns "
                "(earliest start_date=%s)",
                len(all_usernames), campaigns_total,
                earliest_start.date().isoformat() if earliest_start else "none",
            )
            all_scraped, _, _, scrape_outcomes = _scrape_creator_accounts_v2(
                list(all_usernames),
                start_date=earliest_start,
                max_workers=DEFAULT_MAX_WORKERS,
            )
            # Index by account
            for v in all_scraped:
                acct = (v.get("account", "") or "").lstrip("@").lower()
                if acct:
                    shared_videos.setdefault(acct, []).append(v)

        # Roll up scrape outcome distribution
        outcome_counts = {"ok": 0, "empty": 0, "error": 0}
        for o in scrape_outcomes.values():
            s = o.get("status", "error")
            outcome_counts[s] = outcome_counts.get(s, 0) + 1

        # Track per-campaign new-match links for the daily digest
        new_matches_by_campaign: dict = {}

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
                    "match_strategy": meta.get("match_strategy", "fuzzy"),
                    "match_strategy_breakdown": result.get("strategy_breakdown", {}),
                }
                if result.get("new_match_links"):
                    new_matches_by_campaign[slug] = {
                        "title": meta.get("title") or meta.get("name") or slug,
                        "links": result["new_match_links"],
                    }
            except Exception as e:
                campaigns_failed += 1
                errors.append(f"{slug}: {e}")
                log.error("CRON: campaign %s failed: %s", slug, e)

        # Anomaly detection
        # 1. Empty rate — % of creators that returned 0 videos. >70% is the
        #    rate-limit signal (TikTok blocked us, yt-dlp returned empty).
        # 2. Zero-match anomaly — refreshed many campaigns but found nothing
        #    new. Could be legit (slow day) but combined with high empty rate
        #    means the system is broken, not just quiet.
        total_creators_scraped = len(scrape_outcomes)
        empty_rate = (
            outcome_counts["empty"] / total_creators_scraped
            if total_creators_scraped > 0
            else 0.0
        )
        is_degraded = (
            (empty_rate > 0.7 and total_creators_scraped > 5)
            or (
                campaigns_refreshed > 5
                and total_new_matches == 0
                and total_videos_checked == 0
            )
        )

        summary = {
            "campaigns_total": campaigns_total,
            "campaigns_refreshed": campaigns_refreshed,
            "campaigns_failed": campaigns_failed,
            "total_new_matches": total_new_matches,
            "total_videos_checked": total_videos_checked,
            "discovered_sound_ids": discovered_sound_ids,
            "errors": errors[:10],
            "per_campaign": per_campaign,
            # New observability fields
            "scrape_outcome_counts": outcome_counts,
            "creators_scraped_total": total_creators_scraped,
            "empty_creator_rate": round(empty_rate, 3),
            "degraded": is_degraded,
        }

        _db.finish_cron_log(log_id, "completed", summary)
        _post_campaign_refresh_slack(summary)
        _post_new_matches_digest_slack(new_matches_by_campaign)
        _post_active_sounds_slack()
        log.info(
            "CRON: campaign_refresh done — %d/%d refreshed, %d new matches, "
            "outcomes=%s degraded=%s",
            campaigns_refreshed, campaigns_total, total_new_matches,
            outcome_counts, is_degraded,
        )

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

    _, match_video_to_sounds = _import_scraper()

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
        misses = []
        for uname in usernames:
            hits = shared_videos.get(uname.lower(), [])
            if hits:
                all_videos.extend(hits)
            else:
                misses.append(uname)
        # If we're getting all-misses, log a sample of available keys so we
        # can diagnose the username-mismatch class of bug. Logged at INFO
        # so it shows up in Railway logs without being spammy.
        if misses and not all_videos:
            sample_keys = list(shared_videos.keys())[:5]
            log.info(
                "CRON %s: shared_videos lookup ALL MISSED. usernames=%r sample_keys=%r total_keys=%d",
                slug, usernames[:5], sample_keys, len(shared_videos),
            )
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
            usernames, start_date=scrape_start, max_workers=DEFAULT_MAX_WORKERS
        )
        if scrape_errors:
            for err in scrape_errors[:5]:
                log.warning("CRON: scrape error for %s: %s", slug, err)

    # Filter by campaign start_date
    start_date_str = meta.get("start_date", "")
    if start_date_str:
        try:
            scrape_start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            all_videos = _filter_by_date(all_videos, scrape_start_date)
        except ValueError:
            pass

    # Step 3: Match using strategy specified by the campaign.
    # "strict" disables fuzzy fallback + auto-discovery. Critical for
    # original sound campaigns where multiple campaigns share an artist
    # (e.g. Stella Lefty I-Know-I-Know vs Boston).
    tt_artist_label = meta.get("tt_artist_label", "")
    match_strategy = meta.get("match_strategy", "fuzzy")
    matched = match_videos(
        all_videos, sound_ids, sound_keys, core_song_words, artist,
        match_fn=match_video_to_sounds, tt_artist_label=tt_artist_label,
        match_strategy=match_strategy,
    )

    # Step 4: Auto-discover original sounds — fuzzy mode only
    extra_matched, discovered_sound_ids = discover_original_sounds(
        all_videos, matched, sound_ids, usernames, artist,
        tt_artist_label=tt_artist_label,
        match_strategy=match_strategy,
    )
    matched.extend(extra_matched)

    # Auto-add discovered sounds to campaign (only happens in fuzzy mode now)
    if discovered_sound_ids:
        current_additional = list(meta.get("additional_sounds") or [])
        for sid in discovered_sound_ids:
            if sid not in current_additional:
                current_additional.append(sid)
        updated_meta = dict(meta)
        updated_meta["additional_sounds"] = current_additional
        _db.save_campaign(slug, updated_meta)

    # Cobrand cross-check — for every tracker that covers any of this
    # campaign's sound IDs, fetch its submitted-videos list and pre-mark
    # scraped matches that are already in Cobrand as tracked. This is the
    # difference between a noisy "queue full of stuff already in Cobrand"
    # and a useful "queue of new links the human still needs to paste."
    #
    # Tracker discovery is sound-ID-based (no manual linking required).
    # A campaign with rounds may have multiple trackers — we query all of
    # them and union the tracked-URLs sets.
    cobrand_tracked_count = 0
    try:
        from campaign_manager.services.tracker_discovery import (
            find_trackers_for_campaign,
        )
        from campaign_manager.services.tidestracker import (
            get_tracked_videos as _get_tv,
            normalize_video_url as _norm,
            extract_video_id as _vid,
        )

        tracker_matches = find_trackers_for_campaign(meta)

        if tracker_matches:
            # Union tracked URLs from every tracker that covers this campaign's sounds
            all_tracked_urls: set = set()
            all_tracked_vids: set = set()
            for tm in tracker_matches:
                tv = _get_tv(tm["tracker_id"])
                if tv.get("ok"):
                    all_tracked_urls |= tv.get("urls") or set()
                    all_tracked_vids |= tv.get("video_ids") or set()

            # Tag every matched video that's already in Cobrand
            from datetime import datetime as _dt_now
            now_iso = _dt_now.now().isoformat()
            for v in matched:
                u = v.get("url", "")
                if not u:
                    continue
                norm_u = _norm(u)
                vid = _vid(u)
                if norm_u in all_tracked_urls or (vid and vid in all_tracked_vids):
                    v["tracked_at"] = now_iso
                    v["tracked_by"] = "cobrand_auto"
                    cobrand_tracked_count += 1
    except Exception as e:
        log.warning(
            "CRON: cobrand cross-check failed for %s: %s",
            slug, e,
        )

    # Step 5: Merge — updates view/like counts for existing matches + adds new ones
    existing_urls = {v.get("url") for v in existing_videos if v.get("url")}
    new_match_links = []
    for v in matched:
        url = v.get("url", "")
        if not url or url in existing_urls:
            continue
        # Skip videos already auto-tracked from Cobrand — they shouldn't
        # surface in the daily new-links digest. Your coworker doesn't need
        # to know about them; they're already in tracking.
        if v.get("tracked_at"):
            continue
        new_match_links.append({
            "url": url,
            "account": v.get("account", ""),
            "views": v.get("views", 0),
            "match_strategy": v.get("match_strategy", "unknown"),
        })

    all_matched, new_count = merge_matched_videos(existing_videos, matched)

    # Strategy breakdown — answers "how was each match found?"
    strategy_breakdown: dict = {}
    for v in matched:
        s = v.get("match_strategy", "unknown")
        strategy_breakdown[s] = strategy_breakdown.get(s, 0) + 1

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

    # Save daily stats snapshot for dashboard time-series
    try:
        from datetime import date as date_type
        cid = _db.get_campaign_id(slug)
        if cid:
            total_shares = sum(v.get("shares", 0) or 0 for v in all_matched)
            total_comments = sum(v.get("comments", 0) or 0 for v in all_matched)
            _db.save_stats_snapshot(
                campaign_id=cid,
                snapshot_date=date_type.today(),
                views=total_views,
                likes=total_likes,
                shares=total_shares,
                comments=total_comments,
                post_count=len(all_matched),
            )
    except Exception as e:
        log.warning("CRON: stats snapshot failed for %s: %s", slug, e)

    return {
        "new_matches": new_count,
        "total_matches": len(all_matched),
        "videos_checked": len(all_videos),
        "discovered_sound_ids": discovered_sound_ids,
        "strategy_breakdown": strategy_breakdown,
        "new_match_links": new_match_links,
    }


def _filter_by_date(videos, start_date):
    """Filter videos to only those on or after start_date.

    Videos with missing or malformed timestamps are EXCLUDED (not silently
    passed through). Previously, a video with no timestamp would bypass the
    date check entirely and land in the matched set regardless of campaign
    start_date. This closed that backdoor -- bad metadata now fails safe
    (excluded) instead of fail-open (included).
    """
    filtered = []
    excluded_no_ts = 0
    for v in videos:
        ts = v.get("timestamp", "")
        if not ts or not isinstance(ts, str):
            excluded_no_ts += 1
            continue
        try:
            vdt = datetime.fromisoformat(ts).date()
        except Exception:
            excluded_no_ts += 1
            continue
        if vdt < start_date:
            continue
        filtered.append(v)
    if excluded_no_ts:
        log.info(
            "CRON: _filter_by_date excluded %d video(s) with missing/bad timestamps",
            excluded_no_ts,
        )
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
            creators, start_date=None, max_workers=DEFAULT_MAX_WORKERS
        )
        if scrape_errors:
            for err in scrape_errors[:5]:
                log.warning("CRON: internal scrape error: %s", err)

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

        # Group filtered videos.
        #
        # Group by sound id when available, falling back to title+artist text.
        # Per-video HTML enrichment was removed in RTA-44, so `extracted_sound_id`
        # is now only present on apify-sourced rows; cron-scraped rows fall back
        # to yt-dlp's `music_id` field. Either is the same canonical TikTok
        # sound id, which preserves the I-Know-I-Know vs Boston disambiguation
        # the title-only key used to collapse.
        def _normalize_key(s: str) -> str:
            return re.sub(r"[^\w\s]", "", s.lower()).strip()

        song_groups: dict = {}
        for v in filtered:
            s = v.get("song", "") or ""
            a = v.get("artist", "") or ""
            sid = (v.get("extracted_sound_id") or v.get("music_id") or "").strip()

            # Pick a grouping key: sound_id (preferred) or title+artist text
            if sid:
                key = f"sid:{sid}"
            elif s:
                key = f"text:{_normalize_key(s)} - {_normalize_key(a)}"
            else:
                continue  # no song info AND no sound id — skip

            if key not in song_groups:
                song_groups[key] = {
                    "song": s,
                    "artist": a,
                    "sound_id": sid,
                    "videos": [],
                    "is_original_sound": (
                        v.get("is_original_sound", False)
                        or s.lower().startswith("original sound")
                    ),
                }
            song_groups[key]["videos"].append(v)

        songs_list = sorted(song_groups.values(), key=lambda x: len(x["videos"]), reverse=True)
        unique_songs = len(songs_list)

        # Sanitize datetimes inside the songs JSONB blob — videos coming from
        # yt-dlp / sound enhancement carry datetime objects in the `timestamp`
        # field, which JSON cannot serialize. This bug has been failing the
        # internal_scrape job daily for 10+ days.
        def _sanitize_video(v: dict) -> dict:
            out = dict(v)
            ts = out.get("timestamp")
            if isinstance(ts, datetime):
                out["timestamp"] = ts.isoformat()
            return out

        sanitized_songs = []
        for entry in songs_list[:100]:
            entry_copy = dict(entry)
            entry_copy["videos"] = [
                _sanitize_video(v) for v in (entry.get("videos") or [])
            ]
            sanitized_songs.append(entry_copy)

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
            "songs": sanitized_songs,  # cap at 100 to avoid bloating DB
        })

        summary = {
            "accounts_total": len(creators),
            "accounts_successful": accounts_successful,
            "accounts_failed": accounts_failed,
            "total_videos": len(filtered),
            "unique_songs": unique_songs,
            "errors": [],
        }

        # Cross-reference internal videos against active campaigns.
        # Any internal video whose sound_id matches an active campaign
        # gets attached to that campaign's matched_videos with
        # match_strategy="internal_creator". This unifies the two pipelines
        # so an internal creator post that hits a campaign sound shows up
        # in the campaign's tracking queue, not just the internal song
        # discovery view.
        try:
            campaign_attach_summary = _attach_internal_to_campaigns(filtered)
            summary_attach_info = campaign_attach_summary
        except Exception as e:
            log.error("CRON: internal->campaign attach failed: %s", e)
            summary_attach_info = {"error": str(e)}

        summary["campaign_attach"] = summary_attach_info
        _db.finish_cron_log(log_id, "completed", summary)
        _post_internal_scrape_slack(summary)
        log.info(
            "CRON: internal_scrape done — %d accounts, %d videos, %d songs, "
            "%d internal->campaign attaches",
            len(creators), len(filtered), unique_songs,
            (summary_attach_info or {}).get("attached_count", 0)
            if isinstance(summary_attach_info, dict) else 0,
        )

    except Exception as e:
        _db.finish_cron_log(log_id, "failed", {"error": str(e)})
        _post_failure_slack("internal_scrape", str(e))
        log.error("CRON: internal_scrape failed: %s", e)


def _attach_internal_to_campaigns(internal_videos: list) -> dict:
    """For each internal-scrape video whose sound ID matches an active
    campaign sound, attach it to that campaign's matched_videos.

    Disambiguation rule when multiple campaigns share a sound ID
    (typical for rounds: r3, r4, r6 may all use the same sound):
        Latest active round wins (highest start_date).
        If start_dates tie, latest created_at wins.

    Returns a dict summary:
        {
          "attached_count": int,
          "campaigns_touched": int,
          "skipped_no_sound_id": int,
          "skipped_no_active_campaign": int,
          "per_campaign": {slug: count, ...}
        }

    Only auto-attaches in fuzzy mode OR when the campaign explicitly
    accepts internal hits. In strict mode, attachment STILL happens
    because the match is sound-ID-exact (the whole point of strict).
    """
    from campaign_manager.services.matching import merge_matched_videos

    attached_count = 0
    skipped_no_sound_id = 0
    skipped_no_active_campaign = 0
    per_campaign: dict = {}

    if not internal_videos:
        return {
            "attached_count": 0,
            "campaigns_touched": 0,
            "skipped_no_sound_id": 0,
            "skipped_no_active_campaign": 0,
            "per_campaign": {},
        }

    # Build sound_id -> winning campaign lookup
    campaigns = _db.list_campaigns(status="active", exclude_completed=True)
    sound_to_campaign: dict = {}  # sound_id -> meta

    for meta in campaigns:
        sids = []
        primary = (meta.get("sound_id") or "").strip()
        if primary and primary != "-" and len(primary) >= 5:
            sids.append(primary)
        for sid in (meta.get("additional_sounds") or []):
            s = (sid or "").strip()
            if s and s != "-" and len(s) >= 5 and s not in sids:
                sids.append(s)

        for sid in sids:
            existing = sound_to_campaign.get(sid)
            if existing is None:
                sound_to_campaign[sid] = meta
                continue

            # Disambiguation: latest start_date wins
            def _start_key(m):
                return (m.get("start_date") or "", m.get("created_at") or "")

            if _start_key(meta) > _start_key(existing):
                sound_to_campaign[sid] = meta

    # Group internal videos by which campaign they should attach to
    by_campaign: dict = {}  # campaign_slug -> [video_dicts_to_attach]
    for v in internal_videos:
        sid = (v.get("extracted_sound_id") or v.get("music_id") or "").strip()
        if not sid:
            skipped_no_sound_id += 1
            continue
        winning = sound_to_campaign.get(sid)
        if winning is None:
            skipped_no_active_campaign += 1
            continue
        # Tag and stage for attach
        attach_v = dict(v)
        attach_v["match_strategy"] = "internal_creator"
        slug = winning.get("slug", "")
        if not slug:
            continue
        by_campaign.setdefault(slug, []).append(attach_v)

    # Merge into each campaign's matched_videos
    for slug, vids in by_campaign.items():
        try:
            existing = _db.get_matched_videos(slug)
            all_matched, new_count = merge_matched_videos(existing, vids)
            # Sanitize timestamps
            for v in all_matched:
                if isinstance(v.get("timestamp"), datetime):
                    v["timestamp"] = v["timestamp"].isoformat()
            _db.replace_matched_videos(slug, all_matched)
            attached_count += new_count
            per_campaign[slug] = new_count

            # Refresh campaign-level totals when there were new attaches
            if new_count > 0:
                total_views = sum(v.get("views", 0) or 0 for v in all_matched)
                total_likes = sum(v.get("likes", 0) or 0 for v in all_matched)
                _db.update_campaign_stats(slug, total_views, total_likes)
        except Exception as e:
            log.warning(
                "CRON: failed to attach internal videos to %s: %s", slug, e
            )

    return {
        "attached_count": attached_count,
        "campaigns_touched": len(by_campaign),
        "skipped_no_sound_id": skipped_no_sound_id,
        "skipped_no_active_campaign": skipped_no_active_campaign,
        "per_campaign": per_campaign,
    }


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
    """Post campaign refresh results to Slack with anomaly detection.

    Stops lying about success when nothing actually worked. A run with
    `degraded=True` posts a :warning: header so the team sees it loud.
    """
    client = _get_slack_client()
    channel = _get_cron_channel()
    if not client or not channel:
        return

    now = datetime.now(EST).strftime("%-I:%M %p EST")
    refreshed = summary.get("campaigns_refreshed", 0)
    total = summary.get("campaigns_total", 0)
    new_matches = summary.get("total_new_matches", 0)
    failed = summary.get("campaigns_failed", 0)
    degraded = summary.get("degraded", False)
    outcomes = summary.get("scrape_outcome_counts", {})
    creators_total = summary.get("creators_scraped_total", 0)
    empty_rate = summary.get("empty_creator_rate", 0)
    videos_checked = summary.get("total_videos_checked", 0)

    header = (
        ":warning: *Daily campaign refresh DEGRADED*"
        if degraded
        else "*Daily campaign refresh complete*"
    )
    lines = [f"{header} ({now})"]
    lines.append(
        f"Campaigns: {refreshed}/{total} refreshed | "
        f"Videos checked: {videos_checked} | "
        f"New matches: {new_matches}"
    )

    if creators_total > 0:
        ok = outcomes.get("ok", 0)
        empty = outcomes.get("empty", 0)
        err_count = outcomes.get("error", 0)
        lines.append(
            f"Creators: {creators_total} scraped — "
            f"{ok} returned videos, {empty} empty, {err_count} errored "
            f"({int(empty_rate * 100)}% empty rate)"
        )

    if degraded:
        lines.append(
            "_Run produced no useful data. Likely TikTok rate-limited yt-dlp "
            "(empty rate over 70%) or matching is broken. Check logs._"
        )

    if failed:
        lines.append(f":x: {failed} campaign(s) failed")
        for err in summary.get("errors", [])[:3]:
            lines.append(f"  - {err}")

    try:
        client.chat_postMessage(channel=channel, text="\n".join(lines))
    except Exception as e:
        log.error("CRON: Slack post failed: %s", e)


def _post_new_matches_digest_slack(new_matches_by_campaign: dict):
    """Post a daily digest of NEW matched links per campaign for the human
    whose job is to copy these into tracking tools.

    One Slack message. One section per campaign that has new matches.
    Older view-count updates are NOT included — only links that didn't
    exist before today.
    """
    if not new_matches_by_campaign:
        return

    client = _get_slack_client()
    channel = _get_cron_channel()
    if not client or not channel:
        return

    total_new = sum(len(d["links"]) for d in new_matches_by_campaign.values())
    if total_new == 0:
        return

    now = datetime.now(EST).strftime("%a %b %-d, %-I:%M %p EST")
    lines = [
        f"*New matched links to add to tracking* — {now}",
        f"_{total_new} new link(s) across {len(new_matches_by_campaign)} campaign(s). "
        f"Copy into the tracking tools._",
        "",
    ]

    # Sort campaigns by new-link count, descending
    sorted_campaigns = sorted(
        new_matches_by_campaign.items(),
        key=lambda kv: len(kv[1]["links"]),
        reverse=True,
    )

    for slug, data in sorted_campaigns:
        title = data.get("title") or slug
        links = data.get("links", [])
        if not links:
            continue
        lines.append(f"*{title}* ({len(links)} new)")
        for link in links[:25]:  # cap per campaign to avoid Slack length limits
            url = link.get("url", "")
            account = link.get("account", "")
            views = link.get("views", 0) or 0
            strategy = link.get("match_strategy", "")
            strat_tag = f" [{strategy}]" if strategy and strategy != "sound_id" else ""
            lines.append(f"  • {account} — {url} ({views:,} views){strat_tag}")
        if len(links) > 25:
            lines.append(f"  _… and {len(links) - 25} more_")
        lines.append("")

    try:
        client.chat_postMessage(channel=channel, text="\n".join(lines))
    except Exception as e:
        log.error("CRON: digest Slack post failed: %s", e)


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
