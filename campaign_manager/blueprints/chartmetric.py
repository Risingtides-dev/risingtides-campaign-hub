"""Campaign pop score (Spotify popularity via Chartmetric).

GET  /api/campaign/<slug>/pop-score        current score + daily history
POST /api/campaign/<slug>/pop-score/track  link a song {"link": "<spotify url | chartmetric url | ISRC>"}
                                           an empty link unlinks it
POST  /api/campaign/<slug>/pop-score/override set per-date streams/UGC attribution override
"""
from __future__ import annotations

import logging
import time
import requests
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

from campaign_manager import db as _db
from campaign_manager.models import Campaign
from campaign_manager.services import chartmetric
from campaign_manager.utils.attribution import calculate_attribution
from campaign_manager.utils.helpers import build_round_end_by_slug, video_in_round

log = logging.getLogger(__name__)

chartmetric_bp = Blueprint("chartmetric", __name__)

# Show the run-up before the campaign started so lift is visible.
HISTORY_LEAD_DAYS = 21
DEFAULT_HISTORY_DAYS = 90
MAX_LINK_LENGTH = 500


def _history_start(start_date: str) -> date:
    try:
        return datetime.strptime(start_date, "%Y-%m-%d").date() - timedelta(days=HISTORY_LEAD_DAYS)
    except (TypeError, ValueError):
        return datetime.now(_db.EST).date() - timedelta(days=DEFAULT_HISTORY_DAYS)


def _baseline(history: list, start_date: str):
    """Last reading on or before campaign start — what the lift is measured from."""
    before = [p for p in history if start_date and p["date"] <= start_date]
    return before[-1]["value"] if before else None


def _load(slug: str):
    with _db.get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if c is None:
            return None
        return {
            "track_id": c.chartmetric_track_id,
            "link": c.chartmetric_link or "",
            "start_date": c.start_date or "",
            "end_date": c.end_date or "",
            "end_date_auto": bool(c.end_date_auto),
            "completion_status": c.completion_status or "none",
            "attribution_overrides": c.attribution_overrides or {},
            "link_status": c.chartmetric_link_status or "",
            "link_detail": c.chartmetric_link_detail or "",
            "checked_at": c.chartmetric_autolink_checked_at,
            "song": c.song or "",
            "artist": c.artist or "",
        }


@chartmetric_bp.get("/api/campaign/<slug>/pop-score")
def get_pop_score(slug: str):
    if not _db.is_active():
        return jsonify({"error": "Database not available."}), 503
    row = _load(slug)
    if row is None:
        return jsonify({"error": "Campaign not found."}), 404
    if not row["track_id"]:
        from campaign_manager.services.chartmetric_autolink import get_autolink_interval_minutes, retry_days
        if not row["link_status"]:
            if not row["song"].strip() or not row["artist"].strip():
                return jsonify({"linked": False, "link_status": "no_song_info",
                                "link_detail": "Add a song title and artist so we can look for the track.",
                                "next_check": None})
            next_check = (datetime.now() + timedelta(minutes=get_autolink_interval_minutes())).isoformat()
            return jsonify({"linked": False, "link_status": "pending",
                            "link_detail": "Checking Chartmetric soon.", "next_check": next_check})
        checked = row["checked_at"]
        next_check = (checked + timedelta(days=retry_days(row["link_status"]))).isoformat() if checked else None
        return jsonify({"linked": False, "link_status": row["link_status"] or "no_song_info",
                        "link_detail": row["link_detail"] or "Song match has not been checked yet.",
                        "next_check": next_check})

    budget_started = time.monotonic()
    budget_seconds = 75
    deadline = budget_started + budget_seconds
    def too_slow():
        return time.monotonic() >= deadline
    try:
        client = chartmetric.get_client()
        snap = client.track_snapshot(row["track_id"], deadline=deadline)
        history = client.popularity_history(row["track_id"], since=_history_start(row["start_date"]), deadline=deadline)
    except chartmetric.ChartmetricError as e:
        return jsonify({"linked": True, "link": row["link"], "error": str(e)}), 502
    except Exception:
        log.exception("pop-score fetch failed for %s", slug)
        return jsonify({"linked": True, "link": row["link"], "error": "Couldn't reach Chartmetric."}), 502

    baseline = _baseline(history, row["start_date"])
    current = snap.spotify_popularity
    streams_error = None
    ugc_error = None
    try:
        if too_slow():
            raise TimeoutError
        pop_track_domain_id = client.popularity_track_domain_id(row["track_id"], since=_history_start(row["start_date"]), deadline=deadline)
        if too_slow():
            raise TimeoutError
        streams = client.streams_history(row["track_id"], since=_history_start(row["start_date"]), track_domain_id=pop_track_domain_id, deadline=deadline)
    except Exception as e:
        log.exception("streams history fetch failed for %s", slug)
        streams, streams_error = [], "Chartmetric is slow — try again shortly" if isinstance(e, (TimeoutError, requests.Timeout, requests.ConnectionError)) else "Streams history is temporarily unavailable."
    try:
        if too_slow():
            raise TimeoutError
        ugc = client.tiktok_posts_history(row["track_id"], since=_history_start(row["start_date"]), deadline=deadline)
    except Exception as e:
        log.exception("TikTok posts history fetch failed for %s", slug)
        ugc, ugc_error = [], "Chartmetric is slow — try again shortly" if isinstance(e, (TimeoutError, requests.Timeout, requests.ConnectionError)) else "TikTok video history is temporarily unavailable."
    try:
        attribution = calculate_attribution(history, streams, row["start_date"], row["end_date"], ugc=ugc, completion_status=row["completion_status"], today=datetime.now(_db.EST).date(), overrides=row["attribution_overrides"])
    except Exception:
        log.exception("attribution calculation failed for %s", slug)
        return jsonify({"linked": True, "link": row["link"], "error": "Couldn't calculate song attribution."}), 502
    result = {
        "linked": True,
        "link": row["link"],
        "chartmetric_track_id": snap.chartmetric_id,
        "link_status": row["link_status"],
        "track": {"name": snap.name, "artists": list(snap.artists), "image_url": snap.image_url},
        "spotify_popularity": current,
        "chartmetric_score": snap.chartmetric_score,
        "spotify_streams": snap.spotify_streams,
        "baseline": baseline,
        "change_since_start": (current - baseline) if (current is not None and baseline is not None) else None,
        "start_date": row["start_date"],
        "end_date_auto": row["end_date_auto"],
        "history": history,
        **attribution,
    }
    if streams_error:
        result["streams_error"] = streams_error
    if ugc_error:
        result["ugc_error"] = ugc_error
    from campaign_manager.models import MatchedVideo
    round_end = build_round_end_by_slug(_db.list_campaigns(exclude_completed=False)).get(slug)
    with _db.get_session() as s:
        campaign = s.query(Campaign).filter_by(slug=slug).first()
        events = {}
        if campaign:
            for video in s.query(MatchedVideo).filter(MatchedVideo.campaign_id == campaign.id, MatchedVideo.dismissed_at.is_(None)).all():
                upload_date = video.upload_date
                if not video_in_round(
                    {"id": video.id, "url": video.url or "", "timestamp": video.timestamp, "upload_date": upload_date,
                     "extracted_sound_id": video.extracted_sound_id or "", "music_id": video.music_id or ""},
                    row["start_date"], end_date=round_end,
                ):
                    continue
                raw = (upload_date or "").strip()
                day = raw[:4] + "-" + raw[4:6] + "-" + raw[6:8] if len(raw) == 8 and raw.isdigit() else raw[:10]
                try:
                    day = date.fromisoformat(day).isoformat()
                except ValueError:
                    continue
                if _history_start(row["start_date"]).isoformat() <= day <= datetime.now(_db.EST).date().isoformat():
                    events[day] = events.get(day, 0) + 1
    result["post_events"] = [{"date": d, "count": events[d]} for d in sorted(events)]
    return jsonify(result)


@chartmetric_bp.post("/api/campaign/<slug>/pop-score/override")
def set_pop_score_override(slug: str):
    if not _db.is_active():
        return jsonify({"error": "Database not available."}), 503
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid override."}), 400
    metric, day, action = data.get("metric"), data.get("date"), data.get("action")
    try:
        parsed = date.fromisoformat(day) if isinstance(day, str) else None
        valid_date = parsed is not None and parsed.isoformat() == day
    except ValueError:
        valid_date = False
    if metric not in ("streams", "ugc") or not valid_date or action not in ("include", "exclude", "auto"):
        return jsonify({"error": "metric, date, or action is invalid."}), 400
    with _db.get_session() as s:
        query = s.query(Campaign).filter_by(slug=slug)
        if s.bind and s.bind.dialect.name == "postgresql":
            query = query.with_for_update()
        campaign = query.first()
        if campaign is None:
            return jsonify({"error": "Campaign not found."}), 404
        overrides = dict(campaign.attribution_overrides or {})
        metric_values = dict(overrides.get(metric) or {})
        if action == "auto":
            metric_values.pop(day, None)
        else:
            metric_values[day] = action
        overrides[metric] = metric_values
        campaign.attribution_overrides = overrides
        s.commit()
    return jsonify({"ok": True, "attribution_overrides": overrides})


@chartmetric_bp.post("/api/campaign/<slug>/pop-score/track")
def set_pop_score_track(slug: str):
    if not _db.is_active():
        return jsonify({"error": "Database not available."}), 503
    data = request.get_json(silent=True) or {}
    link = str(data.get("link") or "").strip()
    if len(link) > MAX_LINK_LENGTH:
        return jsonify({"error": "Link is too long."}), 400

    track_id = None
    if link:
        try:
            ref = chartmetric.parse_track_link(link)
            track_id = chartmetric.get_client().resolve_track_id(ref)
        except chartmetric.ChartmetricError as e:
            return jsonify({"error": str(e)}), 400
        except Exception:
            log.exception("Chartmetric resolve failed for %s", slug)
            return jsonify({"error": "Couldn't reach Chartmetric."}), 502

    with _db.get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if c is None:
            return jsonify({"error": "Campaign not found."}), 404
        if not link or c.chartmetric_track_id != track_id:
            c.attribution_overrides = {}
        c.chartmetric_track_id = track_id
        c.chartmetric_link = link
        c.chartmetric_link_status = "manual" if link else ""
        c.chartmetric_link_detail = "Linked by a user." if link else ""
        c.chartmetric_autolink_checked_at = None if not link else c.chartmetric_autolink_checked_at
        s.commit()

    return jsonify({"ok": True, "chartmetric_track_id": track_id, "link": link})
