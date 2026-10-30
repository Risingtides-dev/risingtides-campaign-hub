"""Creator payout endpoints (Round 1).

Public — authenticated by the creator's link token, rate-limited per IP:
  POST /api/creator/dashboard {token}                       -> own bookings + payments
  POST /api/payout/lookup    {token}                       -> handle + masked details
  POST /api/payout/submit    {token, method, destination}  -> saves, audits

  The token travels in the JSON body, never the URL, so it stays out of
  access logs. Any bad / unknown token gets the same 404, so a response
  never reveals whether a token exists.

Admin — require header X-Payout-Admin-Key == PAYOUT_ADMIN_KEY:
  GET  /api/payouts/admin/creators
  POST /api/payouts/admin/links                       {usernames: [...]}
  POST /api/payouts/admin/creators/<u>/rotate-link
  POST /api/payouts/admin/creators/<u>/clear-flag
  GET  /api/payouts/admin/creators/<u>/events
  GET  /api/payouts/admin/queue                        ready / awaiting / not ready
  POST /api/payouts/admin/bookings/mark                {slug, username, platform, action, note}
  POST /api/payouts/admin/creators/<u>/trust           {override: ''|trusted|standard}

No money moves here. Paying out (Stage 4) is a separate, human-approved step.
"""
from __future__ import annotations

from flask import Blueprint, current_app

from campaign_manager import db as _db
from campaign_manager.services import payout_profiles as payouts
from campaign_manager.services import payout_readiness as readiness
from campaign_manager.services.creator_dashboard import build_dashboard
from campaign_manager.services.payout_validation import PayoutValidationError
from campaign_manager.blueprints.payout_common import (  # noqa: F401 (limiters re-exported for tests)
    MAX_LINK_BATCH,
    _INVALID_LINK,
    admin_fail_limiter,
    admin_guard as _admin_guard,
    db_error as _db_error,
    db_unavailable,
    json_response as _json,
    log,
    public_limiter,
    request_body as _body,
)
from campaign_manager.utils.rate_limit import client_ip

payouts_bp = Blueprint("payouts", __name__)

# ── public (creator link) ──────────────────────────────────────────────

def _public_guard():
    if not public_limiter.allow(client_ip()):
        return _json({"error": "Too many tries. Wait a few minutes and try again."}, 429)
    if not _db.is_active():
        return db_unavailable()
    return None


@payouts_bp.post("/api/payout/lookup")
def payout_lookup():
    blocked = _public_guard()
    if blocked:
        return blocked
    with _db.get_session() as session:
        try:
            profile = payouts.find_by_token(session, _body().get("token"))
        except Exception as exc:
            return _db_error("lookup", exc)
        if profile is None:
            return _json({"error": _INVALID_LINK}, 404)
        return _json(payouts.public_view(profile))


@payouts_bp.post("/api/creator/dashboard")
def creator_dashboard():
    blocked = _public_guard()
    if blocked:
        return blocked
    with _db.get_session() as session:
        try:
            profile = payouts.find_by_token(session, _body().get("token"))
            if profile is None:
                return _json({"error": _INVALID_LINK}, 404)
            return _json(build_dashboard(session, profile))
        except Exception as exc:
            return _db_error("dashboard", exc)


@payouts_bp.post("/api/payout/submit")
def payout_submit():
    blocked = _public_guard()
    if blocked:
        return blocked
    data = _body()
    with _db.get_session() as session:
        try:
            profile = payouts.find_by_token(session, data.get("token"), for_update=True)
        except Exception as exc:
            return _db_error("submit lookup", exc)
        if profile is None:
            return _json({"error": _INVALID_LINK}, 404)
        try:
            event = payouts.submit_destination(
                session, profile, data.get("method"), data.get("destination"),
                client_ip=client_ip(),
            )
        except PayoutValidationError as exc:
            return _json({"error": str(exc)}, 400)
        except Exception as exc:
            session.rollback()
            return _db_error(f"submit for {profile.username}", exc)
        if event == "changed":
            # Username only — destinations are PII and stay out of logs.
            log.warning("payout destination CHANGED by creator link: %s", profile.username)
        return _json({"ok": True, "result": event, **payouts.public_view(profile)})


# ── admin (Hub Payouts page) ───────────────────────────────────────────

@payouts_bp.get("/api/payouts/admin/creators")
def admin_creators():
    blocked = _admin_guard()
    if blocked:
        return blocked
    with _db.get_session() as session:
        return _json(payouts.admin_overview(session))


@payouts_bp.post("/api/payouts/admin/links")
def admin_links():
    blocked = _admin_guard()
    if blocked:
        return blocked
    usernames = _body().get("usernames")
    if not isinstance(usernames, list) or not usernames:
        return _json({"error": "usernames must be a non-empty list"}, 400)
    if len(usernames) > MAX_LINK_BATCH:
        return _json({"error": f"At most {MAX_LINK_BATCH} usernames per request"}, 400)

    base = current_app.config.get("PUBLIC_BASE_URL", "")
    links, skipped = [], []
    with _db.get_session() as session:
        for raw in usernames:
            try:
                profile, issued = payouts.issue_token(session, str(raw))
            except ValueError:
                skipped.append(str(raw))
                continue
            links.append({
                "username": profile.username,
                "handle": profile.display_username or profile.username,
                "link": payouts.build_link(base, profile.payout_token),
                "newly_issued": issued,
                "has_destination": bool(profile.payout_destination),
            })
    return _json({"links": links, "skipped": skipped})


@payouts_bp.post("/api/payouts/admin/creators/<username>/rotate-link")
def admin_rotate(username):
    blocked = _admin_guard()
    if blocked:
        return blocked
    with _db.get_session() as session:
        try:
            profile, _ = payouts.issue_token(session, username, rotate=True)
        except ValueError:
            return _json({"error": "Username is required."}, 400)
        base = current_app.config.get("PUBLIC_BASE_URL", "")
        return _json({"username": profile.username,
                      "link": payouts.build_link(base, profile.payout_token)})


@payouts_bp.post("/api/payouts/admin/creators/<username>/clear-flag")
def admin_clear_flag(username):
    blocked = _admin_guard()
    if blocked:
        return blocked
    with _db.get_session() as session:
        if not payouts.clear_flag(session, username):
            return _json({"error": "Creator not found."}, 404)
        return _json({"ok": True})


@payouts_bp.get("/api/payouts/admin/creators/<username>/events")
def admin_events(username):
    blocked = _admin_guard()
    if blocked:
        return blocked
    with _db.get_session() as session:
        return _json({"events": payouts.events_for(session, username)})


@payouts_bp.get("/api/payouts/admin/queue")
def admin_queue():
    blocked = _admin_guard()
    if blocked:
        return blocked
    with _db.get_session() as session:
        return _json(readiness.build_queue(session))


@payouts_bp.post("/api/payouts/admin/bookings/mark")
def admin_mark_booking():
    """confirm = trusted creator accepted (paid up front); ready = manual
    override (e.g. partial delivery); clear = undo either."""
    blocked = _admin_guard()
    if blocked:
        return blocked
    data = _body()
    action = data.get("action")
    if action not in ("confirm", "ready", "clear"):
        return _json({"error": "action must be confirm, ready or clear"}, 400)
    fields = [data.get(k) for k in ("slug", "username", "platform")]
    if not all(isinstance(v, str) and v.strip() for v in fields):
        return _json({"error": "slug, username and platform are required"}, 400)
    note = data.get("note") if isinstance(data.get("note"), str) else ""
    with _db.get_session() as session:
        if not readiness.set_mark(session, *fields, action, note):
            return _json({"error": "Booking not found."}, 404)
        return _json({"ok": True})


@payouts_bp.post("/api/payouts/admin/creators/<username>/trust")
def admin_set_trust(username):
    blocked = _admin_guard()
    if blocked:
        return blocked
    override = _body().get("override")
    if override not in readiness.TRUST_OVERRIDES:
        return _json({"error": "override must be '', 'trusted' or 'standard'"}, 400)
    with _db.get_session() as session:
        if not readiness.set_trust_override(session, username, override):
            return _json({"error": "Creator not found."}, 404)
        return _json({"ok": True, "override": override})


@payouts_bp.post("/api/payouts/admin/creators/<username>/destination")
def admin_set_destination(username):
    blocked = _admin_guard()
    if blocked:
        return blocked
    data = _body()
    with _db.get_session() as session:
        try:
            user = payouts.admin_set_destination(session, username, data.get("method"), data.get("destination"))
        except PayoutValidationError as exc:
            return _json({"error": str(exc)}, 400)
        except ValueError:
            return _json({"error": "Username is required."}, 400)
        log.warning("payout destination set by admin: %s", user)
        return _json({"ok": True, "username": user})
