"""Internal TikTok API endpoints.

Migrated from web_dashboard.py -- all routes converted to JSON API responses.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

from flask import Blueprint, jsonify, request

from campaign_manager import db as _db

internal_bp = Blueprint("internal", __name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent          # campaign_manager/
PROJECT_ROOT = BASE_DIR.parent                             # project root

IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT") is not None
DATA_ROOT = Path("/app/data_volume") if IS_RAILWAY else BASE_DIR

INTERNAL_CREATORS_PATH = DATA_ROOT / "internal_creators.json"
INTERNAL_RESULTS_PATH = DATA_ROOT / "internal_last_scrape.json"
INTERNAL_CACHE_DIR = DATA_ROOT / "internal_cache"

# ---------------------------------------------------------------------------
# Background scrape state (module-level, shared by routes + worker thread)
# ---------------------------------------------------------------------------
_internal_scrape_status: Dict = {
    "running": False,
    "done": False,
    "progress": "",
    "accounts_total": 0,
    "accounts_completed": 0,
    "accounts_failed": 0,
    "videos_so_far": 0,
    "current_accounts": [],
    "log": [],
}

# Job registry for the per-group trigger endpoint (RTA-16).
#
# _jobs maps job_id -> {group, started_at, state, progress: {n,m}, last_log, error}
# _current_job_by_group maps group slug -> active job_id (debounce key).
#
# In-memory only. Railway dyno recycles drop in-flight scrapes; job state
# resets to empty after a restart. Acceptable for now — the underlying
# scrape worker is already in-process state and shares the same limitation.
# A persistent job store (Redis/DB row) is the upgrade path if it becomes
# a real problem.
#
# RTA-46: terminal entries (state in {"done", "error"}) are pruned by
# `_prune_jobs` whenever a new job is inserted. Without pruning, the dict
# grows one entry per scrape for the lifetime of the dyno.
_jobs: Dict[str, Dict] = {}
_current_job_by_group: Dict[str, str] = {}
_jobs_lock = threading.Lock()

# Default 24-hour retention for terminal (done/error) job entries. Tuneable
# via the ``INTERNAL_JOBS_TTL_HOURS`` env var. Bounds mirror the defensive
# pattern used by RTA-10's ``NOTION_SYNC_INTERVAL_MINUTES``: a typo or
# out-of-range value falls back to the default rather than disabling
# pruning entirely (which would reintroduce the unbounded-growth bug).
INTERNAL_JOBS_DEFAULT_TTL_HOURS = 24
INTERNAL_JOBS_MIN_TTL_HOURS = 1
INTERNAL_JOBS_MAX_TTL_HOURS = 720  # 30 days


def get_internal_jobs_ttl_hours() -> int:
    """Resolve the _jobs registry TTL from the env var, clamped to bounds.

    Bounds: ``INTERNAL_JOBS_MIN_TTL_HOURS`` <= n <= ``INTERNAL_JOBS_MAX_TTL_HOURS``.
    Falls back to the default on missing / unparseable / out-of-bounds values.
    """
    raw = os.environ.get("INTERNAL_JOBS_TTL_HOURS", "")
    if not raw:
        return INTERNAL_JOBS_DEFAULT_TTL_HOURS
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return INTERNAL_JOBS_DEFAULT_TTL_HOURS
    if n < INTERNAL_JOBS_MIN_TTL_HOURS or n > INTERNAL_JOBS_MAX_TTL_HOURS:
        return INTERNAL_JOBS_DEFAULT_TTL_HOURS
    return n


def _prune_jobs() -> int:
    """Sweep terminal _jobs entries older than the TTL. Returns count pruned.

    MUST be called with ``_jobs_lock`` held by the caller. This keeps the
    prune + insert in ``scrape_start`` inside one critical section, which
    is the only correctness-relevant ordering. Tests acquire the lock
    explicitly before calling.

    Pruning rules:
      - state == "running": NEVER pruned. The worker thread is still
        writing to the dict; its ``_current_job_by_group`` pointer is
        also live (the debounce check reads from it).
      - state in {"done", "error"}: pruned iff ``started_at`` is older
        than ``get_internal_jobs_ttl_hours()`` hours. A missing or
        unparseable ``started_at`` on a terminal job is treated as
        ancient and pruned (defensive cleanup; this shape should never
        occur in practice).

    Idempotent: re-running with no eligible entries is a no-op.
    """
    from datetime import timedelta

    ttl_hours = get_internal_jobs_ttl_hours()
    cutoff = datetime.now(EST) - timedelta(hours=ttl_hours)

    to_drop: List[str] = []
    for job_id, job in _jobs.items():
        state = job.get("state", "running")
        if state == "running":
            continue
        started = job.get("started_at")
        if not started or not isinstance(started, str):
            to_drop.append(job_id)
            continue
        try:
            started_dt = datetime.fromisoformat(started)
        except ValueError:
            to_drop.append(job_id)
            continue
        if started_dt < cutoff:
            to_drop.append(job_id)

    for job_id in to_drop:
        _jobs.pop(job_id, None)
        # Defensive: clear any stale group->job pointer that still
        # references a pruned entry. In practice _clear_current_job runs
        # when the worker finishes, but if a worker died mid-flight the
        # pointer could linger past the TTL alongside its terminal entry.
        for group, gid in list(_current_job_by_group.items()):
            if gid == job_id:
                _current_job_by_group.pop(group, None)

    return len(to_drop)


def _job_snapshot(job_id: str) -> Optional[Dict]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return {
            "job_id": job_id,
            "group": job.get("group"),
            "started_at": job.get("started_at"),
            "state": job.get("state", "running"),
            "progress": dict(job.get("progress") or {"n": 0, "m": 0}),
            "last_log": job.get("last_log", ""),
            "error": job.get("error"),
        }


def _update_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(fields)


def _clear_current_job(group: str, job_id: str) -> None:
    """Clear group->job mapping if it still points at this job."""
    with _jobs_lock:
        if _current_job_by_group.get(group) == job_id:
            _current_job_by_group.pop(group, None)

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_internal_creators() -> List[str]:
    if _db.is_active():
        return _db.get_internal_creators()
    if INTERNAL_CREATORS_PATH.exists():
        try:
            return json.loads(INTERNAL_CREATORS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_internal_creators(creators: List[str]) -> None:
    if _db.is_active():
        _db.save_internal_creators(creators)
        return
    INTERNAL_CREATORS_PATH.write_text(
        json.dumps(sorted(set(creators)), indent=2), encoding="utf-8"
    )


def load_internal_results() -> Dict:
    if _db.is_active():
        return _db.get_internal_results()
    if INTERNAL_RESULTS_PATH.exists():
        try:
            return json.loads(INTERNAL_RESULTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_internal_results(data: Dict) -> None:
    if _db.is_active():
        _db.save_internal_results(data)
        return
    INTERNAL_RESULTS_PATH.write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )


# -- Per-account 30-day rolling cache --

def _account_cache_path(username: str) -> Path:
    return INTERNAL_CACHE_DIR / f"{username.lower()}.json"


def load_account_cache(username: str) -> List[Dict]:
    if _db.is_active():
        return _db.get_internal_cache(username)
    path = _account_cache_path(username)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_account_cache(username: str, videos: List[Dict]) -> None:
    if _db.is_active():
        # In DB mode, use merge_into_cache instead
        return
    INTERNAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _account_cache_path(username)
    path.write_text(json.dumps(videos, indent=2, default=str), encoding="utf-8")


def merge_into_cache(username: str, new_videos: List[Dict]) -> List[Dict]:
    """Merge new videos into account cache, dedupe by URL, prune older than 30 days."""
    if _db.is_active():
        return _db.merge_internal_cache(username, new_videos)

    from datetime import timedelta
    cutoff = datetime.now(EST) - timedelta(days=30)

    existing = load_account_cache(username)
    seen_urls = {v.get("url") for v in existing if v.get("url")}
    for v in new_videos:
        url = v.get("url", "")
        if url and url not in seen_urls:
            existing.append(v)
            seen_urls.add(url)

    # Prune videos older than 30 days
    pruned = []
    for v in existing:
        video_dt = None
        ts = v.get("timestamp")
        if ts and isinstance(ts, str):
            try:
                video_dt = datetime.fromisoformat(ts)
            except Exception:
                pass
        if not video_dt:
            upload = v.get("upload_date", "")
            if upload and len(upload) == 8:
                try:
                    video_dt = datetime.strptime(upload, "%Y%m%d")
                except Exception:
                    pass
        # Keep if we can't determine date or if within 30 days
        if video_dt is None or video_dt >= cutoff:
            pruned.append(v)

    save_account_cache(username, pruned)
    return pruned


# ---------------------------------------------------------------------------
# Background scrape worker
# ---------------------------------------------------------------------------

def _run_internal_scrape(hours: int, creators: List[str], *,
                         start_date_str: str = "", end_date_str: str = "",
                         job_id: Optional[str] = None,
                         group_slug: Optional[str] = None):
    """Background scrape worker -- runs in a thread.

    When start_date_str / end_date_str are provided (YYYY-MM-DD), they
    override the hours-based window. This lets the UI request a specific
    date range like "March 15 to April 15".

    When job_id is provided, the worker also writes progress + state into
    the _jobs registry so the /api/internal/scrape/start polling shape
    (state, progress: {n,m}, last_log) reflects real progress (RTA-16).
    """
    def _bump(state: str, *, n: Optional[int] = None, m: Optional[int] = None,
              last_log: Optional[str] = None, error: Optional[str] = None) -> None:
        if not job_id:
            return
        fields: Dict = {"state": state}
        if n is not None or m is not None:
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job:
                    prog = dict(job.get("progress") or {"n": 0, "m": 0})
                    if n is not None:
                        prog["n"] = n
                    if m is not None:
                        prog["m"] = m
                    fields["progress"] = prog
        if last_log is not None:
            fields["last_log"] = last_log
        if error is not None:
            fields["error"] = error
        _update_job(job_id, **fields)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from collections import defaultdict
    from datetime import timedelta

    global _internal_scrape_status
    total = len(creators)
    _internal_scrape_status = {
        "running": True,
        "done": False,
        "progress": "Starting...",
        "accounts_total": total,
        "accounts_completed": 0,
        "accounts_failed": 0,
        "videos_so_far": 0,
        "current_accounts": [],
        "log": [],
    }
    _bump("running", n=0, m=total, last_log="Starting...")

    # Thread-safe set for tracking in-flight accounts
    _inflight_lock = threading.Lock()
    _inflight: set = set()

    def _add_inflight(account: str):
        with _inflight_lock:
            _inflight.add(account)
            _internal_scrape_status["current_accounts"] = sorted(_inflight)

    def _remove_inflight(account: str):
        with _inflight_lock:
            _inflight.discard(account)
            _internal_scrape_status["current_accounts"] = sorted(_inflight)

    utils_dir = str(PROJECT_ROOT / "src" / "utils")
    if utils_dir not in sys.path:
        sys.path.insert(0, utils_dir)

    try:
        from get_post_links_by_song import scrape_account_videos, normalize_song_key, ScrapeError
    except ImportError as e:
        _internal_scrape_status = {
            "running": False, "done": True, "progress": f"Import error: {e}",
            "accounts_total": total, "accounts_completed": 0, "accounts_failed": 0,
            "videos_so_far": 0, "current_accounts": [], "log": [],
        }
        _bump("error", last_log=f"Import error: {e}", error=str(e))
        if group_slug and job_id:
            _clear_current_job(group_slug, job_id)
        return

    try:
        # Use explicit date range if provided, otherwise fall back to hours
        if start_date_str:
            try:
                start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=EST)
            except ValueError:
                start_dt = datetime.now(EST) - timedelta(hours=hours)
        else:
            start_dt = datetime.now(EST) - timedelta(hours=hours)

        if end_date_str:
            try:
                # End of the specified day
                end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, tzinfo=EST
                )
            except ValueError:
                end_dt = datetime.now(EST)
        else:
            end_dt = datetime.now(EST)

        all_videos: List[Dict] = []
        successful = 0
        failed = 0

        def _scrape_one(account):
            _add_inflight(account)
            try:
                videos = scrape_account_videos(account, start_datetime=start_dt, end_datetime=end_dt, limit=500)
                return account, videos or [], None
            except ScrapeError as e:
                return account, [], str(e)
            except Exception as e:
                return account, [], f"Unexpected error: {e}"

        completed_count = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_scrape_one, c): c for c in creators}
            for future in as_completed(futures):
                account, videos, error = future.result()
                _remove_inflight(account)
                completed_count += 1
                video_count = len(videos)
                if error:
                    failed += 1
                    _internal_scrape_status["log"].append({
                        "username": account,
                        "status": "failed",
                        "video_count": 0,
                        "error": error,
                    })
                else:
                    # Merge into per-account cache
                    serializable = []
                    for v in videos:
                        sv = {
                            "url": v.get("url", ""),
                            "song": v.get("song", ""),
                            "artist": v.get("artist", ""),
                            "account": v.get("account", ""),
                            "views": v.get("views", 0),
                            "likes": v.get("likes", 0),
                            "upload_date": v.get("upload_date", ""),
                            "timestamp": v.get("timestamp").isoformat() if isinstance(v.get("timestamp"), datetime) else str(v.get("timestamp", "")),
                        }
                        serializable.append(sv)
                    merge_into_cache(account.lstrip("@"), serializable)
                    all_videos.extend(serializable)
                    successful += 1
                    _internal_scrape_status["log"].append({
                        "username": account,
                        "status": "ok",
                        "video_count": video_count,
                    })

                _internal_scrape_status["accounts_completed"] = completed_count
                _internal_scrape_status["accounts_failed"] = failed
                _internal_scrape_status["videos_so_far"] = len(all_videos)
                progress_str = f"Scraped {completed_count}/{total} accounts ({successful} ok, {failed} failed)"
                _internal_scrape_status["progress"] = progress_str
                _bump(
                    "running",
                    n=completed_count,
                    m=total,
                    last_log=f"{account}: {'ok' if not error else 'failed'} ({video_count} videos)",
                )

        # Group by song
        songs_dict = defaultdict(lambda: {
            "song": "", "artist": "", "videos": [], "accounts": set(),
            "total_views": 0, "total_likes": 0,
        })

        for video in all_videos:
            song_key = normalize_song_key(video.get("song", ""), video.get("artist", ""))
            entry = songs_dict[song_key]
            entry["song"] = video.get("song", "Unknown")
            entry["artist"] = video.get("artist", "Unknown")
            entry["videos"].append({
                "url": video.get("url", ""),
                "account": video.get("account", ""),
                "views": video.get("views", 0),
                "likes": video.get("likes", 0),
                "upload_date": video.get("upload_date", ""),
            })
            entry["accounts"].add(video.get("account", ""))
            entry["total_views"] += video.get("views", 0)
            entry["total_likes"] += video.get("likes", 0)

        songs_list = []
        for key, data in sorted(songs_dict.items(), key=lambda x: x[1]["total_views"], reverse=True):
            data["accounts"] = sorted(data["accounts"])
            data["videos"].sort(key=lambda v: v.get("views", 0), reverse=True)
            data["key"] = key
            songs_list.append(data)

        results = {
            "scraped_at": datetime.now(EST).strftime("%Y-%m-%dT%H:%M:%S"),
            "hours": hours,
            "start_dt": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "end_dt": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "accounts_total": total,
            "accounts_successful": successful,
            "accounts_failed": failed,
            "total_videos": len(all_videos),
            "total_videos_unfiltered": len(all_videos),
            "unique_songs": len(songs_list),
            "songs": songs_list,
        }
        save_internal_results(results)

        done_msg = (
            f"Done: {successful}/{total} accounts, "
            f"{len(all_videos)} videos, "
            f"{len(songs_list)} unique sounds"
        )
        _internal_scrape_status.update({
            "running": False,
            "done": True,
            "progress": done_msg,
            "current_accounts": [],
        })
        _bump("done", n=total, m=total, last_log=done_msg)
    except Exception as e:
        _internal_scrape_status.update({
            "running": False,
            "done": True,
            "progress": f"Error: {e}",
            "current_accounts": [],
        })
        _bump("error", last_log=f"Error: {e}", error=str(e))
    finally:
        if group_slug and job_id:
            _clear_current_job(group_slug, job_id)


# ===================================================================
# Routes
# ===================================================================

# -------------------------------------------------------------------
# 1. GET /api/internal/creators  -- list internal creators with stats
# -------------------------------------------------------------------
@internal_bp.get("/api/internal/creators")
def list_creators():
    """List all internal creators with per-creator stats from cache."""
    creators = load_internal_creators()
    creator_list = []
    for c in creators:
        cached = load_account_cache(c)
        creator_list.append({
            "username": c,
            "total_videos": len(cached),
            "total_views": sum(v.get("views", 0) for v in cached),
        })
    return jsonify(creator_list)


# -------------------------------------------------------------------
# 2. POST /api/internal/creators  -- add creators
# -------------------------------------------------------------------
@internal_bp.post("/api/internal/creators")
def add_creators():
    """Add one or more internal creators by username."""
    data = request.get_json(silent=True) or {}
    raw = (data.get("username") or "").strip()
    if not raw:
        return jsonify({"error": "Username is required."}), 400

    usernames = re.split(r"[\n,]+", raw)
    creators = load_internal_creators()
    existing = {c.lower() for c in creators}
    added = []
    for u in usernames:
        u = u.strip().lstrip("@").strip()
        if u and u.lower() not in existing:
            creators.append(u)
            existing.add(u.lower())
            added.append(u)

    if added:
        save_internal_creators(creators)
        return jsonify({
            "ok": True,
            "added": added,
            "message": f"Added {len(added)} creator(s): {', '.join('@' + a for a in added)}",
        }), 201
    else:
        return jsonify({"error": "No new creators to add (already exist or empty)."}), 409


# -------------------------------------------------------------------
# 3. DELETE /api/internal/creators/<username>  -- remove creator
# -------------------------------------------------------------------
@internal_bp.delete("/api/internal/creators/<username>")
def remove_creator(username: str):
    """Remove an internal creator by username."""
    creators = load_internal_creators()
    original_len = len(creators)
    creators = [c for c in creators if c.lower() != username.lower()]

    if len(creators) == original_len:
        return jsonify({"error": f"@{username} not found."}), 404

    save_internal_creators(creators)
    return jsonify({"ok": True, "message": f"Removed @{username}"})


# -------------------------------------------------------------------
# 4. POST /api/internal/scrape  -- trigger background scrape
# -------------------------------------------------------------------
@internal_bp.post("/api/internal/scrape")
def trigger_scrape():
    """Start a background scrape of internal creators.

    Accepts optional filters to scope the scrape:
      - group: slug of a creator group (scrapes only that group's members)
      - username: single creator username (scrapes just one account)
      - hours: lookback window (default 48) -- used when start_date/end_date not set
      - start_date: explicit start date (YYYY-MM-DD), overrides hours
      - end_date: explicit end date (YYYY-MM-DD), defaults to now
    """
    if _internal_scrape_status.get("running"):
        return jsonify({"error": "A scrape is already running. Please wait."}), 409

    data = request.get_json(silent=True) or {}
    hours = int(data.get("hours", 48))

    # Determine which creators to scrape
    group_slug = (data.get("group") or "").strip()
    single_username = (data.get("username") or "").strip().lstrip("@")

    if single_username:
        creators = [single_username]
        scope_label = f"@{single_username}"
    elif group_slug:
        if _db.is_active():
            group = _db.get_internal_group(group_slug)
            if not group:
                return jsonify({"error": f"Group '{group_slug}' not found."}), 404
            creators = _db.get_group_members(group["id"])
            if not creators:
                return jsonify({"error": f"Group '{group_slug}' has no members."}), 400
            scope_label = f"group:{group_slug} ({len(creators)} accounts)"
        else:
            return jsonify({"error": "Groups require database. Use 'hours' for flat scrape."}), 503
    else:
        creators = load_internal_creators()
        scope_label = f"all ({len(creators)} accounts)"

    if not creators:
        return jsonify({"error": "No creators to scrape."}), 400

    # Parse optional date range
    start_date_str = (data.get("start_date") or "").strip()
    end_date_str = (data.get("end_date") or "").strip()

    # Launch scrape in background thread
    t = threading.Thread(
        target=_run_internal_scrape,
        args=(hours, creators),
        kwargs={"start_date_str": start_date_str, "end_date_str": end_date_str},
        daemon=True,
    )
    t.start()

    return jsonify({
        "ok": True,
        "message": f"Scrape started for {scope_label} (last {hours}h).",
        "creators_count": len(creators),
        "hours": hours,
        "group": group_slug or None,
        "username": single_username or None,
        "start_date": start_date_str or None,
        "end_date": end_date_str or None,
    })


# -------------------------------------------------------------------
# 5. GET /api/internal/scrape/status  -- poll scrape progress
# -------------------------------------------------------------------
@internal_bp.get("/api/internal/scrape/status")
def scrape_status():
    """Poll scrape progress.

    Two shapes:
      - No ?job_id -- legacy global shape (used by existing UI).
      - ?job_id=<id> -- per-job shape for the /scrape/start trigger
        endpoint (RTA-16): {state, progress: {n,m}, last_log, ...}.
    """
    job_id = (request.args.get("job_id") or "").strip()
    if job_id:
        snap = _job_snapshot(job_id)
        if not snap:
            return jsonify({"error": f"job_id '{job_id}' not found"}), 404
        return jsonify(snap)
    return jsonify(_internal_scrape_status)


# -------------------------------------------------------------------
# 5b. POST /api/internal/scrape/start  -- trigger per-group scrape (RTA-16)
# -------------------------------------------------------------------
@internal_bp.post("/api/internal/scrape/start")
def scrape_start():
    """Kick off a scrape for a single creator group and return a job id.

    Body: {"group": "<slug>", "hours": 168}
    Response: {"job_id": "...", "started_at": "<iso>"}

    Debounce: if a job is already running for the same group, returns
    the existing job id rather than spawning a second worker.
    """
    err = _require_db()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    group_slug = (data.get("group") or "").strip().lower()
    if not group_slug:
        return jsonify({"error": "group is required"}), 400

    try:
        hours = int(data.get("hours", 168))
    except (TypeError, ValueError):
        return jsonify({"error": "hours must be an integer"}), 400

    group = _db.get_internal_group(group_slug)
    if not group:
        return jsonify({"error": f"Group '{group_slug}' not found."}), 404

    members = _db.get_group_members(group["id"])
    if not members:
        return jsonify({"error": f"Group '{group_slug}' has no members."}), 400

    start_date_str = (data.get("start_date") or "").strip()
    end_date_str = (data.get("end_date") or "").strip()

    # Debounce: if a job for this group is still running, return it.
    with _jobs_lock:
        existing_id = _current_job_by_group.get(group_slug)
        if existing_id:
            existing = _jobs.get(existing_id)
            if existing and existing.get("state") == "running":
                return jsonify({
                    "job_id": existing_id,
                    "started_at": existing.get("started_at"),
                    "debounced": True,
                })
            # Stale pointer (state moved to done/error). Clear it.
            _current_job_by_group.pop(group_slug, None)

        # RTA-46: sweep terminal entries older than the TTL before
        # inserting a new job, so the dict can't grow unboundedly across
        # the dyno's lifetime.
        _prune_jobs()

        job_id = uuid.uuid4().hex
        started_at = datetime.now(EST).isoformat()
        _jobs[job_id] = {
            "group": group_slug,
            "started_at": started_at,
            "state": "running",
            "progress": {"n": 0, "m": len(members)},
            "last_log": "",
            "error": None,
        }
        _current_job_by_group[group_slug] = job_id

    # Railway dyno recycles can kill in-flight scrapes; job state then
    # stops updating and clients should treat a stalled "running" job
    # as lost after a sensible timeout. Persistent queueing (Redis/DB
    # row) is the upgrade path if this becomes a real problem.
    t = threading.Thread(
        target=_run_internal_scrape,
        args=(hours, members),
        kwargs={
            "start_date_str": start_date_str,
            "end_date_str": end_date_str,
            "job_id": job_id,
            "group_slug": group_slug,
        },
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id, "started_at": started_at}), 202


# -------------------------------------------------------------------
# 6. GET /api/internal/creator/<username>  -- creator detail
# -------------------------------------------------------------------
@internal_bp.get("/api/internal/creator/<username>")
def creator_detail(username: str):
    """Get detailed stats for a single internal creator."""
    creators = load_internal_creators()
    if username.lower() not in {c.lower() for c in creators}:
        return jsonify({"error": f"@{username} not found in internal creators."}), 404

    # Load all cached videos for this account
    cached = load_account_cache(username)

    # Group by song
    from collections import defaultdict
    songs_dict = defaultdict(lambda: {
        "song": "", "artist": "", "videos": [], "total_views": 0, "total_likes": 0,
    })

    for v in cached:
        key = f"{(v.get('song') or 'Unknown').strip()} - {(v.get('artist') or 'Unknown').strip()}"
        entry = songs_dict[key]
        entry["song"] = v.get("song", "Unknown")
        entry["artist"] = v.get("artist", "Unknown")
        entry["videos"].append(v)
        entry["total_views"] += v.get("views", 0)
        entry["total_likes"] += v.get("likes", 0)

    songs_list = []
    for key, data in sorted(songs_dict.items(), key=lambda x: x[1]["total_views"], reverse=True):
        data["videos"].sort(key=lambda v: v.get("views", 0), reverse=True)
        data["key"] = key
        songs_list.append(data)

    total_views = sum(v.get("views", 0) for v in cached)
    total_likes = sum(v.get("likes", 0) for v in cached)

    return jsonify({
        "username": username,
        "songs": songs_list,
        "total_videos": len(cached),
        "total_views": total_views,
        "total_likes": total_likes,
    })


# -------------------------------------------------------------------
# 7. GET /api/internal/results  -- latest scrape results
# -------------------------------------------------------------------
@internal_bp.get("/api/internal/results")
def scrape_results():
    """Return the latest internal scrape results."""
    results = load_internal_results()
    return jsonify(results)


# -------------------------------------------------------------------
# 8. POST /api/internal/results  -- upload local scrape results
# -------------------------------------------------------------------
@internal_bp.post("/api/internal/results")
def upload_results():
    """Accept scrape results pushed from a local machine."""
    data = request.get_json(silent=True)
    if not data or "songs" not in data:
        return jsonify({"error": "Invalid results payload."}), 400
    save_internal_results(data)
    return jsonify({"ok": True, "message": f"Saved {data.get('total_videos', 0)} videos, {data.get('unique_songs', 0)} songs."}), 201


# ===================================================================
# Creator Groups -- bucket internal creators for per-group stats.
# All routes require the database to be active; JSON fallback is not
# supported for groups (keeps the data model simple).
# ===================================================================

def _require_db():
    if not _db.is_active():
        return jsonify({"error": "Database not configured. Groups require Postgres."}), 503
    return None


# -------------------------------------------------------------------
# 9. GET /api/internal/groups  -- list all groups with member counts
# -------------------------------------------------------------------
@internal_bp.get("/api/internal/groups")
def list_groups():
    err = _require_db()
    if err:
        return err
    return jsonify(_db.list_internal_groups())


# -------------------------------------------------------------------
# 10. POST /api/internal/groups  -- create a group
# -------------------------------------------------------------------
@internal_bp.post("/api/internal/groups")
def create_group():
    err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    slug = (data.get("slug") or "").strip().lower()
    title = (data.get("title") or "").strip()
    kind = (data.get("kind") or "custom").strip().lower()
    sort_order = int(data.get("sort_order") or 0)

    if not slug or not title:
        return jsonify({"error": "slug and title are required"}), 400

    group = _db.create_internal_group(slug, title, kind=kind, sort_order=sort_order)
    if not group:
        return jsonify({"error": f"Group '{slug}' already exists or is invalid"}), 409
    return jsonify(group), 201


# -------------------------------------------------------------------
# 11. GET /api/internal/groups/<identifier>  -- group detail + members
# -------------------------------------------------------------------
@internal_bp.get("/api/internal/groups/<identifier>")
def get_group(identifier: str):
    err = _require_db()
    if err:
        return err
    group = _db.get_internal_group(identifier)
    if not group:
        return jsonify({"error": "Group not found"}), 404
    members = _db.get_group_members(group["id"])
    return jsonify({**group, "members": members})


# -------------------------------------------------------------------
# 12. PATCH /api/internal/groups/<id>  -- rename / re-kind / reorder
# -------------------------------------------------------------------
@internal_bp.patch("/api/internal/groups/<int:group_id>")
def patch_group(group_id: int):
    err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    updated = _db.update_internal_group(group_id, data)
    if not updated:
        return jsonify({"error": "Group not found"}), 404
    return jsonify(updated)


# -------------------------------------------------------------------
# 13. DELETE /api/internal/groups/<id>  -- remove a group
# -------------------------------------------------------------------
@internal_bp.delete("/api/internal/groups/<int:group_id>")
def delete_group(group_id: int):
    err = _require_db()
    if err:
        return err
    if not _db.delete_internal_group(group_id):
        return jsonify({"error": "Group not found"}), 404
    return jsonify({"ok": True})


# -------------------------------------------------------------------
# 14. POST /api/internal/groups/<id>/members  -- add members
# -------------------------------------------------------------------
@internal_bp.post("/api/internal/groups/<int:group_id>/members")
def add_members(group_id: int):
    err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    usernames = data.get("usernames") or data.get("username") or []
    if isinstance(usernames, str):
        usernames = re.split(r"[\n,]+", usernames)
    if not usernames:
        return jsonify({"error": "usernames is required (list or comma/newline separated string)"}), 400

    added = _db.add_group_members(group_id, usernames)
    return jsonify({
        "ok": True,
        "group_id": group_id,
        "added": added,
        "skipped": [u.strip().lstrip("@") for u in usernames
                    if u.strip().lstrip("@").lower() not in {a.lower() for a in added}],
    }), 201


# -------------------------------------------------------------------
# 15. DELETE /api/internal/groups/<id>/members/<username>
# -------------------------------------------------------------------
@internal_bp.delete("/api/internal/groups/<int:group_id>/members/<username>")
def remove_member(group_id: int, username: str):
    err = _require_db()
    if err:
        return err
    if not _db.remove_group_member(group_id, username):
        return jsonify({"error": f"@{username} is not a member of group {group_id}"}), 404
    return jsonify({"ok": True})


# -------------------------------------------------------------------
# 16. GET /api/internal/groups/<id>/stats  -- aggregate group stats
# -------------------------------------------------------------------
@internal_bp.get("/api/internal/groups/<identifier>/stats")
def group_stats(identifier: str):
    err = _require_db()
    if err:
        return err
    group = _db.get_internal_group(identifier)
    if not group:
        return jsonify({"error": "Group not found"}), 404
    days = int(request.args.get("days", 30))
    return jsonify(_db.get_group_stats(group["id"], days=days))


# -------------------------------------------------------------------
# 17. GET /api/internal/creators/<username>/stats  -- per-creator stats
# -------------------------------------------------------------------
@internal_bp.get("/api/internal/creators/<username>/stats")
def creator_stats(username: str):
    err = _require_db()
    if err:
        return err
    days = int(request.args.get("days", 30))
    return jsonify(_db.get_creator_stats(username, days=days))
