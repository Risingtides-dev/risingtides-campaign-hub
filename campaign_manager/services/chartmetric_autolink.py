"""Conservative scheduled linking of campaigns to Chartmetric tracks."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from campaign_manager import db
from campaign_manager.models import Campaign
from campaign_manager.services.chartmetric import ChartmetricError, get_client

log = logging.getLogger(__name__)
AUTOLINK_INTERVAL_DEFAULT = 360
AUTOLINK_INTERVAL_MIN = 30
AUTOLINK_INTERVAL_MAX = 1440
_in_progress = False
_lock = threading.Lock()


def get_autolink_interval_minutes():
    raw = os.environ.get("CHARTMETRIC_AUTOLINK_INTERVAL_MINUTES", "")
    try:
        value = int(raw) if raw else AUTOLINK_INTERVAL_DEFAULT
    except ValueError:
        return AUTOLINK_INTERVAL_DEFAULT
    return max(AUTOLINK_INTERVAL_MIN, min(AUTOLINK_INTERVAL_MAX, value))


def autolink_campaigns(limit=15):
    """Check stale unlinked campaigns and persist exact, unambiguous matches."""
    global _in_progress
    if not os.environ.get("CHARTMETRIC_REFRESH_TOKEN"):
        return {"linked": 0, "none": 0}
    if not _lock.acquire(blocking=False):
        return {"linked": 0, "none": 0}
    _in_progress = True
    linked = none = 0
    deadline = time.monotonic() + 300
    try:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
        with db.get_session() as session:
            rows = (session.query(Campaign)
                    .filter(Campaign.chartmetric_track_id.is_(None))
                    .filter((Campaign.chartmetric_link.is_(None)) | (Campaign.chartmetric_link == ""))
                    .filter((Campaign.chartmetric_autolink_checked_at.is_(None)) |
                            (Campaign.chartmetric_autolink_checked_at < cutoff))
                    .order_by(Campaign.start_date.desc()).limit(limit).all())
            campaigns = [(c.slug, c.song or "", c.artist or "") for c in rows]
        client = get_client()
        for slug, song, artist in campaigns:
            if time.monotonic() >= deadline:
                break
            try:
                track_id = client.search_track(song, artist, deadline=deadline)
            except ChartmetricError:
                log.exception("Chartmetric auto-link stopped after API failure")
                break
            fields = {"chartmetric_autolink_checked_at": datetime.now(timezone.utc).replace(tzinfo=None)}
            if track_id:
                # Re-read before writing so an operator's new link is preserved.
                with db.get_session() as session:
                    current = session.query(Campaign).filter_by(slug=slug).first()
                    can_link = bool(current and current.chartmetric_track_id is None and not current.chartmetric_link)
                if can_link:
                    fields.update(chartmetric_track_id=track_id,
                                  chartmetric_link=f"https://app.chartmetric.com/track?id={track_id}")
                    linked += 1
                else:
                    none += 1
            else:
                none += 1
            db.update_campaign_fields(slug, fields)
        log.info("Chartmetric auto-link: linked %d, ambiguous/none %d", linked, none)
        return {"linked": linked, "none": none}
    except Exception:
        log.exception("Chartmetric auto-link run failed")
        return {"linked": linked, "none": none}
    finally:
        _in_progress = False
        _lock.release()
