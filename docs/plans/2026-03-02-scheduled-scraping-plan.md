# Scheduled Daily Scraping Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automate daily campaign refresh and internal scraping at 6 AM EST with Slack notifications and on-site logging.

**Architecture:** APScheduler's `BackgroundScheduler` runs inside the Flask/gunicorn process, using `SQLAlchemyJobStore` for cross-worker deduplication. Two jobs fire daily: campaign refresh (all active campaigns) and internal scrape (all internal creators). Results log to a `cron_log` DB table and post to Slack.

**Tech Stack:** APScheduler 3.10+, SQLAlchemy (existing), slack-bolt (existing), Flask (existing)

**Design doc:** `docs/plans/2026-03-02-scheduled-scraping-design.md`

---

### Task 1: Add CronLog Model

**Files:**
- Modify: `campaign_manager/models.py:296` (after InternalScrapeResult)

**Step 1: Add the CronLog model**

Add this class at the end of `models.py` (after `InternalScrapeResult`):

```python
class CronLog(Base):
    """Logs each scheduled cron job run."""
    __tablename__ = "cron_log"

    id = Column(Integer, primary_key=True)
    job_type = Column(String(50), nullable=False, index=True)   # 'campaign_refresh' | 'internal_scrape'
    status = Column(String(20), nullable=False, index=True)     # 'running' | 'completed' | 'failed'
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    summary = Column(JSONB, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "job_type": self.job_type or "",
            "status": self.status or "",
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "finished_at": self.finished_at.isoformat() if self.finished_at else "",
            "summary": self.summary or {},
        }
```

**Step 2: Update the models import in db.py**

In `campaign_manager/db.py`, line 18, add `CronLog` to the import:

```python
from campaign_manager.models import (
    Base, Campaign, Creator, MatchedVideo, ScrapeLog,
    InboxItem, PaypalMemory, InternalCreator, InternalVideoCache,
    InternalScrapeResult, CronLog,
)
```

**Step 3: Verify table auto-creates**

The existing `Base.metadata.create_all(_engine)` call in `db.init()` (line 44) will pick up the new model automatically. No migration script needed.

**Step 4: Commit**

```bash
git add campaign_manager/models.py campaign_manager/db.py
git commit -m "feat: add CronLog model for scheduled scraping"
```

---

### Task 2: Add CronLog CRUD Helpers

**Files:**
- Modify: `campaign_manager/db.py` (add new section after Internal Scrape Results, ~line 592)

**Step 1: Add cron log helpers**

Add a new section at the end of `db.py` (before the Notion Sync section, or after it — placement doesn't matter):

```python
# ── Cron Logs ────────────────────────────────────────────────────────

def create_cron_log(job_type: str) -> int:
    """Create a new cron log entry with status 'running'. Returns the log ID."""
    with get_session() as s:
        log = CronLog(
            job_type=job_type,
            status="running",
            started_at=datetime.now(EST).replace(tzinfo=None),
        )
        s.add(log)
        s.commit()
        return log.id


def finish_cron_log(log_id: int, status: str, summary: dict):
    """Mark a cron log as completed or failed with summary data."""
    with get_session() as s:
        log = s.query(CronLog).filter_by(id=log_id).first()
        if log:
            log.status = status
            log.finished_at = datetime.now(EST).replace(tzinfo=None)
            log.summary = summary
            s.commit()


def get_cron_logs(limit: int = 20, offset: int = 0) -> List[Dict]:
    """Get paginated cron log history, newest first."""
    with get_session() as s:
        logs = s.query(CronLog)\
            .order_by(desc(CronLog.started_at))\
            .offset(offset).limit(limit).all()
        return [l.to_dict() for l in logs]


def get_cron_log_by_id(log_id: int) -> Optional[Dict]:
    """Get a single cron log entry by ID."""
    with get_session() as s:
        log = s.query(CronLog).filter_by(id=log_id).first()
        return log.to_dict() if log else None
```

**Step 2: Commit**

```bash
git add campaign_manager/db.py
git commit -m "feat: add cron log CRUD helpers"
```

---

### Task 3: Create Scheduler Service

**Files:**
- Create: `campaign_manager/services/scheduler.py`

**Step 1: Create the scheduler service**

Create `campaign_manager/services/scheduler.py` with the full scheduler, job functions, and Slack notification logic:

```python
"""APScheduler-based daily scraping scheduler.

Runs two jobs at 6 AM EST:
1. campaign_refresh — scrapes all active campaigns via Apify, runs matching
2. internal_scrape — scrapes all internal creators via Apify, updates caches

Results log to cron_log table and post to Slack.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from campaign_manager import db as _db
from campaign_manager.services.apify_scraper import scrape_profiles

log = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")

_scheduler: Optional[BackgroundScheduler] = None


# ── Scheduler lifecycle ──────────────────────────────────────────────

def init_scheduler(database_url: str, hour: int = 6, minute: int = 0):
    """Initialize and start the APScheduler BackgroundScheduler."""
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
        hour=hour,
        minute=minute + 2,  # stagger by 2 min to avoid overlapping Apify calls
        id="internal_scrape",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    log.info("Scheduler started: campaign_refresh + internal_scrape at %02d:%02d EST", hour, minute)


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
    """Manually trigger a job right now."""
    if job_type == "campaign_refresh":
        run_campaign_refresh()
    elif job_type == "internal_scrape":
        run_internal_scrape()
    else:
        raise ValueError(f"Unknown job type: {job_type}")


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

        status = "completed" if campaigns_failed == 0 else "completed"
        _db.finish_cron_log(log_id, status, summary)
        _post_campaign_refresh_slack(summary)
        log.info("CRON: campaign_refresh done — %d/%d refreshed, %d new matches",
                 campaigns_refreshed, campaigns_total, total_new_matches)

    except Exception as e:
        _db.finish_cron_log(log_id, "failed", {"error": str(e), "errors": errors[:10]})
        _post_failure_slack("campaign_refresh", str(e))
        log.error("CRON: campaign_refresh failed: %s", e)


def _refresh_single_campaign(slug: str, meta: dict) -> dict:
    """Refresh a single campaign. Returns result dict with new_matches, total_matches, etc."""
    import re

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
        sound_keys.add(f"{song.lower().strip()} - {artist.lower().strip()}")

    # Collect TikTok creator usernames
    tiktok_creators = [c for c in creators if c.get("platform", "tiktok") == "tiktok" and c.get("status") == "active"]
    usernames = [c.get("username", "") for c in tiktok_creators if c.get("username")]

    if not usernames:
        return {"new_matches": 0, "total_matches": len(existing_videos), "videos_checked": 0}

    # Scrape via Apify
    all_videos = scrape_profiles(usernames, results_per_page=100)

    # Match videos
    matched = []
    discovered_sound_ids = []

    def _core_name(s: str) -> str:
        return re.sub(r"[^\w\s]", "", s.lower()).strip()

    core_song_words = set()
    if song:
        core_song_words = {w for w in _core_name(song).split() if len(w) > 2}

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
            v_words = set(_core_name(v_song).split())
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

    # Merge matched videos (dedup by URL)
    existing_urls = {v.get("url") for v in existing_videos}
    new_matches = [v for v in matched if v.get("url") and v["url"] not in existing_urls]
    all_matched = existing_videos + new_matches
    _db.save_matched_videos(slug, new_matches)

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
                    from datetime import timezone
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
        import re
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
```

**Step 2: Commit**

```bash
git add campaign_manager/services/scheduler.py
git commit -m "feat: create scheduler service with campaign refresh + internal scrape jobs"
```

---

### Task 4: Create Cron API Blueprint

**Files:**
- Create: `campaign_manager/blueprints/cron.py`

**Step 1: Create the cron blueprint**

Create `campaign_manager/blueprints/cron.py`:

```python
"""Cron scheduler API endpoints.

Provides status, logs, manual trigger, and toggle for the daily scraping scheduler.
"""
from __future__ import annotations

import threading

from flask import Blueprint, jsonify, request

from campaign_manager import db as _db
from campaign_manager.services.scheduler import (
    get_scheduler_status,
    toggle_scheduler,
    trigger_job,
)

cron_bp = Blueprint("cron", __name__)


@cron_bp.route("/api/cron/status")
def cron_status():
    """Get scheduler state and next run times."""
    return jsonify(get_scheduler_status())


@cron_bp.route("/api/cron/logs")
def cron_logs():
    """Get paginated cron log history."""
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    logs = _db.get_cron_logs(limit=limit, offset=offset)
    return jsonify({"logs": logs})


@cron_bp.route("/api/cron/logs/<int:log_id>")
def cron_log_detail(log_id: int):
    """Get a single cron log with full summary."""
    log_entry = _db.get_cron_log_by_id(log_id)
    if not log_entry:
        return jsonify({"error": "Log not found"}), 404
    return jsonify(log_entry)


@cron_bp.route("/api/cron/trigger", methods=["POST"])
def cron_trigger():
    """Manually trigger a job. Body: {"job_type": "campaign_refresh"|"internal_scrape"}"""
    data = request.get_json(silent=True) or {}
    job_type = data.get("job_type", "")

    if job_type not in ("campaign_refresh", "internal_scrape"):
        return jsonify({"error": "Invalid job_type. Use 'campaign_refresh' or 'internal_scrape'"}), 400

    # Run in background thread so we return immediately
    thread = threading.Thread(target=trigger_job, args=(job_type,), daemon=True)
    thread.start()

    return jsonify({"status": "triggered", "job_type": job_type})


@cron_bp.route("/api/cron/toggle", methods=["POST"])
def cron_toggle():
    """Enable or disable the scheduler. Body: {"enabled": true|false}"""
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", True)

    toggle_scheduler(enabled)
    return jsonify({"enabled": enabled})
```

**Step 2: Commit**

```bash
git add campaign_manager/blueprints/cron.py
git commit -m "feat: add cron API blueprint (status, logs, trigger, toggle)"
```

---

### Task 5: Wire Scheduler into App Factory

**Files:**
- Modify: `campaign_manager/__init__.py`
- Modify: `campaign_manager/config.py`

**Step 1: Add scheduler config vars**

In `campaign_manager/config.py`, add these lines at the end of the `Config` class:

```python
    # Scheduler (daily cron)
    SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "false").lower() == "true"
    SLACK_CRON_CHANNEL = os.environ.get("SLACK_CRON_CHANNEL", "")
    CRON_HOUR = int(os.environ.get("CRON_HOUR", "6"))
    CRON_MINUTE = int(os.environ.get("CRON_MINUTE", "0"))
```

**Step 2: Modify create_app() to init scheduler and register cron blueprint**

In `campaign_manager/__init__.py`, add the cron blueprint import and registration after the existing blueprints, and add the scheduler init after Slack init:

```python
def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    # Initialize CORS
    CORS(app, origins=app.config["CORS_ORIGINS"])

    # Initialize database
    db.init(app.config.get("DATABASE_URL"))

    from campaign_manager.blueprints.health import health_bp
    from campaign_manager.blueprints.campaigns import campaigns_bp
    from campaign_manager.blueprints.internal import internal_bp
    from campaign_manager.blueprints.inbox import inbox_bp
    from campaign_manager.blueprints.webhooks import webhooks_bp
    from campaign_manager.blueprints.migrate import migrate_bp
    from campaign_manager.blueprints.slack_events import slack_events_bp
    from campaign_manager.blueprints.cron import cron_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(internal_bp)
    app.register_blueprint(inbox_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(migrate_bp)
    app.register_blueprint(slack_events_bp)
    app.register_blueprint(cron_bp)

    # Initialize Slack bot (no-op if credentials aren't set)
    if app.config.get("SLACK_BOT_TOKEN"):
        from campaign_manager.services.slack_bot import init_slack_app
        init_slack_app()

    # Initialize scheduler (only if enabled and DB is active)
    if app.config.get("SCHEDULER_ENABLED") and db.is_active():
        from campaign_manager.services.scheduler import init_scheduler
        init_scheduler(
            database_url=app.config["DATABASE_URL"],
            hour=app.config.get("CRON_HOUR", 6),
            minute=app.config.get("CRON_MINUTE", 0),
        )

    return app
```

**Step 3: Commit**

```bash
git add campaign_manager/__init__.py campaign_manager/config.py
git commit -m "feat: wire scheduler + cron blueprint into app factory"
```

---

### Task 6: Add APScheduler Dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add APScheduler to requirements**

Add after the `apify-client` line:

```
# Scheduled jobs (daily cron)
APScheduler>=3.10.0
```

**Step 2: Commit**

```bash
git add requirements.txt
git commit -m "feat: add APScheduler dependency"
```

---

### Task 7: Deploy and Test

**Step 1: Push to fork**

```bash
git push fork main
```

**Step 2: Add env vars on Railway**

Set on Railway dashboard:
- `SCHEDULER_ENABLED=true`
- `SLACK_CRON_CHANNEL` (optional — set to a test channel, or let it fall back to `SLACK_BOOKING_CHANNEL`)

**Step 3: Verify deployment**

```bash
curl https://risingtides-campaign-hub-production.up.railway.app/api/cron/status
```

Expected response:
```json
{
  "enabled": true,
  "running": true,
  "jobs": [
    {"id": "campaign_refresh", "next_run": "2026-03-03T06:00:00-05:00"},
    {"id": "internal_scrape", "next_run": "2026-03-03T06:02:00-05:00"}
  ]
}
```

**Step 4: Manual trigger test — campaign refresh**

```bash
curl -X POST https://risingtides-campaign-hub-production.up.railway.app/api/cron/trigger \
  -H "Content-Type: application/json" \
  -d '{"job_type": "campaign_refresh"}'
```

Wait ~2 minutes, then check logs:

```bash
curl https://risingtides-campaign-hub-production.up.railway.app/api/cron/logs
```

Verify: log entry with `status: "completed"`, summary shows campaign counts and match data.

**Step 5: Manual trigger test — internal scrape**

```bash
curl -X POST https://risingtides-campaign-hub-production.up.railway.app/api/cron/trigger \
  -H "Content-Type: application/json" \
  -d '{"job_type": "internal_scrape"}'
```

Wait ~1 minute, check logs again. Verify internal scrape entry appears.

**Step 6: Verify Slack notifications**

Check the configured Slack channel for the summary messages after each manual trigger.

**Step 7: Verify next morning**

The following day at 6 AM EST, check:
- `GET /api/cron/logs` shows two new entries (campaign_refresh + internal_scrape)
- Slack channel has summary notifications
- Campaign data on the frontend reflects fresh scrapes

---

## Files Summary

| File | Action |
|---|---|
| `campaign_manager/models.py` | **MODIFY** — add CronLog model |
| `campaign_manager/db.py` | **MODIFY** — import CronLog, add CRUD helpers |
| `campaign_manager/services/scheduler.py` | **CREATE** — scheduler init, job functions, Slack posting |
| `campaign_manager/blueprints/cron.py` | **CREATE** — API endpoints (status/logs/trigger/toggle) |
| `campaign_manager/__init__.py` | **MODIFY** — register cron blueprint, init scheduler |
| `campaign_manager/config.py` | **MODIFY** — add SCHEDULER_ENABLED, SLACK_CRON_CHANNEL, CRON_HOUR, CRON_MINUTE |
| `requirements.txt` | **MODIFY** — add APScheduler>=3.10.0 |
