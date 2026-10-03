"""Creator Library API — the roster, its niche vocabulary, and rate memory.

Endpoints:
  GET    /api/library/creators?window=w60
  POST   /api/library/creators                  add a scouted creator
  PATCH  /api/library/creators/<username>       rate / slow / note / paypal
  PUT    /api/library/creators/<username>/niches
  GET    /api/library/creators/<username>/rate  booking auto-fill

  GET    /api/library/niches
  POST   /api/library/niches                    create (get-or-create)
  PATCH  /api/library/niches/<id>               rename (merges on clash)
  DELETE /api/library/niches/<id>
  POST   /api/library/niches/<id>/apply         bulk-tag many creators
  POST   /api/library/niches/<id>/merge         fold into another niche

  POST   /api/library/refresh-stats             pull live Tides Tracker views
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from campaign_manager import db as _db
from campaign_manager.services import creator_library as lib
from campaign_manager.services.creator_library_refresh import refresh_creator_stats
from campaign_manager.services.creator_library_stats import DEFAULT_WINDOW, WINDOWS
from campaign_manager.services.creator_library_view import (
    build_library,
    rate_for_booking,
)

log = logging.getLogger(__name__)

creator_library_bp = Blueprint("creator_library", __name__)

# Progress for the manual refresh. Per-worker, not shared across gunicorn
# processes — enough to stop one browser tab starting three overlapping
# runs, which is what this guards. The scheduled job is the real path.
_refresh_lock = threading.Lock()
_refresh_state = {"running": False, "started_at": "", "last": None, "error": ""}


def _session():
    if not _db.is_active():
        return None
    return _db.get_session()


def _requires_db():
    return jsonify({"error": "Database not available."}), 503


# ── roster ─────────────────────────────────────────────────────────────

@creator_library_bp.get("/api/library/creators")
def list_creators():
    """The full roster, ranked by projected CPM in the requested window."""
    window = request.args.get("window", DEFAULT_WINDOW)
    if window not in WINDOWS:
        window = DEFAULT_WINDOW

    session = _session()
    if session is None:
        return _requires_db()
    try:
        rows = build_library(session, window=window)
        return jsonify({
            "window": window,
            "windows": list(WINDOWS.keys()),
            "count": len(rows),
            "creators": rows,
        })
    finally:
        session.close()


@creator_library_bp.post("/api/library/creators")
def add_creator():
    """Add someone scouted off-platform, before any booking exists."""
    data = request.get_json(silent=True) or {}
    username = lib.normalize_username(data.get("username"))
    if not username:
        return jsonify({"error": "Username is required."}), 400

    session = _session()
    if session is None:
        return _requires_db()
    try:
        from campaign_manager.models import CreatorProfile

        if session.get(CreatorProfile, username) is not None:
            return jsonify({"error": f"@{username} is already in the library."}), 409

        lib.get_or_create_profile(session, data.get("username") or username)

        fields = {}
        if data.get("paypal_email"):
            fields["paypal_email"] = str(data["paypal_email"]).strip()
        if data.get("platform"):
            fields["platform"] = str(data["platform"]).strip()
        if data.get("note"):
            fields["note"] = str(data["note"])

        rate = data.get("rate")
        if rate not in (None, ""):
            try:
                fields["rate_override"] = float(rate)
            except (TypeError, ValueError):
                return jsonify({"error": "Rate must be a number."}), 400

        if fields:
            lib.update_profile(session, username, **fields)

        niches = data.get("niches")
        if isinstance(niches, list) and niches:
            lib.set_niches(session, username, niches)

        return jsonify({"ok": True, "username": username}), 201
    finally:
        session.close()


@creator_library_bp.patch("/api/library/creators/<path:username>")
def patch_creator(username: str):
    """Update rate memory, the slow flag, notes or PayPal.

    Sending `rate` as null clears the manual rate and hands control back to
    the booking history.
    """
    data = request.get_json(silent=True) or {}
    session = _session()
    if session is None:
        return _requires_db()
    try:
        fields = {}

        if "rate" in data:
            rate = data["rate"]
            if rate in (None, ""):
                fields["rate_override"] = None
            else:
                try:
                    fields["rate_override"] = float(rate)
                except (TypeError, ValueError):
                    return jsonify({"error": "Rate must be a number."}), 400

        if "slow" in data:
            fields["slow"] = bool(data["slow"])
        if "note" in data:
            fields["note"] = str(data["note"] or "")
        if "paypal_email" in data:
            fields["paypal_email"] = str(data["paypal_email"] or "").strip()

        if not fields:
            return jsonify({"error": "Nothing to update."}), 400

        profile = lib.update_profile(session, username, **fields)
        return jsonify({"ok": True, "creator": profile.to_dict()})
    finally:
        session.close()


@creator_library_bp.put("/api/library/creators/<path:username>/niches")
def set_creator_niches(username: str):
    """Replace this creator's tags. Unknown names join the vocabulary."""
    data = request.get_json(silent=True) or {}
    niches = data.get("niches")
    if not isinstance(niches, list):
        return jsonify({"error": "niches must be a list."}), 400

    session = _session()
    if session is None:
        return _requires_db()
    try:
        applied = lib.set_niches(session, username, niches)
        return jsonify({"ok": True, "username": username, "niches": applied})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        session.close()


@creator_library_bp.get("/api/library/creators/<path:username>/rate")
def creator_rate(username: str):
    """What this creator should cost on the next booking, and why."""
    session = _session()
    if session is None:
        return _requires_db()
    try:
        return jsonify(rate_for_booking(session, username))
    finally:
        session.close()


# ── vocabulary ─────────────────────────────────────────────────────────

@creator_library_bp.get("/api/library/niches")
def list_niches():
    """The vocabulary with usage counts, most-used first.

    Seeds the starting set on first call so the picker is never empty.
    """
    session = _session()
    if session is None:
        return _requires_db()
    try:
        lib.ensure_seed_niches(session)
        rows = lib.list_niches(session)
        return jsonify({"count": len(rows), "niches": rows})
    finally:
        session.close()


@creator_library_bp.post("/api/library/niches")
def create_niche():
    data = request.get_json(silent=True) or {}
    session = _session()
    if session is None:
        return _requires_db()
    try:
        return jsonify(lib.create_niche(session, data.get("name"))), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        session.close()


@creator_library_bp.patch("/api/library/niches/<int:niche_id>")
def rename_niche(niche_id: int):
    data = request.get_json(silent=True) or {}
    session = _session()
    if session is None:
        return _requires_db()
    try:
        return jsonify(lib.rename_niche(session, niche_id, data.get("name")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    finally:
        session.close()


@creator_library_bp.delete("/api/library/niches/<int:niche_id>")
def delete_niche(niche_id: int):
    session = _session()
    if session is None:
        return _requires_db()
    try:
        if not lib.delete_niche(session, niche_id):
            return jsonify({"error": "Niche not found."}), 404
        return jsonify({"ok": True})
    finally:
        session.close()


@creator_library_bp.post("/api/library/niches/<int:niche_id>/apply")
def apply_niche(niche_id: int):
    """Tag many creators at once — the bulk path for working the backlog."""
    data = request.get_json(silent=True) or {}
    usernames = data.get("usernames")
    if not isinstance(usernames, list) or not usernames:
        return jsonify({"error": "usernames must be a non-empty list."}), 400

    session = _session()
    if session is None:
        return _requires_db()
    try:
        added = lib.apply_niche_to(session, niche_id, usernames)
        return jsonify({"ok": True, "tagged": added, "requested": len(usernames)})
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    finally:
        session.close()


@creator_library_bp.post("/api/library/niches/<int:niche_id>/merge")
def merge_niche(niche_id: int):
    """Fold this niche into another — the fix for near-duplicate tags."""
    data = request.get_json(silent=True) or {}
    target = data.get("into")
    if target in (None, ""):
        return jsonify({"error": "into (target niche id) is required."}), 400

    session = _session()
    if session is None:
        return _requires_db()
    try:
        return jsonify(lib.merge_niches(session, niche_id, int(target)))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    finally:
        session.close()


# ── stats refresh ──────────────────────────────────────────────────────

@creator_library_bp.post("/api/library/refresh-stats")
def refresh_stats():
    """Pull live view counts from every Tides Tracker.

    Completed campaigns are skipped by the read-time overlay, so without
    this their numbers stay frozen at whatever the last scrape caught.

    Runs in a background thread and returns 202 immediately. Even
    parallelised, walking a few hundred trackers can approach gunicorn's
    120s sync-worker timeout, and a refresh that dies at the proxy while
    still running server-side is the worst of both worlds. Callers poll
    /api/library/refresh-status.
    """
    if not _db.is_active():
        return _requires_db()

    with _refresh_lock:
        if _refresh_state.get("running"):
            return jsonify({"status": "already_running", **_refresh_state}), 202
        _refresh_state.update({
            "running": True,
            "started_at": datetime.now().isoformat(),
            "error": "",
        })

    app = current_app._get_current_object()

    def _run():
        session = _db.get_session()
        try:
            summary = refresh_creator_stats(session)
            log.info("library refresh: %s", summary)
            with _refresh_lock:
                _refresh_state.update({"running": False, "last": summary, "error": ""})
        except Exception as exc:
            log.exception("library refresh failed")
            with _refresh_lock:
                _refresh_state.update({"running": False, "error": str(exc)})
        finally:
            session.close()

    def _with_context():
        with app.app_context():
            _run()

    threading.Thread(target=_with_context, daemon=True).start()
    return jsonify({"status": "started"}), 202


@creator_library_bp.get("/api/library/refresh-status")
def refresh_status():
    """Whether a refresh is in flight, and the last run's summary."""
    with _refresh_lock:
        return jsonify(dict(_refresh_state))
