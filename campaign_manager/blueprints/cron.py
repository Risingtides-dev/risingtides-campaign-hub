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


@cron_bp.route("/api/cron/diag")
def cron_diag():
    """Diagnostic endpoint: test Apify connectivity and token."""
    import os
    from campaign_manager.config import Config

    env_token = os.environ.get("APIFY_API_TOKEN", "")
    config_token = Config.APIFY_API_TOKEN

    result = {
        "env_token_set": bool(env_token),
        "env_token_prefix": env_token[:8] + "..." if env_token else "",
        "config_token_set": bool(config_token),
        "config_token_prefix": config_token[:8] + "..." if config_token else "",
    }

    # Try a minimal Apify call
    try:
        from campaign_manager.services.apify_scraper import scrape_profiles
        videos = scrape_profiles(["charlidamelio"], results_per_page=1)
        result["apify_test"] = "ok"
        result["apify_videos_returned"] = len(videos)
    except Exception as e:
        result["apify_test"] = "failed"
        result["apify_error"] = str(e)

    return jsonify(result)
