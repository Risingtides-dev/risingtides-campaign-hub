"""Campaign pop score (Spotify popularity via Chartmetric).

GET  /api/campaign/<slug>/pop-score        current score + daily history
POST /api/campaign/<slug>/pop-score/track  link a song {"link": "<spotify url | chartmetric url | ISRC>"}
                                           an empty link unlinks it
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
from campaign_manager.utils.helpers import video_posted_before_start

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
        }


@chartmetric_bp.get("/api/campaign/<slug>/pop-score")
def get_pop_score(slug: str):
    if not _db.is_active():
        return jsonify({"error": "Database not available."}), 503
    row = _load(slug)
    if row is None:
        return jsonify({"error": "Campaign not found."}), 404
    if not row["track_id"]:
        return jsonify({"linked": False})

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
        from campaign_manager.models import MatchedVideo
        with _db.get_session() as s:
            campaign = s.query(Campaign).filter_by(slug=slug).first()
            post_dates = []
            if campaign:
                for video in s.query(MatchedVideo).filter(MatchedVideo.campaign_id == campaign.id, MatchedVideo.dismissed_at.is_(None)).all():
                    raw = (video.upload_date or "").strip()
                    day = raw[:4] + "-" + raw[4:6] + "-" + raw[6:8] if len(raw) == 8 and raw.isdigit() else raw[:10]
                    try:
                        post_dates.append(date.fromisoformat(day).isoformat())
                    except ValueError:
                        continue
        attribution = calculate_attribution(history, streams, row["start_date"], row["end_date"], ugc=ugc, completion_status=row["completion_status"], today=datetime.now(_db.EST).date(), post_dates=post_dates)
    except Exception:
        log.exception("attribution calculation failed for %s", slug)
        return jsonify({"linked": True, "link": row["link"], "error": "Couldn't calculate song attribution."}), 502
    result = {
        "linked": True,
        "link": row["link"],
        "chartmetric_track_id": snap.chartmetric_id,
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
    with _db.get_session() as s:
        campaign = s.query(Campaign).filter_by(slug=slug).first()
        events = {}
        if campaign:
            for video in s.query(MatchedVideo).filter(MatchedVideo.campaign_id == campaign.id, MatchedVideo.dismissed_at.is_(None)).all():
                upload_date = video.upload_date
                if video_posted_before_start({"timestamp": video.timestamp, "upload_date": upload_date}, row["start_date"]):
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
        c.chartmetric_track_id = track_id
        c.chartmetric_link = link
        s.commit()

    return jsonify({"ok": True, "chartmetric_track_id": track_id, "link": link})
