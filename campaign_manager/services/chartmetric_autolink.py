"""Self-healing campaign to Chartmetric song linking."""
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
AUTOLINK_INTERVAL_DEFAULT = 120
AUTOLINK_INTERVAL_MIN = 30
AUTOLINK_INTERVAL_MAX = 1440
RUN_BUDGET_SECONDS = 8 * 60
RUN_LIMIT = 25
_in_progress = False
_lock = threading.Lock()


def get_autolink_interval_minutes():
    raw = os.environ.get("CHARTMETRIC_AUTOLINK_INTERVAL_MINUTES", "")
    try:
        value = int(raw) if raw else AUTOLINK_INTERVAL_DEFAULT
    except ValueError:
        return AUTOLINK_INTERVAL_DEFAULT
    return max(AUTOLINK_INTERVAL_MIN, min(AUTOLINK_INTERVAL_MAX, value))


def retry_days(status):
    return {"not_released": 1, "ambiguous": 3, "artist_not_found": 3}.get(status, 7)


def _due(campaign, now):
    checked = campaign.chartmetric_autolink_checked_at
    return checked is None or checked <= now - timedelta(days=retry_days(campaign.chartmetric_link_status))


def resolve_one(slug, client=None, deadline=None):
    """Resolve and persist one campaign; safe for immediate background invocation."""
    client = client or get_client()
    with db.get_session() as session:
        campaign = session.query(Campaign).filter_by(slug=slug).first()
        if campaign is None:
            return None
        data = {key: getattr(campaign, key) or "" for key in
                ("song", "artist", "sound_id", "tt_artist_label", "tt_track_name", "start_date", "round")}
        data["slug"] = slug
        already_linked = bool(campaign.chartmetric_track_id or campaign.chartmetric_link)
        manual = campaign.chartmetric_link_status == "manual"
    if already_linked or manual:
        return None
    result = client.resolve_campaign(data, deadline=deadline)
    detail = result.get("detail") or ""
    if result.get("status") == "linked_auto" and result.get("method"):
        detail = f"{result['method']}: {detail}"
    fields = {
        "chartmetric_autolink_checked_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "chartmetric_link_status": result["status"],
        "chartmetric_link_detail": detail[:500],
    }
    if result.get("status") == "linked_auto":
        with db.get_session() as session:
            current = session.query(Campaign).filter_by(slug=slug).first()
            if current is None or current.chartmetric_track_id or current.chartmetric_link:
                return None
            fields.update(chartmetric_track_id=result["track_id"],
                          chartmetric_link=f"https://app.chartmetric.com/track?id={result['track_id']}")
    db.update_campaign_fields(slug, fields)
    return result


def _run(limit=RUN_LIMIT):
    if not os.environ.get("CHARTMETRIC_REFRESH_TOKEN"):
        return {"linked": 0, "checked": 0, "stopped": "missing_auth"}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deadline = time.monotonic() + RUN_BUDGET_SECONDS
    with db.get_session() as session:
        candidates = (session.query(Campaign)
            .filter(Campaign.chartmetric_track_id.is_(None))
            .filter((Campaign.chartmetric_link.is_(None)) | (Campaign.chartmetric_link == ""))
            .order_by(Campaign.created_at.desc().nullslast(), Campaign.start_date.desc().nullslast())
            .limit(500).all())
        campaigns = [c.slug for c in candidates if c.chartmetric_link_status != "manual" and _due(c, now)][:min(limit, RUN_LIMIT)]
    client = get_client()
    linked = checked = 0
    stopped = ""
    rate_limits = 0
    for slug in campaigns:
        if time.monotonic() >= deadline:
            stopped = "budget"
            break
        try:
            result = resolve_one(slug, client=client, deadline=deadline)
            checked += int(result is not None)
            linked += int(bool(result and result.get("status") == "linked_auto"))
            rate_limits = 0
        except ChartmetricError as exc:
            # The client retries a 429 once. A second 429 ends this run.
            if "(429)" in str(exc):
                rate_limits += 1
                if rate_limits >= 1:
                    stopped = "rate_limit"
                    break
                time.sleep(2)
                continue
            log.error("Chartmetric auto-link stopped after API failure: %s", str(exc))
            stopped = "api_failure"
            break
        except Exception as exc:
            log.exception("Chartmetric auto-link failed for %s", slug)
            stopped = "error"
            break
    return {"linked": linked, "checked": checked, **({"stopped": stopped} if stopped else {})}


def autolink_campaigns(limit=RUN_LIMIT):
    global _in_progress
    if not _lock.acquire(blocking=False):
        return {"linked": 0, "checked": 0, "stopped": "in_progress"}
    _in_progress = True
    try:
        result = _run(limit)
        log.info("Chartmetric auto-link: %s", result)
        return result
    except Exception:
        log.exception("Chartmetric auto-link run failed")
        return {"linked": 0, "checked": 0, "stopped": "error"}
    finally:
        _in_progress = False
        _lock.release()


def request_immediate_resolve(slug):
    """Queue the same resolver on a daemon thread after campaign create/edit."""
    if not os.environ.get("CHARTMETRIC_REFRESH_TOKEN"):
        return
    try:
        from flask import current_app
        if current_app.testing:
            return
    except RuntimeError:
        pass
    def run():
        try:
            resolve_one(slug, deadline=time.monotonic() + RUN_BUDGET_SECONDS)
        except Exception:
            log.exception("Immediate Chartmetric resolution failed for %s", slug)
    threading.Thread(target=run, name=f"chartmetric-link-{slug}", daemon=True).start()
