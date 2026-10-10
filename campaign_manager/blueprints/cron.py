"""Cron scheduler API endpoints.

Provides status, logs, and manual trigger for the daily scraping scheduler.
"""
from __future__ import annotations

import threading
import logging

from flask import Blueprint, jsonify, request

from campaign_manager import db as _db
from campaign_manager.services.scheduler import (
    get_scheduler_status,
    trigger_job,
)

cron_bp = Blueprint("cron", __name__)
log = logging.getLogger(__name__)


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

    # Delegate campaign scrapes to the local node when configured (Railway's IP
    # is TikTok-blocked). This also stops stray POSTs here from launching a
    # doomed Railway-side scrape.
    if job_type == "campaign_refresh":
        from campaign_manager.services.local_agent import is_configured, dispatch_scrape
        if is_configured():
            try:
                log_id = _db.create_cron_log(job_type, status="queued")
            except Exception:
                log.exception("Could not record delegated cron request")
                return jsonify({"error": "Could not record cron request"}), 503
            # Once this durable state commits, a crash at any point around the
            # node POST is ambiguous. The janitor closes stale dispatching
            # receipts as unknown, never as "never started".
            try:
                if not _db.transition_cron_log(log_id, "queued", "dispatching"):
                    raise RuntimeError("delegated request receipt was already closed")
            except Exception:
                log.exception("Could not reserve local dispatch for %s", log_id)
                return jsonify({
                    "status": "failed", "ok": False, "log_id": log_id,
                    "error": "Could not reserve local dispatch",
                }), 503
            result = dispatch_scrape(None)
            node = result.get("node") or {}
            if result.get("ok") and node.get("started") is True:
                state, http_status = "delegated", 202
            elif result.get("ok") and node.get("started") is False:
                state, http_status = "skipped", 200
            elif result.get("outcome") == "unknown":
                state, http_status = "unknown", 502
            else:
                state, http_status = "failed", 502
            try:
                changed = _db.transition_cron_log(
                    log_id, "dispatching", state,
                    {"dispatch": result, "note": "Node acknowledgment only; reconcile node for scrape outcome"},
                )
                if not changed:
                    raise RuntimeError("delegated request receipt was already closed")
            except Exception:
                log.exception("Could not record delegated cron outcome for %s", log_id)
                return jsonify({
                    "status": "unknown", "ok": False, "log_id": log_id,
                    "error": "Local dispatch receipt update failed; reconcile before retry",
                }), 503
            return jsonify({
                "status": "delegated_to_local" if state == "delegated" else state,
                "log_id": log_id, **result,
            }), http_status

    # Persist the accepted request before returning. The background worker
    # changes this receipt to running, skipped, completed or failed; a process
    # recycle before it starts is reaped as an orphaned queued request.
    try:
        log_id = _db.create_cron_log(job_type, status="queued")
    except Exception:
        log.exception("Could not record manual cron request")
        return jsonify({"error": "Could not record cron request"}), 503

    try:
        thread = threading.Thread(
            target=trigger_job, args=(job_type, log_id), daemon=True
        )
        thread.start()
    except Exception:
        log.exception("Could not start manual cron worker")
        try:
            _db.transition_cron_log(
                log_id, "queued", "failed", {"error": "Could not start cron worker"}
            )
        except Exception:
            log.exception("Could not close manual cron request %s", log_id)
        return jsonify({"error": "Could not start cron worker", "log_id": log_id}), 503

    return jsonify({"status": "accepted", "job_type": job_type, "log_id": log_id}), 202


@cron_bp.route("/api/cron/toggle", methods=["POST"])
def cron_toggle():
    """Retired: per-worker mutation cannot control the fleet scheduler."""
    return jsonify({
        "error": "Scheduler toggle retired; configure SCHEDULER_ENABLED and restart the service",
    }), 410


@cron_bp.route("/api/cron/diag")
def cron_diag():
    """Retired: public diagnostics must not execute probes or expose config."""
    return jsonify({"error": "Public cron diagnostic retired"}), 410
