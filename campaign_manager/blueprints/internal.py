"""Internal TikTok API endpoints.

Migrated from web_dashboard.py -- all routes converted to JSON API responses.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List
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

def _run_internal_scrape(hours: int, creators: List[str]):
    """Background scrape worker -- runs in a thread."""
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
        return

    try:
        end_dt = datetime.now(EST)
        start_dt = end_dt - timedelta(hours=hours)

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
                _internal_scrape_status["progress"] = f"Scraped {completed_count}/{total} accounts ({successful} ok, {failed} failed)"

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

        _internal_scrape_status.update({
            "running": False,
            "done": True,
            "progress": (
                f"Done: {successful}/{total} accounts, "
                f"{len(all_videos)} videos, "
                f"{len(songs_list)} unique sounds"
            ),
            "current_accounts": [],
        })
    except Exception as e:
        _internal_scrape_status.update({
            "running": False,
            "done": True,
            "progress": f"Error: {e}",
            "current_accounts": [],
        })


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
    """Start a background scrape of all internal creators."""
    if _internal_scrape_status.get("running"):
        return jsonify({"error": "A scrape is already running. Please wait."}), 409

    data = request.get_json(silent=True) or {}
    hours = int(data.get("hours", 48))
    creators = load_internal_creators()

    if not creators:
        return jsonify({"error": "No internal creators to scrape."}), 400

    # Launch scrape in background thread
    t = threading.Thread(target=_run_internal_scrape, args=(hours, creators), daemon=True)
    t.start()

    return jsonify({
        "ok": True,
        "message": f"Scrape started for {len(creators)} accounts (last {hours}h).",
        "creators_count": len(creators),
        "hours": hours,
    })


# -------------------------------------------------------------------
# 5. GET /api/internal/scrape/status  -- poll scrape progress
# -------------------------------------------------------------------
@internal_bp.get("/api/internal/scrape/status")
def scrape_status():
    """AJAX endpoint for polling scrape progress."""
    return jsonify(_internal_scrape_status)


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
