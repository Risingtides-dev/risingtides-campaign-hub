"""Scrape Tasks API — backs the dedicated tab where the team tracks
which scraped video links have been copied into Cobrand.

Default organization: by campaign. The queue groups untracked matched
videos under their campaign so the person doing the work can knock out
one campaign at a time.

Endpoints:
    GET  /api/scrape-tasks/queue        — untracked videos grouped by campaign
    GET  /api/scrape-tasks/health       — last cron run status + degraded flag
    POST /api/scrape-tasks/mark-tracked — mark videos as tracked (bulk)
    POST /api/scrape-tasks/unmark-tracked — undo (in case of mis-click)
    POST /api/scrape-tasks/mark-campaign-tracked — bulk mark every untracked
         video for a single campaign in one click
    POST /api/scrape-tasks/dismiss       — hide false-positive matches so they
         stop counting toward totals (bulk)
    POST /api/scrape-tasks/undismiss     — undo a dismissal (bulk)
"""
from __future__ import annotations

from datetime import datetime
from flask import Blueprint, jsonify, request

from campaign_manager import db as _db
from sqlalchemy import or_

from campaign_manager.models import MatchedVideo, Campaign
from campaign_manager.utils.helpers import video_posted_before_start

scrape_tasks_bp = Blueprint("scrape_tasks", __name__)


# ── On-demand scrape trigger (CAMP-24) ───────────────────────────────────
@scrape_tasks_bp.post("/api/scrape-tasks/trigger")
def trigger_scrape_task():
    """Fire a campaign refresh on demand (instead of waiting for the cron).

    Body:
      {"all_active": true}            -> refresh every active campaign
      {"campaign_id": "<slug>"}       -> refresh just that campaign
      {"slugs": ["a", "b"]}           -> refresh those campaigns

    Returns {job_id, state, scope}. Debounced: a second trigger while one is
    running returns the in-flight job (avoids doubling the scraper load).
    """
    data = request.get_json(silent=True) or {}
    only_slugs = None
    if not data.get("all_active"):
        if data.get("campaign_id"):
            only_slugs = [str(data["campaign_id"])]
        elif isinstance(data.get("slugs"), list) and data["slugs"]:
            only_slugs = [str(s) for s in data["slugs"]]
        else:
            return jsonify({
                "error": "Provide all_active:true, campaign_id:<slug>, or slugs:[...]"
            }), 400

    # Delegate to the local scraper node when configured — Railway's IP gets
    # TikTok-blocked, so the real scrape runs on the Mac (residential IP).
    from campaign_manager.services.local_agent import is_configured, dispatch_scrape
    if is_configured():
        result = dispatch_scrape(only_slugs)
        node = result.get("node") or {}
        # Shape it like the legacy job response so the frontend stays happy.
        result["state"] = "running" if result.get("ok") else "error"
        result["already_running"] = "already running" in (node.get("note") or "")
        return jsonify(result), (202 if result.get("ok") else 502)

    from campaign_manager.services.scrape_trigger import start_scrape
    job = start_scrape(only_slugs)
    return jsonify(job), (200 if job.get("already_running") else 202)


@scrape_tasks_bp.get("/api/scrape-tasks/trigger/status")
def trigger_scrape_status():
    """Poll a trigger job: /api/scrape-tasks/trigger/status?job_id=<id>."""
    from campaign_manager.services.scrape_trigger import job_status, active_job

    job_id = request.args.get("job_id", "")
    if not job_id:
        # No id -> return the active job if there is one, else idle.
        active = active_job()
        return jsonify(active or {"state": "idle"})
    status = job_status(job_id)
    if status is None:
        return jsonify({"error": "Unknown job_id"}), 404
    return jsonify(status)


@scrape_tasks_bp.get("/api/scrape-tasks/queue")
def queue():
    """Return untracked matched videos grouped by campaign.

    Response shape:
        {
          "total_untracked": 47,
          "campaigns": [
            {
              "slug": "...",
              "title": "Stella Lefty - I Know I Know R2",
              "artist": "Stella Lefty",
              "match_strategy": "strict",
              "untracked_count": 12,
              "videos": [
                {
                  "id": 1234,
                  "url": "...",
                  "account": "@ellie_creator",
                  "views": 24500,
                  "likes": 1200,
                  "match_strategy": "sound_id",
                  "first_seen_at": "2026-05-06T06:00:00",
                  "timestamp": "2026-05-05T14:32:00"
                },
                ...
              ]
            },
            ...
          ]
        }

    Query params:
        ?campaign=<slug>  — filter to single campaign (still nested in same shape)
        ?since=YYYY-MM-DD — only videos first_seen_at on or after this date
        ?limit=<n>        — max videos per campaign (default 100)
    """
    if not _db.is_active():
        return jsonify({"error": "DB mode required."}), 400

    campaign_filter = request.args.get("campaign", "").strip()
    since_str = request.args.get("since", "").strip()
    limit = request.args.get("limit", 100, type=int)

    since_dt = None
    if since_str:
        try:
            since_dt = datetime.strptime(since_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({
                "error": f"Invalid 'since' format: {since_str}",
                "hint": "Use YYYY-MM-DD",
            }), 400

    with _db.get_session() as s:
        q = (
            s.query(MatchedVideo, Campaign)
            .join(Campaign, MatchedVideo.campaign_id == Campaign.id)
            .filter(MatchedVideo.tracked_at.is_(None))
            .filter(MatchedVideo.dismissed_at.is_(None))
            .filter(Campaign.status == "active")
            .filter(or_(Campaign.completion_status.is_(None), Campaign.completion_status != "completed"))
        )
        if campaign_filter:
            q = q.filter(Campaign.slug == campaign_filter)
        if since_dt is not None:
            q = q.filter(MatchedVideo.first_seen_at >= since_dt)
        q = q.order_by(
            Campaign.slug,
            MatchedVideo.first_seen_at.desc(),
            MatchedVideo.views.desc(),
        )
        rows = q.all()

    by_campaign: dict = {}
    total = 0
    for mv, camp in rows:
        # CAMP-42: when a round-2 campaign reuses creators from round 1,
        # those creators' pre-start-date posts persist as matched_videos
        # rows. Cobrand only dedupes within a single round, so leaking
        # them into the queue produces duplicate uploads in the client
        # report. Exclude videos posted before the campaign's start_date.
        if video_posted_before_start(
            {"timestamp": mv.timestamp or "", "upload_date": mv.upload_date or ""},
            camp.start_date or "",
        ):
            continue
        slug = camp.slug or ""
        if slug not in by_campaign:
            by_campaign[slug] = {
                "slug": slug,
                "title": camp.title or camp.name or slug,
                "artist": camp.artist or "",
                "song": camp.song or "",
                "match_strategy": camp.match_strategy or "fuzzy",
                "completion_status": camp.completion_status or "none",
                "round": camp.round or "",
                "untracked_count": 0,
                "videos": [],
            }
        bucket = by_campaign[slug]
        if len(bucket["videos"]) >= limit:
            bucket["untracked_count"] += 1
            continue
        bucket["videos"].append({
            "id": mv.id,
            "url": mv.url or "",
            "account": mv.account or "",
            "views": mv.views or 0,
            "likes": mv.likes or 0,
            "song": mv.song or "",
            "match_strategy": mv.match_strategy or "",
            "extracted_sound_id": mv.extracted_sound_id or "",
            "first_seen_at": (
                mv.first_seen_at.isoformat() if mv.first_seen_at else ""
            ),
            "timestamp": mv.timestamp or "",
            "upload_date": mv.upload_date or "",
        })
        bucket["untracked_count"] += 1
        total += 1

    # Sort campaigns by untracked_count desc — busiest first
    campaigns = sorted(
        by_campaign.values(),
        key=lambda c: c["untracked_count"],
        reverse=True,
    )

    return jsonify({
        "total_untracked": total,
        "campaigns": campaigns,
    })


@scrape_tasks_bp.get("/api/scrape-tasks/health")
def health():
    """Return cron run health summary for the Scrape Tasks tab."""
    logs = _db.get_cron_logs(limit=10) or []

    # Filter to the campaign refresh job specifically
    refresh_logs = [
        log for log in logs
        if (log.get("job_type") or "").startswith("campaign_refresh")
    ]

    last = refresh_logs[0] if refresh_logs else None

    history = []
    for log in refresh_logs[:7]:
        summary = log.get("summary") or {}
        history.append({
            "id": log.get("id"),
            "status": log.get("status") or "",
            "started_at": log.get("started_at") or "",
            "finished_at": log.get("finished_at") or "",
            "degraded": bool(summary.get("degraded", False)),
            "campaigns_refreshed": summary.get("campaigns_refreshed", 0),
            "total_new_matches": summary.get("total_new_matches", 0),
            "empty_creator_rate": summary.get("empty_creator_rate", 0),
        })

    return jsonify({
        "last_run": last,
        "history": history,
    })


@scrape_tasks_bp.post("/api/scrape-tasks/mark-tracked")
def mark_tracked():
    """Mark one or more matched videos as tracked.

    Body: {"matched_video_ids": [1234, 1235, ...], "tracked_by": "<name>"}

    Strict body validation — invalid types or missing IDs return 400 not
    silent success. (Audit lesson: send-all-style endpoints that ignore
    body are dangerous.)
    """
    data = request.get_json(silent=True) or {}
    ids = data.get("matched_video_ids")
    tracked_by = (data.get("tracked_by") or "").strip()[:100]

    if not isinstance(ids, list) or not ids:
        return jsonify({
            "error": "matched_video_ids must be a non-empty list of integers",
        }), 400

    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "matched_video_ids must be integers"}), 400

    now = datetime.now()
    updated = 0
    with _db.get_session() as s:
        rows = s.query(MatchedVideo).filter(MatchedVideo.id.in_(ids)).all()
        for row in rows:
            if row.tracked_at is None:
                row.tracked_at = now
                if tracked_by:
                    row.tracked_by = tracked_by
                updated += 1
        s.commit()

    return jsonify({
        "ok": True,
        "marked_tracked": updated,
        "requested": len(ids),
    })


@scrape_tasks_bp.post("/api/scrape-tasks/unmark-tracked")
def unmark_tracked():
    """Undo: clear tracked_at on the given videos.

    Body: {"matched_video_ids": [1234, ...]}
    """
    data = request.get_json(silent=True) or {}
    ids = data.get("matched_video_ids")

    if not isinstance(ids, list) or not ids:
        return jsonify({
            "error": "matched_video_ids must be a non-empty list of integers",
        }), 400

    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "matched_video_ids must be integers"}), 400

    updated = 0
    with _db.get_session() as s:
        rows = s.query(MatchedVideo).filter(MatchedVideo.id.in_(ids)).all()
        for row in rows:
            if row.tracked_at is not None:
                row.tracked_at = None
                row.tracked_by = ""
                updated += 1
        s.commit()

    return jsonify({
        "ok": True,
        "unmarked": updated,
        "requested": len(ids),
    })


@scrape_tasks_bp.get("/api/scrape-tasks/tracker-discovery")
def tracker_discovery():
    """Return the campaign↔tracker discovery report.

    Surfaces:
        - matched: active campaigns that have a TidesTracker (via sound-ID overlap)
        - unmatched: active campaigns with no Cobrand tracker — needs setup
        - orphan_trackers: TidesTrackers with no active campaign (probably
          tied to completed campaigns or test/old promos)

    The Scrape Tasks tab uses this to show your team which campaigns
    are missing trackers so they can fix the gap.
    """
    from campaign_manager.services.tracker_discovery import discovery_report
    try:
        report = discovery_report()
        return jsonify(report)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scrape_tasks_bp.post("/api/scrape-tasks/mark-campaign-tracked")
def mark_campaign_tracked():
    """Bulk-mark every untracked video for a single campaign as tracked.

    Body: {"slug": "<campaign-slug>", "tracked_by": "<name>"}

    Useful when the human pastes a whole batch into Cobrand at once.
    """
    data = request.get_json(silent=True) or {}
    slug = (data.get("slug") or "").strip()
    tracked_by = (data.get("tracked_by") or "").strip()[:100]

    if not slug:
        return jsonify({"error": "slug is required"}), 400

    now = datetime.now()
    with _db.get_session() as s:
        camp = s.query(Campaign).filter_by(slug=slug).first()
        if not camp:
            return jsonify({"error": "Campaign not found"}), 404

        rows = (
            s.query(MatchedVideo)
            .filter_by(campaign_id=camp.id)
            .filter(MatchedVideo.tracked_at.is_(None))
            .filter(MatchedVideo.dismissed_at.is_(None))
            .all()
        )
        campaign_start = camp.start_date or ""
        count = 0
        for row in rows:
            # CAMP-42: skip pre-start-date rows so a bulk-tracked sweep
            # doesn't claim we uploaded round-1 posts under round 2 — the
            # queue itself hides those rows, so they're not part of what
            # the user just sent to Cobrand.
            if video_posted_before_start(
                {"timestamp": row.timestamp or "", "upload_date": row.upload_date or ""},
                campaign_start,
            ):
                continue
            row.tracked_at = now
            if tracked_by:
                row.tracked_by = tracked_by
            count += 1
        s.commit()

    return jsonify({"ok": True, "slug": slug, "marked_tracked": count})


@scrape_tasks_bp.post("/api/scrape-tasks/dismiss")
def dismiss():
    """Soft-dismiss false-positive matches.

    Body: {
        "matched_video_ids": [1234, ...],
        "dismissed_by": "<name>",   # optional, recorded for audit
        "reason": "<free text>"     # optional, why it was dismissed
    }

    Dismissed rows stay in the DB (so re-scrapes don't resurrect them via
    insert) but are hidden from the tracking queue and excluded from
    campaign view/engagement totals.
    """
    data = request.get_json(silent=True) or {}
    ids = data.get("matched_video_ids")
    dismissed_by = (data.get("dismissed_by") or "").strip()[:100]
    reason = (data.get("reason") or "").strip()

    if not isinstance(ids, list) or not ids:
        return jsonify({
            "error": "matched_video_ids must be a non-empty list of integers",
        }), 400

    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "matched_video_ids must be integers"}), 400

    now = datetime.now()
    updated = 0
    with _db.get_session() as s:
        rows = s.query(MatchedVideo).filter(MatchedVideo.id.in_(ids)).all()
        for row in rows:
            if row.dismissed_at is None:
                row.dismissed_at = now
                if dismissed_by:
                    row.dismissed_by = dismissed_by
                if reason:
                    row.dismissed_reason = reason
                updated += 1
        s.commit()

    return jsonify({
        "ok": True,
        "dismissed": updated,
        "requested": len(ids),
    })


@scrape_tasks_bp.post("/api/scrape-tasks/undismiss")
def undismiss():
    """Undo a dismissal — restores the row to the active set.

    Body: {"matched_video_ids": [1234, ...]}
    """
    data = request.get_json(silent=True) or {}
    ids = data.get("matched_video_ids")

    if not isinstance(ids, list) or not ids:
        return jsonify({
            "error": "matched_video_ids must be a non-empty list of integers",
        }), 400

    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return jsonify({"error": "matched_video_ids must be integers"}), 400

    updated = 0
    with _db.get_session() as s:
        rows = s.query(MatchedVideo).filter(MatchedVideo.id.in_(ids)).all()
        for row in rows:
            if row.dismissed_at is not None:
                row.dismissed_at = None
                row.dismissed_by = ""
                row.dismissed_reason = ""
                updated += 1
        s.commit()

    return jsonify({
        "ok": True,
        "undismissed": updated,
        "requested": len(ids),
    })
