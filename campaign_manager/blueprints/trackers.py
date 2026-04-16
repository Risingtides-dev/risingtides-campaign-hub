"""TidesTracker API endpoints.

Trackers themselves live in TidesTracker (Supabase). This blueprint:
  - Reads the live tracker list from the TidesTracker API
  - Maintains a local "folder" overlay (groups + tracker→group assignments)
  - Forwards POSTs to TidesTracker so creation goes through one place
"""
from __future__ import annotations

import re

from flask import Blueprint, jsonify, request

from campaign_manager import db as _db
from campaign_manager.services.tidestracker import (
    create_tracker_campaign,
    list_tracker_campaigns,
    tracker_url_for,
    TidesTrackerError,
)

trackers_bp = Blueprint("trackers", __name__)


def _require_db():
    if not _db.is_active():
        return jsonify({"error": "Database not configured. Trackers require Postgres."}), 503
    return None


def _slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "tracker"


def _hydrate(
    tracker: dict,
    assignments: dict,
    names: dict,
    campaign_links: dict,
    campaigns_by_slug: dict,
) -> dict:
    """Convert a TidesTracker API row into the shape the frontend expects."""
    tid = tracker.get("id") or ""
    original_name = tracker.get("name") or ""
    override = names.get(tid) or ""
    linked_slug = campaign_links.get(tid)
    campaign_obj = campaigns_by_slug.get(linked_slug) if linked_slug else None
    return {
        "id": tid,
        "name": override or original_name,
        "original_name": original_name,
        "slug": tracker.get("slug") or "",
        "cobrand_share_url": tracker.get("cobrand_share_link") or "",
        "tracker_url": tracker_url_for(tid),
        "is_active": bool(tracker.get("is_active", True)),
        "created_at": tracker.get("created_at") or "",
        "client": tracker.get("client") or None,
        "group_id": assignments.get(tid),
        "campaign_slug": linked_slug or None,
        "campaign": campaign_obj,
    }


# ---------------------------------------------------------------------------
# Trackers (live from TidesTracker, with local group overlay)
# ---------------------------------------------------------------------------

@trackers_bp.get("/api/trackers")
def list_trackers():
    err = _require_db()
    if err:
        return err
    try:
        raw = list_tracker_campaigns()
    except TidesTrackerError as e:
        return jsonify({"error": str(e)}), e.status_code

    assignments = _db.get_tracker_assignments()
    names = _db.get_tracker_names()
    campaign_links = _db.get_tracker_campaign_links()
    campaigns_by_slug = {
        c.get("slug"): {
            "slug": c.get("slug"),
            "title": c.get("title") or c.get("name") or "",
        }
        for c in _db.list_campaigns(status="")  # all statuses
        if c.get("slug")
    }
    trackers = [
        _hydrate(t, assignments, names, campaign_links, campaigns_by_slug)
        for t in raw
    ]

    group_id_raw = request.args.get("group_id")
    if group_id_raw == "none":
        trackers = [t for t in trackers if t["group_id"] is None]
    elif group_id_raw and group_id_raw.isdigit():
        gid = int(group_id_raw)
        trackers = [t for t in trackers if t["group_id"] == gid]

    return jsonify(trackers)


@trackers_bp.post("/api/trackers")
def create_tracker():
    err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    cobrand_share_url = (data.get("cobrand_share_url") or "").strip()
    name = (data.get("name") or "").strip() or cobrand_share_url
    group_id_raw = data.get("group_id")

    if not cobrand_share_url:
        return jsonify({"error": "cobrand_share_url is required"}), 400

    try:
        tracker_id, tracker_url = create_tracker_campaign(
            name=name,
            slug=_slugify(name),
            cobrand_share_url=cobrand_share_url,
        )
    except TidesTrackerError as e:
        return jsonify({"error": str(e)}), e.status_code

    group_id = None
    if group_id_raw not in (None, "", "null"):
        try:
            group_id = int(group_id_raw)
        except (TypeError, ValueError):
            group_id = None

    if group_id is not None and tracker_id:
        _db.set_tracker_assignment(tracker_id, group_id)

    return jsonify({
        "ok": True,
        "tracker": {
            "id": tracker_id,
            "name": name,
            "cobrand_share_url": cobrand_share_url,
            "tracker_url": tracker_url,
            "group_id": group_id,
        },
    }), 201


@trackers_bp.patch("/api/trackers/<tracker_id>")
def update_tracker(tracker_id: str):
    """Update local-only fields for a tracker (group_id, display name)."""
    err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    touched = False
    response: dict = {"ok": True, "id": tracker_id}

    if "group_id" in data:
        gid_raw = data["group_id"]
        if gid_raw in (None, "", "null"):
            _db.set_tracker_assignment(tracker_id, None)
            response["group_id"] = None
        else:
            try:
                gid = int(gid_raw)
            except (TypeError, ValueError):
                return jsonify({"error": "group_id must be an integer or null"}), 400
            _db.set_tracker_assignment(tracker_id, gid)
            response["group_id"] = gid
        touched = True

    if "name" in data:
        name_raw = data["name"]
        if name_raw is None or (isinstance(name_raw, str) and not name_raw.strip()):
            _db.set_tracker_name(tracker_id, None)
            response["name"] = None
        else:
            _db.set_tracker_name(tracker_id, str(name_raw))
            response["name"] = str(name_raw).strip()
        touched = True

    if "campaign_slug" in data:
        slug_raw = data["campaign_slug"]
        if slug_raw in (None, "", "null"):
            _db.set_tracker_campaign_link(tracker_id, None)
            response["campaign_slug"] = None
        else:
            slug = str(slug_raw).strip()
            _db.set_tracker_campaign_link(tracker_id, slug)
            response["campaign_slug"] = slug
        touched = True

    if not touched:
        return jsonify({"error": "No updatable fields supplied"}), 400
    return jsonify(response)


# ---------------------------------------------------------------------------
# Tracker groups (local-only)
# ---------------------------------------------------------------------------

@trackers_bp.get("/api/tracker-groups")
def list_tracker_groups():
    err = _require_db()
    if err:
        return err
    return jsonify(_db.list_tracker_groups())


@trackers_bp.post("/api/tracker-groups")
def create_tracker_group():
    err = _require_db()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    slug = (data.get("slug") or _slugify(title)).strip().lower()
    sort_order = int(data.get("sort_order") or 0)
    if not title:
        return jsonify({"error": "title is required"}), 400

    group = _db.create_tracker_group(slug, title, sort_order=sort_order)
    if not group:
        return jsonify({"error": f"Group '{slug}' already exists or is invalid"}), 409
    return jsonify(group), 201


@trackers_bp.delete("/api/tracker-groups/<int:group_id>")
def delete_tracker_group(group_id: int):
    err = _require_db()
    if err:
        return err
    if not _db.delete_tracker_group(group_id):
        return jsonify({"error": "Group not found"}), 404
    return jsonify({"ok": True})
