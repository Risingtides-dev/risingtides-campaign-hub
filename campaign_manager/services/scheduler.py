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
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from campaign_manager import db as _db
from campaign_manager.services.apify_instagram import clean_username
from campaign_manager.utils.helpers import build_round_end_by_slug, round_end_for_video, round_qualified_videos

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


def _shared_key(platform: str, username: str) -> str:
    """Key into the cron's shared video cache.

    TikTok keeps the bare lowercase handle (existing behavior); Instagram is
    namespaced so a creator with the same handle on both platforms can't have
    their TikToks matched as reels or vice versa.
    """
    handle = (username or "").lstrip("@").strip().lower()
    return f"instagram:{handle}" if platform == "instagram" else handle


def _scrape_instagram(usernames, start_date=None):
    from campaign_manager.services.apify_instagram import (
        SCHEDULER_WAIT_BUDGET_SECS,
        scrape_instagram_reels,
    )
    return scrape_instagram_reels(
        usernames,
        start_date=start_date,
        wait_budget_secs=SCHEDULER_WAIT_BUDGET_SECS,
    )


# Concurrency caps — kept low to avoid burst-rate-limit from TikTok.
# 216 creators × parallelism × 500-video pulls used to mean ~108k metadata
# requests in a few minutes from one Railway IP, which TikTok responded to
# by serving empty 200s (silent block). 2 parallel + 50-video cap brings
# total request volume way down, and the per-request jitter spreads the
# burst out further.
DEFAULT_MAX_WORKERS = 2
DEFAULT_VIDEO_LIMIT = 50


def _save_discovered_sounds(slug: str, meta: dict, discovered_sound_ids: list[str]) -> None:
    """Union newly discovered sounds with the campaign's current sound list."""
    current = _db.get_campaign(slug) or {}
    additional = list(current.get("additional_sounds") or [])
    snapshot = set(meta.get("additional_sounds") or [])
    for sound_id in discovered_sound_ids:
        if sound_id not in snapshot and sound_id not in additional:
            additional.append(sound_id)
    _db.update_campaign_fields(slug, {"additional_sounds": additional})


# A native subprocess crash (SIGABRT etc.) kills one creator's yt-dlp, not the
# fleet. Only a widespread crash rate means the environment itself is broken.
NATIVE_CRASH_PREFIX = "native subprocess crash: "
NATIVE_CRASH_FATAL_RATE = 0.5
NATIVE_CRASH_MIN_FLEET = 5


def _scrape_run_is_degraded(
    outcome_counts: dict,
    *,
    total_creators: int,
    campaigns_refreshed: int,
    total_new_matches: int,
    total_videos_checked: int,
    instagram_complete_failure: bool = False,
) -> bool:
    """Return whether scrape results are unsafe to report as healthy."""
    empty_rate = (
        outcome_counts.get("empty", 0) / total_creators
        if total_creators > 0
        else 0.0
    )
    source_failure_rate = (
        outcome_counts.get("error", 0) / total_creators
        if total_creators > 0
        else 0.0
    )
    native_crash_rate = (
        outcome_counts.get("native_crash", 0) / total_creators
        if total_creators > 0
        else 0.0
    )
    return bool(
        instagram_complete_failure
        or (empty_rate > 0.7 and total_creators > 5)
        or (total_creators > 0 and source_failure_rate == 1.0)
        or (source_failure_rate > 0.7 and total_creators > 5)
        or (native_crash_rate > 0.2 and total_creators > 5)
        or (
            campaigns_refreshed > 5
            and total_new_matches == 0
            and total_videos_checked == 0
        )
    )


def _instagram_outcome_counts(requested: set[str], outcomes: dict) -> dict[str, int]:
    """Count only requested creators; absence/unknown status is not success."""
    names = {clean_username(name) for name in requested}
    names.discard("")
    normalized: dict[str, set[str]] = {}
    for raw_name, outcome in outcomes.items():
        name = clean_username(raw_name)
        if not name or name not in names:
            continue
        status = outcome.get("status") if isinstance(outcome, dict) else None
        normalized.setdefault(name, set()).add(
            status if isinstance(status, str) and status in {"ok", "empty", "error"}
            else "missing"
        )
    counts = {"ok": 0, "empty": 0, "error": 0, "missing": 0}
    for name in names:
        statuses = normalized.get(name, set())
        counts[next(iter(statuses)) if len(statuses) == 1 else "missing"] += 1
    return counts


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


def _scrape_creator_accounts_v2(usernames, start_date=None, max_workers=DEFAULT_MAX_WORKERS, on_progress=None):
    """Scrape creator accounts and report per-creator outcomes.

    on_progress: optional callable(done, total, last_username) invoked after
    each account finishes — used by the on-demand trigger (CAMP-21) to report
    live progress. Best-effort; a raising callback never breaks the scrape.

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
        error         — yt-dlp source fetch failed, or both attempts raised
        native_crash  — the child terminated by a native signal

    This is the observability layer that fixes the "133/133 refreshed,
    0 new matches" lie. The cron summary now reports the outcome
    distribution so a run dominated by `empty` is visibly degraded.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from src.scrapers.yt_dlp_runner import NativeSubprocessCrash
    from src.scrapers.master_tracker import TikTokScrapeError

    scrape_tiktok_account, _ = _import_scraper()

    all_videos = []
    accounts_scraped = 0
    errors = []
    outcomes: dict = {}
    native_crashes: list = []

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
            except NativeSubprocessCrash as e:
                # Native allocator corruption is not a network retry, so this
                # creator is done — but one bad subprocess out of ~216 must not
                # cancel the fleet. Report it as a per-creator failure; the
                # systemic guard below still fails the run if crashes are
                # widespread rather than isolated.
                return username, [], f"{NATIVE_CRASH_PREFIX}{e.signal_name}"
            except TikTokScrapeError as e:
                # Keep the previously confirmed cache available to matching,
                # but never call a failed source fetch an empty/success outcome.
                if attempt == 0 and e.reason != "invalid_account":
                    time.sleep(random.uniform(5.0, 10.0))
                    continue
                return username, e.cached_videos, f"source_fetch_failed:{e.reason}"
            except Exception:
                last_err = "unexpected_scrape_error"
                if attempt == 0:
                    # Backoff before retry — TikTok 429s can take 30s+ to clear
                    time.sleep(random.uniform(5.0, 10.0))
                    continue
                return username, [], last_err
        return username, [], last_err or "max_retries"

    total = len(usernames)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scrape_one, u): u for u in usernames}
        for future in as_completed(futures):
            username, videos, error = future.result()
            if error:
                if videos:
                    all_videos.extend(videos)
                errors.append(f"@{username}: {error}")
                is_native = error.startswith(NATIVE_CRASH_PREFIX)
                if is_native:
                    native_crashes.append(username)
                outcomes[username] = {
                    "status": "native_crash" if is_native else "error",
                    "video_count": len(videos),
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
            done += 1
            if on_progress is not None:
                try:
                    on_progress(done, total, username)
                except Exception:
                    log.debug("on_progress callback raised (ignored)", exc_info=True)

    if native_crashes:
        crash_rate = len(native_crashes) / total if total else 0.0
        log.warning(
            "CRON: %d/%d creator(s) died on a native subprocess crash (%.0f%%): %s",
            len(native_crashes), total, crash_rate * 100,
            ", ".join(f"@{u}" for u in native_crashes[:10]),
        )
        # Isolated crashes are creator-level noise. A fleet-wide crash rate is
        # real allocator corruption and must still fail the run loudly.
        if total > NATIVE_CRASH_MIN_FLEET and crash_rate > NATIVE_CRASH_FATAL_RATE:
            raise NativeSubprocessCrash(
                f"{len(native_crashes)}/{total} creators died on native signals",
                -6,
            )

    return all_videos, accounts_scraped, errors, outcomes


EST = ZoneInfo("America/New_York")

_scheduler: Optional[BackgroundScheduler] = None

# ── Scheduler lifecycle ──────────────────────────────────────────────

def init_scheduler(
    database_url: str, hour: int = 6, minute: int = 0,
    campaign_refresh_enabled: bool = True,
):
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
    # Same driver pin as db.init — SQLAlchemy 2.1+ defaults to psycopg v3.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

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

    if campaign_refresh_enabled:
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
    # missed ticks on long-pauses. First fire is APScheduler's interval-trigger
    # default of (now + interval) — no surprise scrape on app boot.
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
    )

    # Conservative Chartmetric campaign linking. Delayed on boot and omitted
    # entirely when credentials are unavailable.
    if os.environ.get("CHARTMETRIC_REFRESH_TOKEN"):
        from campaign_manager.services.chartmetric_autolink import (
            autolink_campaigns, get_autolink_interval_minutes,
        )
        from datetime import datetime as _datetime
        cm_interval = get_autolink_interval_minutes()
        _scheduler.add_job(
            autolink_campaigns, "interval", minutes=cm_interval,
            next_run_time=_datetime.now(EST) + timedelta(minutes=10),
            id="chartmetric_autolink", replace_existing=True,
            coalesce=True, max_instances=1, misfire_grace_time=300,
        )

    # Preserve CRM-declared niche demand for the D1 playlist consumer.
    from campaign_manager.services.notion import request_campaign_niche_refresh
    _scheduler.add_job(
        request_campaign_niche_refresh, "interval", minutes=15,
        id="campaign_niche_refresh", replace_existing=True,
        coalesce=True, max_instances=1, misfire_grace_time=300,
    )

    # Tides Tracker pull (RTA-42): hit the public stats API for every
    # tracker in `tracker_names` every N minutes (default 30). Same
    # cron knobs as notion_sync — `coalesce=True` + `max_instances=1`,
    # first fire is (now + interval) so a deploy doesn't trigger an
    # immediate stats fetch.
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
    )

    # Creator Library stats (CAMP-LIB): rebuild per-creator performance
    # windows from every Tides Tracker, completed campaigns included. The
    # read-time overlay deliberately skips completed campaigns, so without
    # this their view counts stay frozen at whatever the last scrape caught
    # — measured at roughly a 4x undercount across the roster.
    from campaign_manager.services.creator_library_refresh import (
        get_library_stats_interval_minutes,
        run_library_stats_refresh,
    )
    library_interval = get_library_stats_interval_minutes()
    _scheduler.add_job(
        run_library_stats_refresh,
        "interval",
        minutes=library_interval,
        id="library_stats",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    # Cron-log janitor: reaps cron_log rows stuck in 'running' beyond
    # CRON_REAP_THRESHOLD_MINUTES (default 30). Daemon threads spawned
    # from /api/cron/trigger die on worker recycle and leave their rows
    # stuck forever otherwise.
    reap_threshold = int(os.environ.get("CRON_REAP_THRESHOLD_MINUTES", "30"))
    _scheduler.add_job(
        run_cron_log_janitor,
        "interval",
        minutes=5,
        id="cron_log_janitor",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
        kwargs={"threshold_minutes": reap_threshold},
    )

    try:
        if campaign_refresh_enabled:
            _scheduler.start()
        else:
            # Persistent SQLAlchemy jobstores can retain the old cron job across
            # deploys. Load them while paused, remove it, then allow any due jobs
            # to run; never expose the old campaign job to a running scheduler.
            _scheduler.start(paused=True)
            if _scheduler.get_job("campaign_refresh") is not None:
                _scheduler.remove_job("campaign_refresh")
            _scheduler.resume()
    except Exception:
        # A failed removal must not be retried by resuming a stale scheduler.
        # Clear the singleton so the readiness path can retry initialization.
        if _scheduler.running:
            _scheduler.shutdown(wait=False)
        _scheduler = None
        raise
    log.info(
        "Scheduler started: campaign_refresh enabled=%s at %02d:%02d, internal_scrape at "
        "%02d:%02d EST, notion_sync every %d minutes, "
        "tides_tracker_pull every %d minutes, "
        "cron_log_janitor every 5 minutes (threshold=%d min)",
        campaign_refresh_enabled, hour, minute, internal_hour, internal_minute, notion_interval,
        tides_interval, reap_threshold,
    )


def run_cron_log_janitor(threshold_minutes: int = 30):
    """Reap orphaned cron_log rows. Scheduled every 5 minutes by init_scheduler."""
    try:
        reaped = _db.reap_orphaned_cron_logs(threshold_minutes=threshold_minutes)
        if reaped:
            log.warning(
                "JANITOR: reaped %d orphaned cron_log row(s): %s",
                len(reaped), reaped,
            )
    except Exception as e:
        log.error("JANITOR: failed to reap orphaned cron_log rows: %s", e)


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


def trigger_job(job_type: str, request_log_id: int | None = None):
    """Run an accepted manual request and update its durable cron receipt."""
    if job_type == "campaign_refresh":
        return run_campaign_refresh(request_log_id=request_log_id)
    if job_type == "internal_scrape":
        return run_internal_scrape(request_log_id=request_log_id)
    raise ValueError(f"Unknown job type: {job_type}")


# ── Job 1: Campaign Refresh ──────────────────────────────────────────

def _active_run_id(job_type: str) -> int | None:
    try:
        return _db.active_cron_log_id(job_type)
    except Exception:
        log.warning("CRON: active run receipt unavailable for %s", job_type, exc_info=True)
        return None


def _finish_unstarted_request(request_log_id: int | None, status: str, summary: dict) -> None:
    if request_log_id is None:
        return
    try:
        _db.transition_cron_log(request_log_id, "queued", status, summary)
    except Exception:
        log.exception("CRON: could not finish accepted request %s", request_log_id)


CAPACITY_WAIT_SECONDS = 3600


class ScrapeCapacityTimeout(TimeoutError):
    """A distinct scrape could not claim shared capacity within the bound."""


class _CombinedScrapeLease:
    def __init__(self, job_lease, capacity_lease):
        self.job_lease = job_lease
        self.capacity_lease = capacity_lease

    def assert_held(self):
        self.job_lease.assert_held()
        self.capacity_lease.assert_held()


@contextmanager
def _wait_for_scrape_capacity(job_lease):
    """Bounded shared scraper admission; unlike duplicate jobs, distinct jobs wait."""
    deadline = time.monotonic() + CAPACITY_WAIT_SECONDS
    delay = 0.5
    while True:
        job_lease.assert_held()
        with _db.scrape_job_lease("scrape_capacity") as capacity_lease:
            if capacity_lease is not None:
                yield _CombinedScrapeLease(job_lease, capacity_lease)
                return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ScrapeCapacityTimeout("shared scrape capacity wait expired")
        time.sleep(min(delay, remaining))
        delay = min(delay * 2, 15.0)


def _begin_scrape_run(job_type: str, request_log_id: int | None) -> int | None:
    log_id = request_log_id if request_log_id is not None else _db.create_cron_log(
        job_type, status="queued"
    )
    if not _db.transition_cron_log(log_id, "queued", "running"):
        log.warning("CRON: %s request %s was already closed", job_type, log_id)
        return None
    return log_id


def run_campaign_refresh(only_slugs=None, on_progress=None, request_log_id: int | None = None) -> dict:
    """Run one refresh across scheduler, manual and on-demand entrypoints."""
    try:
        with _db.scrape_job_lease("campaign_refresh") as lease:
            if lease is None:
                summary = {"reason": "already_running"}
                active_id = _active_run_id("campaign_refresh")
                if active_id is not None:
                    summary["active_log_id"] = active_id
                _finish_unstarted_request(request_log_id, "skipped", summary)
                log.warning("CRON: campaign_refresh already running; skipping duplicate")
                return {"status": "skipped", "summary": summary}
            if request_log_id is None:
                request_log_id = _db.create_cron_log("campaign_refresh", status="queued")
            if lease.backend_pid is not None and not _db.bind_cron_log_to_scrape_lease(
                    request_log_id, "campaign_refresh", lease):
                return {"status": "skipped", "summary": {"reason": "request_expired"}}
            with _wait_for_scrape_capacity(lease) as guarded_lease:
                log_id = _begin_scrape_run("campaign_refresh", request_log_id)
                if log_id is None:
                    return {"status": "skipped", "summary": {"reason": "request_expired"}}
                return _run_campaign_refresh(only_slugs, on_progress, guarded_lease, log_id)
    except ScrapeCapacityTimeout as exc:
        _finish_unstarted_request(request_log_id, "failed", {"error": str(exc)})
        log.error("CRON: campaign_refresh capacity wait expired: %s", exc)
        return {"status": "failed", "summary": {"error": str(exc)}}
    except _db.ScrapeJobLockLost as exc:
        _finish_unstarted_request(request_log_id, "failed", {"error": str(exc)})
        log.error("CRON: campaign_refresh lock lost; aborted: %s", exc)
        return {"status": "failed", "summary": {"error": str(exc)}}
    except Exception:
        _finish_unstarted_request(
            request_log_id, "failed", {"error": "scrape job lock unavailable"}
        )
        log.exception("CRON: campaign_refresh lock unavailable; refusing to run")
        return {"status": "failed", "summary": {"error": "scrape job lock unavailable"}}


def _run_campaign_refresh(only_slugs, on_progress, lease, request_log_id=None) -> dict:
    """Refresh active campaigns: scrape creators via yt-dlp, run matching, update stats.

    only_slugs: optional iterable of campaign slugs to limit the refresh to
    (CAMP-24 single/selected-campaign trigger). None = all active campaigns.
    The smart-scraper rule (active + not-completed only) still applies — a
    completed campaign passed in only_slugs is filtered out below.

    on_progress: optional callable(done, total, last_username) reported as each
    account finishes scraping (CAMP-21 live progress). Best-effort.
    """
    log.info("CRON: starting campaign_refresh%s",
             f" (scoped to {list(only_slugs)})" if only_slugs else "")
    log_id = request_log_id if request_log_id is not None else _db.create_cron_log("campaign_refresh")

    campaigns_total = 0
    campaigns_refreshed = 0
    campaigns_failed = 0
    total_new_matches = 0
    total_videos_checked = 0
    discovered_sound_ids = []
    errors = []
    per_campaign = {}

    try:
        all_campaigns = _db.list_campaigns(exclude_completed=False)
        round_ends = build_round_end_by_slug(all_campaigns)
        campaigns = [c for c in all_campaigns if c.get("completion_status") != "completed"]
        if only_slugs:
            wanted = {s for s in only_slugs}
            campaigns = [c for c in campaigns if c.get("slug", "") in wanted]
        campaigns_total = len(campaigns)

        # Improvement #4: Deduplicate creators across campaigns
        # Scrape each unique creator once, share results across all their campaigns
        all_usernames = set()
        ig_usernames = set()
        for meta in campaigns:
            campaign_creators = _db.get_creators(meta.get("slug", ""))
            for c in campaign_creators:
                if c.get("status") != "active" or not c.get("username"):
                    continue
                platform = c.get("platform", "tiktok")
                if platform == "tiktok":
                    all_usernames.add(c["username"])
                elif platform == "instagram":
                    ig_usernames.add(c["username"])

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
            all_scraped, _, scrape_errors, scrape_outcomes = _scrape_creator_accounts_v2(
                list(all_usernames),
                start_date=earliest_start,
                max_workers=DEFAULT_MAX_WORKERS,
                on_progress=on_progress,
            )
            errors.extend(scrape_errors)
            # Index by account
            for v in all_scraped:
                acct = (v.get("account", "") or "").lstrip("@").lower()
                if acct:
                    shared_videos.setdefault(acct, []).append(v)

        # Instagram creators go through Apify in one batched run. Their
        # outcomes are kept out of scrape_outcomes so a quiet IG roster can't
        # trip the TikTok rate-limit (empty-rate) anomaly.
        ig_outcomes: dict = {}
        if ig_usernames:
            ig_result = _scrape_instagram(ig_usernames, earliest_start)
            errors.extend(ig_result.errors)
            ig_outcomes = ig_result.outcomes
            for v in ig_result.videos:
                key = _shared_key("instagram", v.get("account", ""))
                shared_videos.setdefault(key, []).append(v)

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
                lease.assert_held()
                result = _refresh_single_campaign(
                    slug, meta, shared_videos=shared_videos, lease=lease,
                    round_end=round_ends.get(slug),
                )
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
            except _db.ScrapeJobLockLost:
                raise
            except Exception as e:
                campaigns_failed += 1
                errors.append(f"{slug}: {e}")
                log.error("CRON: campaign %s failed: %s", slug, e)

        # Auto-dedupe against Tides Tracker submissions BEFORE summarizing
        # so the queue is clean before any Slack notifications go out.
        # Marks every freshly-matched video that's already in a Cobrand
        # tracker as tracked_by='auto:tides_tracker', so the human only
        # sees the truly-new work in the Scrape Tasks tab.
        auto_dedupe_stats: dict = {
            "trackers_polled": 0,
            "trackers_failed": 0,
            "submission_ids_found": 0,
            "queue_rows_auto_tracked": 0,
        }
        try:
            from campaign_manager.services.tides_tracker import (
                auto_track_submitted_videos,
            )
            lease.assert_held()
            dedupe_result = auto_track_submitted_videos(triggered_by="cron")
            auto_dedupe_stats = {
                "trackers_polled": dedupe_result.trackers_polled,
                "trackers_failed": dedupe_result.trackers_failed,
                "submission_ids_found": dedupe_result.submission_ids_found,
                "queue_rows_auto_tracked": dedupe_result.queue_rows_auto_tracked,
            }
            log.info(
                "CRON: auto-dedupe done — trackers=%d/%d submission_ids=%d "
                "queue_rows_auto_tracked=%d",
                dedupe_result.trackers_polled,
                dedupe_result.trackers_polled + dedupe_result.trackers_failed,
                dedupe_result.submission_ids_found,
                dedupe_result.queue_rows_auto_tracked,
            )
        except _db.ScrapeJobLockLost:
            raise
        except Exception as e:
            # Dedupe is a hygiene pass; never let it sink the whole cron run.
            log.warning("CRON: auto-dedupe failed (non-fatal): %s", e)

        # Anomaly detection
        # 1. Empty rate — % of creators that returned 0 videos. >70% is the
        #    rate-limit signal (TikTok blocked us, yt-dlp returned empty).
        # 2. Zero-match anomaly — refreshed many campaigns but found nothing
        #    new. Could be legit (slow day) but combined with high empty rate
        #    means the system is broken, not just quiet.
        total_creators_scraped = len(scrape_outcomes)
        instagram_counts = _instagram_outcome_counts(ig_usernames, ig_outcomes)
        instagram_total = sum(instagram_counts.values())
        instagram_complete_failure = instagram_total > 0 and not (
            instagram_counts["ok"] or instagram_counts["empty"]
        )
        empty_rate = (
            outcome_counts["empty"] / total_creators_scraped
            if total_creators_scraped > 0
            else 0.0
        )
        is_degraded = _scrape_run_is_degraded(
            outcome_counts,
            total_creators=total_creators_scraped,
            campaigns_refreshed=campaigns_refreshed,
            total_new_matches=total_new_matches,
            total_videos_checked=total_videos_checked,
            instagram_complete_failure=instagram_complete_failure,
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
            "scrape_outcomes": scrape_outcomes,
            "instagram_outcome_counts": instagram_counts,
            "instagram_creators_total": instagram_total,
            "instagram_complete_failure": instagram_complete_failure,
            "creators_scraped_total": total_creators_scraped,
            "empty_creator_rate": round(empty_rate, 3),
            "degraded": is_degraded,
            "auto_dedupe": auto_dedupe_stats,
        }

        lease.assert_held()
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
        return _db.get_cron_log_by_id(log_id) or {
            "id": log_id,
            "status": "completed",
            "summary": summary,
        }

    except Exception as e:
        failure_summary = {"error": str(e), "errors": errors[:10]}
        _db.finish_cron_log(log_id, "failed", failure_summary)
        _post_failure_slack("campaign_refresh", str(e))
        log.error("CRON: campaign_refresh failed: %s", e)
        return _db.get_cron_log_by_id(log_id) or {
            "id": log_id,
            "status": "failed",
            "summary": failure_summary,
        }


def _refresh_single_campaign(slug: str, meta: dict, shared_videos: dict = None, lease=None,
                             round_end=None) -> dict:
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

    active = [c for c in creators if c.get("status") == "active" and c.get("username")]
    usernames = [c["username"] for c in active if c.get("platform", "tiktok") == "tiktok"]
    ig_usernames = [c["username"] for c in active if c.get("platform") == "instagram"]

    if not usernames and not ig_usernames:
        start_raw = str(meta.get("start_date") or "").strip()
        countable = round_qualified_videos(
            existing_videos, start_raw, end_date=round_end,
            exclude_dismissed=bool(start_raw),
        )
        if start_raw:
            # No scrape can run, but old cross-round rows may still leave the
            # stored aggregates contaminated. Reconcile without touching rows.
            if lease is not None:
                lease.assert_held()
            _db.save_creators(
                slug, update_creator_post_counts(creators, countable),
            )
            if lease is not None:
                lease.assert_held()
            _db.update_campaign_fields(slug, {
                "total_views": sum(v.get("views", 0) or 0 for v in countable),
                "total_likes": sum(v.get("likes", 0) or 0 for v in countable),
            })
        return {
            "new_matches": 0,
            "total_matches": len(countable),
            "videos_checked": 0,
        }

    # Step 1: Get videos — use shared cache if available, otherwise scrape
    if shared_videos is not None:
        # Pull this campaign's creators from the pre-scraped cache
        all_videos = []
        misses = []
        lookups = [_shared_key("tiktok", u) for u in usernames] + [
            _shared_key("instagram", u) for u in ig_usernames
        ]
        for uname in lookups:
            hits = shared_videos.get(uname, [])
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
        all_videos, scrape_errors = [], []
        if usernames:
            all_videos, _, scrape_errors = _scrape_creator_accounts(
                usernames, start_date=scrape_start, max_workers=DEFAULT_MAX_WORKERS
            )
        if ig_usernames:
            ig_result = _scrape_instagram(ig_usernames, scrape_start)
            all_videos = all_videos + ig_result.videos
            scrape_errors = list(scrape_errors) + ig_result.errors
        if scrape_errors:
            for err in scrape_errors[:5]:
                log.warning("CRON: scrape error for %s: %s", slug, err)

    # Scope candidates before matching; malformed dates cannot prove round
    # membership. No-start campaigns retain the full legacy candidate set.
    all_videos = round_qualified_videos(all_videos, meta.get("start_date"), end_date=round_end)

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
    # TikTok-only: discovered IDs are saved as TikTok additional_sounds, and
    # IG audio IDs aren't resolvable as TikTok sounds downstream.
    tiktok_videos = [v for v in all_videos if v.get("platform", "tiktok") == "tiktok"]
    extra_matched, discovered_sound_ids = discover_original_sounds(
        tiktok_videos, matched, sound_ids, usernames, artist,
        tt_artist_label=tt_artist_label,
        match_strategy=match_strategy,
    )
    matched.extend(extra_matched)

    # Auto-add discovered sounds to campaign (only happens in fuzzy mode now)
    if discovered_sound_ids:
        if lease is not None:
            lease.assert_held()
        _save_discovered_sounds(slug, meta, discovered_sound_ids)

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

    if lease is not None:
        lease.assert_held()
    _db.replace_matched_videos(slug, all_matched)

    # Update creator post counts
    start_raw = str(meta.get("start_date") or "").strip()
    countable = round_qualified_videos(
        all_matched, start_raw, end_date=round_end,
        exclude_dismissed=bool(start_raw),
    )
    updated_creators = update_creator_post_counts(creators, countable)
    if lease is not None:
        lease.assert_held()
    _db.save_creators(slug, updated_creators)

    # Update campaign stats (now with fresh view counts!)
    total_views = sum(v.get("views", 0) or 0 for v in countable)
    total_likes = sum(v.get("likes", 0) or 0 for v in countable)
    if lease is not None:
        lease.assert_held()
    _db.update_campaign_stats(slug, total_views, total_likes)

    if lease is not None:
        lease.assert_held()
    _db.save_scrape_log(slug, {
        "accounts_scraped": len(usernames) + len(ig_usernames),
        "videos_checked": len(all_videos),
        "new_matches": new_count,
        "total_matches": len(countable),
    })

    return {
        "new_matches": new_count,
        "total_matches": len(countable),
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
        ts = v.get("timestamp")
        if not ts:
            excluded_no_ts += 1
            continue
        vdt = None
        if isinstance(ts, datetime):
            vdt = ts.date()
        elif isinstance(ts, str):
            try:
                vdt = datetime.fromisoformat(ts).date()
            except Exception:
                vdt = None
        if vdt is None:
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

def run_internal_scrape(request_log_id: int | None = None):
    """Run one internal scrape across scheduler and manual entrypoints."""
    try:
        with _db.scrape_job_lease("internal_scrape") as lease:
            if lease is None:
                summary = {"reason": "already_running"}
                active_id = _active_run_id("internal_scrape")
                if active_id is not None:
                    summary["active_log_id"] = active_id
                _finish_unstarted_request(request_log_id, "skipped", summary)
                log.warning("CRON: internal_scrape already running; skipping duplicate")
                return {"status": "skipped", "summary": summary}
            if request_log_id is None:
                request_log_id = _db.create_cron_log("internal_scrape", status="queued")
            if lease.backend_pid is not None and not _db.bind_cron_log_to_scrape_lease(
                    request_log_id, "internal_scrape", lease):
                return {"status": "skipped", "summary": {"reason": "request_expired"}}
            with _wait_for_scrape_capacity(lease) as guarded_lease:
                log_id = _begin_scrape_run("internal_scrape", request_log_id)
                if log_id is None:
                    return {"status": "skipped", "summary": {"reason": "request_expired"}}
                return _run_internal_scrape(guarded_lease, log_id)
    except ScrapeCapacityTimeout as exc:
        _finish_unstarted_request(request_log_id, "failed", {"error": str(exc)})
        log.error("CRON: internal_scrape capacity wait expired: %s", exc)
        return {"status": "failed", "summary": {"error": str(exc)}}
    except _db.ScrapeJobLockLost as exc:
        _finish_unstarted_request(request_log_id, "failed", {"error": str(exc)})
        log.error("CRON: internal_scrape lock lost; aborted: %s", exc)
        return {"status": "failed", "summary": {"error": str(exc)}}
    except Exception:
        _finish_unstarted_request(
            request_log_id, "failed", {"error": "scrape job lock unavailable"}
        )
        log.exception("CRON: internal_scrape lock unavailable; refusing to run")
        return {"status": "failed", "summary": {"error": "scrape job lock unavailable"}}


def _run_internal_scrape(lease, request_log_id=None):
    """Scrape all internal creators, update caches and song groupings."""
    log.info("CRON: starting internal_scrape")
    log_id = request_log_id if request_log_id is not None else _db.create_cron_log("internal_scrape")

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

        # Filter to last 48 hours.
        # Sweep #5 fix: the scraper stores `timestamp` as a datetime OBJECT
        # (master_tracker sets 'timestamp': video_dt), but this guarded only
        # `isinstance(ts, str)` — so the check never fired and EVERY video fell
        # through, making `filtered` == full history. The "last 48h" results +
        # Slack summary were silently reporting the entire back-catalogue.
        # Normalize both datetime and str forms.
        cutoff = (datetime.now(EST) - timedelta(hours=48)).astimezone(timezone.utc)
        filtered = []
        for v in all_videos:
            ts = v.get("timestamp", "")
            vdt = None
            if isinstance(ts, datetime):
                vdt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            elif ts and isinstance(ts, str):
                try:
                    vdt = datetime.fromisoformat(ts)
                    if vdt.tzinfo is None:
                        vdt = vdt.replace(tzinfo=timezone.utc)
                except Exception:
                    vdt = None
            if vdt is not None and vdt < cutoff:
                continue
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
                lease.assert_held()
                _db.merge_internal_cache(creator_lower, creator_videos)
                if creator_videos:
                    accounts_successful += 1
            except _db.ScrapeJobLockLost:
                raise
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
        lease.assert_held()
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
            "scope": "full",
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
            lease.assert_held()
            campaign_attach_summary = _attach_internal_to_campaigns(filtered, lease=lease)
            summary_attach_info = campaign_attach_summary
        except _db.ScrapeJobLockLost:
            raise
        except Exception as e:
            log.error("CRON: internal->campaign attach failed: %s", e)
            summary_attach_info = {"error": str(e)}

        summary["campaign_attach"] = summary_attach_info
        lease.assert_held()
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


def _attach_internal_to_campaigns(internal_videos: list, lease=None) -> dict:
    """For each internal-scrape video whose sound ID matches an active
    campaign sound, attach it to that campaign's matched_videos.

    Disambiguation rule when multiple campaigns share a sound ID
    (typical for rounds: r3, r4, r6 may all use the same sound):
        Latest active round whose start is no later than the post wins.
        If start_dates tie, latest created_at wins.
        Posts without a parseable date may attach only to campaigns
        without a start date, preserving their legacy behavior.

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
    from campaign_manager.utils.helpers import round_start_date, video_in_round

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

    # Keep every candidate: the winner depends on the video's post date.
    all_campaigns = _db.list_campaigns(exclude_completed=False)
    round_ends = build_round_end_by_slug(all_campaigns)
    campaigns = [c for c in all_campaigns if c.get("completion_status") != "completed"]
    sound_to_campaigns: dict = {}  # sound_id -> [meta]

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
            sound_to_campaigns.setdefault(sid, []).append(meta)

    # Group internal videos by which campaign they should attach to
    by_campaign: dict = {}  # campaign_slug -> [video_dicts_to_attach]
    attached_meta: dict = {}  # campaign_slug -> meta for round-scoped totals
    for v in internal_videos:
        sid = (v.get("extracted_sound_id") or v.get("music_id") or "").strip()
        if not sid:
            skipped_no_sound_id += 1
            continue
        candidates = sound_to_campaigns.get(sid, [])
        if not candidates:
            skipped_no_active_campaign += 1
            continue
        eligible = []
        for meta in candidates:
            start_raw = str(meta.get("start_date") or "").strip()
            start = round_start_date(start_raw)
            if video_in_round(v, start_raw, end_date=round_ends.get(str(meta.get("slug") or ""))):
                eligible.append((start or datetime.min.date(), str(meta.get("created_at") or ""), str(meta.get("slug") or ""), meta))
        if not eligible:
            skipped_no_active_campaign += 1
            continue
        winning = max(eligible, key=lambda item: item[:3])[3]
        # Tag and stage for attach
        attach_v = dict(v)
        attach_v["match_strategy"] = "internal_creator"
        slug = winning.get("slug", "")
        if not slug:
            continue
        by_campaign.setdefault(slug, []).append(attach_v)
        attached_meta[slug] = winning

    # Merge into each campaign's matched_videos
    for slug, vids in by_campaign.items():
        try:
            existing = _db.get_matched_videos(slug)
            all_matched, new_count = merge_matched_videos(existing, vids)
            # Sanitize timestamps
            for v in all_matched:
                if isinstance(v.get("timestamp"), datetime):
                    v["timestamp"] = v["timestamp"].isoformat()
            if lease is not None:
                lease.assert_held()
            _db.replace_matched_videos(slug, all_matched)
            attached_count += new_count
            per_campaign[slug] = new_count

            # Reconcile dated-round totals even when every URL already exists:
            # old cross-round rows may still be stored from earlier scrapes.
            start = round_start_date(attached_meta[slug].get("start_date"))
            if new_count > 0 or start is not None:
                countable = round_qualified_videos(
                    all_matched, attached_meta[slug].get("start_date"),
                    end_date=round_ends.get(slug),
                    exclude_dismissed=start is not None,
                )
                total_views = sum(v.get("views", 0) or 0 for v in countable)
                total_likes = sum(v.get("likes", 0) or 0 for v in countable)
                if lease is not None:
                    lease.assert_held()
                _db.update_campaign_stats(slug, total_views, total_likes)
        except _db.ScrapeJobLockLost:
            raise
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
    instagram_total = summary.get("instagram_creators_total", 0)
    instagram_outcomes = summary.get("instagram_outcome_counts", {})
    instagram_complete_failure = summary.get("instagram_complete_failure", False)

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

    if instagram_total > 0:
        lines.append(
            f"Instagram creators: {instagram_total} attempted — "
            f"{instagram_outcomes.get('ok', 0)} returned videos, "
            f"{instagram_outcomes.get('empty', 0)} empty, "
            f"{instagram_outcomes.get('error', 0)} errored, "
            f"{instagram_outcomes.get('missing', 0)} missing outcomes"
        )

    if degraded:
        if instagram_complete_failure:
            if instagram_outcomes.get("missing", 0):
                lines.append("_No usable Instagram creator scrape outcomes; results are unavailable. Check cron errors and Apify configuration._")
            else:
                lines.append("_All Instagram creator scrapes failed; Instagram results are unavailable. Check cron errors and Apify configuration._")
        else:
            lines.append(
                "_Scrape anomaly detected. Check TikTok empty/crash rates and matching in cron logs._"
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
