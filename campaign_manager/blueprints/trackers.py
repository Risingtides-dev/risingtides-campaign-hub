"""TidesTracker API endpoints.

Trackers themselves live in TidesTracker (Supabase). This blueprint:
  - Reads the live tracker list from the TidesTracker API
  - Maintains a local "folder" overlay (groups + tracker→group assignments)
  - Forwards POSTs to TidesTracker so creation goes through one place
"""
from __future__ import annotations

import logging
import re

from flask import Blueprint, jsonify, request

_log = logging.getLogger(__name__)

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


def _resolve_tracker_display_name(tracker_id: str, campaign_slug: str) -> str:
    """Best-effort display name for a tracker about to be linked.

    Tries the live TidesTracker name first (the authoritative label users
    see in TidesTracker itself). Falls back to the Campaign Hub campaign
    title so the row is never empty. Used by ``update_tracker`` to seed
    ``tracker_names`` atomically with link creation (RTA-41).

    Any failure short-circuits to "" — link creation must not be blocked
    by a TidesTracker outage, even though it means the row will be skipped
    in the same-transaction upsert. Emits a ``logger.warning`` when this
    happens so the soft-fail is visible in prod logs rather than silent.
    The next link edit or the backfill script will fill in the gap.
    """
    tid = (tracker_id or "").strip()
    slug = (campaign_slug or "").strip()
    if not tid:
        return ""

    tracker_api_error: str | None = None

    # 1. TidesTracker is the source of truth for tracker names.
    try:
        for t in list_tracker_campaigns():
            if (t.get("id") or "") == tid:
                name = (t.get("name") or "").strip()
                if name:
                    return name
                break
    except TidesTrackerError as e:
        tracker_api_error = str(e)

    # 2. Fallback: the Campaign Hub campaign title.
    if slug:
        c = _db.get_campaign(slug)
        if c:
            title = (c.get("title") or c.get("name") or "").strip()
            if title:
                return title

    # Both sources exhausted — link will commit without a tracker_names
    # row. Backfill or the next link edit closes the gap, but log it so
    # the soft-fail is visible.
    _log.warning(
        "tracker_names not populated for tracker_id=%s (campaign_slug=%s): "
        "no TidesTracker name (%s), no campaign title fallback",
        tid,
        slug or "<none>",
        tracker_api_error or "no match in tracker list",
    )
    return ""


def _hydrate(
    tracker: dict,
    assignments: dict,
    names: dict,
    campaign_links: dict,
    campaigns_by_slug: dict,
    tracker_to_suggestions: dict,
    archives: dict,
) -> dict:
    """Convert a TidesTracker API row into the shape the frontend expects.

    `tracker_to_suggestions` maps tracker_id -> list of suggested campaigns
    (slug + title) whose sound IDs overlap with this tracker's sounds.
    Surfaces "you should probably link this tracker to <campaign>" in the UI.

    `archives` maps tracker_id -> archived_at datetime for soft-deleted trackers.
    """
    tid = tracker.get("id") or ""
    original_name = tracker.get("name") or ""
    override = names.get(tid) or ""
    linked_slug = campaign_links.get(tid)
    campaign_obj = campaigns_by_slug.get(linked_slug) if linked_slug else None
    archived_at = archives.get(tid)
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
        "auto_suggested_campaigns": tracker_to_suggestions.get(tid, []),
        "archived_at": archived_at.isoformat() if archived_at else None,
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
    archives = _db.get_tracker_archives()
    all_campaigns = _db.list_campaigns()
    campaigns_by_slug = {
        c.get("slug"): {
            "slug": c.get("slug"),
            "title": c.get("title") or c.get("name") or "",
        }
        for c in all_campaigns
        if c.get("slug")
    }

    # Build sound-ID auto-suggestions: tracker_id -> [{slug, title, matched_sound_ids}]
    # Only consider active campaigns that aren't completed.
    # CAMP-50: pre-resolve manual_links + archived_tids once and thread them
    # through `find_trackers_for_campaign` so the loop body does no DB work.
    tracker_to_suggestions: dict = {}
    try:
        from campaign_manager.services.tracker_discovery import (
            find_trackers_for_campaign,
        )
        archived_tids = set(archives.keys())
        for c in all_campaigns:
            if (c.get("completion_status") or "") == "completed":
                continue
            if (c.get("status") or "") != "active":
                continue
            slug = c.get("slug") or ""
            title = c.get("title") or c.get("name") or slug
            for hit in find_trackers_for_campaign(
                c,
                manual_links=campaign_links,
                archived_tids=archived_tids,
            ):
                # Only surface auto-detected (sound_id) hits as suggestions
                # — manual links are already reflected in `campaign_slug`.
                if hit.get("link_source") == "manual":
                    continue
                tid = hit.get("tracker_id") or ""
                if not tid:
                    continue
                tracker_to_suggestions.setdefault(tid, []).append({
                    "slug": slug,
                    "title": title,
                    "matched_sound_ids": hit.get("matched_sound_ids", []),
                })
    except Exception:
        # Discovery is non-critical — don't fail the trackers list if it errors
        tracker_to_suggestions = {}

    trackers = [
        _hydrate(
            t,
            assignments,
            names,
            campaign_links,
            campaigns_by_slug,
            tracker_to_suggestions,
            archives,
        )
        for t in raw
    ]

    # Hide archived (soft-deleted) trackers unless explicitly requested.
    # Pass ?include_archived=true to surface them (for an "Archived" view).
    include_archived = (request.args.get("include_archived") or "").lower() in (
        "1",
        "true",
        "yes",
    )
    if not include_archived:
        trackers = [t for t in trackers if not t.get("archived_at")]

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
            # Resolve a default display name so tracker_names is populated
            # atomically with the link (RTA-41). Prefer the live TidesTracker
            # name; fall back to the linked campaign's title. Either source
            # is fine — the column just needs to be non-null so name-based
            # lookups (RTA-40) resolve without falling back to slug match.
            display_name = _resolve_tracker_display_name(tracker_id, slug)
            _db.set_tracker_campaign_link(tracker_id, slug, display_name=display_name)
            response["campaign_slug"] = slug
        touched = True

    if not touched:
        return jsonify({"error": "No updatable fields supplied"}), 400
    return jsonify(response)


@trackers_bp.delete("/api/trackers/<tracker_id>")
def archive_tracker_endpoint(tracker_id: str):
    """Soft-delete (archive) a tracker.

    Trackers themselves live in TidesTracker and we don't want to hard-delete
    them remotely — a typo'd duplicate just gets hidden from Campaign Hub by
    recording an archive timestamp here. POST `/restore` to undo.
    """
    err = _require_db()
    if err:
        return err
    if not _db.archive_tracker(tracker_id):
        return jsonify({"error": "tracker_id is required"}), 400
    return jsonify({"ok": True, "id": tracker_id, "archived": True})


@trackers_bp.post("/api/trackers/<tracker_id>/restore")
def restore_tracker_endpoint(tracker_id: str):
    """Un-archive a previously soft-deleted tracker."""
    err = _require_db()
    if err:
        return err
    _db.unarchive_tracker(tracker_id)  # idempotent: no-op if not archived
    return jsonify({"ok": True, "id": tracker_id, "archived": False})


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
    # Guard the cast — a non-numeric sort_order should be a clean 400, not an
    # unhandled 500 (mirrors update_tracker's guarded parse).
    try:
        sort_order = int(data.get("sort_order") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "sort_order must be an integer"}), 400
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
