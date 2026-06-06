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
    """Diagnostic endpoint: yt-dlp version + TikTok scrape test.

    Useful for confirming a deploy actually picked up the pinned yt-dlp
    version and that TikTok isn't soft-blocking from this IP. Hit this
    before debugging "why does cron return 0 matches" — if scrape_test_*
    is empty, it's TikTok-side, not the matcher.
    """
    import os
    import subprocess
    import sys

    result: dict = {
        "yt_dlp_cookies_file_set": bool(os.environ.get("TIKTOK_COOKIES_FILE")),
        "yt_dlp_cookies_file_exists": os.path.exists(os.environ.get("TIKTOK_COOKIES_FILE", "")),
        "yt_dlp_proxy_set": bool(os.environ.get("TIKTOK_PROXY")),
    }

    # yt-dlp version
    try:
        v = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        result["yt_dlp_version"] = (v.stdout or v.stderr or "").strip()
    except Exception as e:
        result["yt_dlp_version_error"] = str(e)

    # Available impersonate targets (so we know what TIKTOK_IMPERSONATE_TARGET
    # values are valid on this deploy)
    try:
        t = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--list-impersonate-targets"],
            capture_output=True, text=True, timeout=15,
        )
        out = (t.stdout or "")[:2000]
        result["impersonate_targets"] = out.strip().split("\n")[:30]
    except Exception as e:
        result["impersonate_targets_error"] = str(e)

    result["tiktok_impersonate_env"] = os.environ.get("TIKTOK_IMPERSONATE", "0")
    result["tiktok_impersonate_target_env"] = os.environ.get("TIKTOK_IMPERSONATE_TARGET", "")

    # CAMP-96 hardening: the EXPENSIVE live tests below (a yt-dlp scrape + a
    # proxy HTML fetch) now run only when explicitly requested with ?run=1.
    # A plain GET used to fire them on every hit — anyone (this endpoint is
    # unauthenticated) could loop it to burn scraper/proxy budget, and the
    # scrape_test_stderr_tail can leak proxy hostnames / auth-failure details.
    # The cheap config/version diagnostics above stay always-on for ops; pass
    # ?run=1 for the full live test (and only then is the stderr tail included).
    run_live = request.args.get("run") in ("1", "true", "yes")
    if not run_live:
        result["live_tests"] = "skipped — append ?run=1 to run the yt-dlp scrape + enrich tests"
        return jsonify(result)

    # Live scrape test against a known-public TikTok account
    try:
        from src.scrapers.yt_dlp_runner import build_tiktok_cmd, diagnose_failure
        test_url = "https://www.tiktok.com/@tiktok"
        cmd = build_tiktok_cmd(test_url, flat_playlist=True, dump_json=True, playlist_end=3)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        stdout_lines = [ln for ln in (proc.stdout or "").strip().split("\n") if ln.strip()]
        result["scrape_test_target"] = test_url
        result["scrape_test_returncode"] = proc.returncode
        result["scrape_test_video_count"] = len(stdout_lines)
        result["scrape_test_stderr_tail"] = (proc.stderr or "")[-400:]
        if proc.returncode != 0 or not stdout_lines:
            result["scrape_test_diagnosis"] = diagnose_failure(proc.stderr)
    except Exception as e:
        result["scrape_test_error"] = str(e)

    # Sound-ID enrichment test — fetches a known TikTok video's HTML through
    # TIKTOK_PROXY and verifies extract_sound_meta_from_video can pull the
    # music.id field. If yt-dlp works but this fails, the proxy is rejecting
    # plain `requests` calls (no TLS fingerprinting) and we need to switch
    # the enrichment fetch to curl_cffi or pass through a different exit.
    try:
        from src.scrapers.master_tracker import extract_sound_meta_from_video
        enrich_url = "https://www.tiktok.com/@narravis/video/7639385764266036502"
        expected_sid = "7623218788412082177"
        sid, title = extract_sound_meta_from_video(enrich_url, timeout=20)
        result["enrich_test_target"] = enrich_url
        result["enrich_test_expected_sid"] = expected_sid
        result["enrich_test_extracted_sid"] = sid
        result["enrich_test_extracted_title"] = title
        result["enrich_test_match"] = (sid == expected_sid)
    except Exception as e:
        result["enrich_test_error"] = str(e)

    return jsonify(result)
