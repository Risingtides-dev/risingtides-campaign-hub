"""Sound Assignments proxy.

Thin pass-through to the Content Posting Lab's Telegram + Roster + Sounds
APIs. The lab is the source of truth for Telegram state (posters, pages,
sounds, page playlists). Campaign Hub provides the user-facing UI on top.

Single-origin frontend → no CORS, no exposing the lab URL in the bundle.
"""
from __future__ import annotations

import hmac
import os
import secrets
import time
from urllib.parse import urlsplit
from urllib.parse import urlencode

import requests
from flask import Blueprint, current_app, jsonify, request, session

from campaign_manager import db
from campaign_manager.models import SoundOperatorLoginState

sound_assignments_bp = Blueprint("sound_assignments", __name__, url_prefix="/api/sound-assignments")


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _operator_password() -> str:
    return (os.environ.get("SOUND_ASSIGNMENTS_OPERATOR_PASSWORD") or "").strip()


def _same_origin() -> bool:
    """Reject cross-site credentialed POSTs even when the browser omits Origin."""
    origin = request.headers.get("Origin")
    if origin:
        parsed = urlsplit(origin)
        expected_scheme = "https" if current_app.config.get("IS_RAILWAY") else request.scheme
        return (parsed.scheme == expected_scheme and parsed.netloc == request.host
                and not parsed.path.rstrip("/"))
    return request.headers.get("Sec-Fetch-Site") == "same-origin"


@sound_assignments_bp.before_request
def require_operator_or_server_key():
    """A same-origin operator session or a server-to-server key gates the proxy."""
    key = (os.environ.get("HUB_WRITE_KEY") or "").strip()
    if not key:
        return jsonify({"error": "Sound Assignments is not configured."}), 503

    # Preserve the existing explicitly keyed service contract. Its callers do
    # not receive browser sessions and never rely on operator configuration.
    supplied = request.headers.get("X-Hub-Write-Key", "")
    if (request.endpoint not in {"sound_assignments.login", "sound_assignments.operator_session"}
            and supplied and hmac.compare_digest(supplied, key)):
        return None

    password = _operator_password()
    if (len(password) < 32 or hmac.compare_digest(key, password)
            or (not current_app.config.get("TESTING") and not (os.environ.get("SECRET_KEY") or "").strip())
            or not current_app.config.get("CONTENT_LAB_HUB_API_KEY")):
        return jsonify({"error": "Sound Assignments operator access is not configured."}), 503

    if request.endpoint in {"sound_assignments.login", "sound_assignments.operator_session"}:
        if request.method not in _SAFE_METHODS and not _same_origin():
            return jsonify({"error": "Cross-origin request refused."}), 403
        return None

    if not session.get("sound_operator") or not session.get("sound_csrf"):
        return jsonify({"error": "Operator login required."}), 401
    if request.method not in _SAFE_METHODS:
        token = session.get("sound_csrf")
        if not token or not _same_origin() or not hmac.compare_digest(
            request.headers.get("X-CSRF-Token", ""), token
        ):
            return jsonify({"error": "CSRF validation failed."}), 403


def _check_operator_login(password: str) -> str:
    """Serialize attempts in PostgreSQL so all workers share one bounded lockout."""
    if db._SessionLocal is None or (
        getattr(getattr(db._engine, "dialect", None), "name", "") != "postgresql"
        and not current_app.config.get("TESTING")
    ):
        return "unavailable"
    now = int(time.time())
    try:
        with db._SessionLocal.begin() as transaction:
            transaction.execute(db.dialect_insert(SoundOperatorLoginState.__table__).values(
                id=1, window_started_at=now, failed_count=0, locked_until=0
            ).on_conflict_do_nothing(index_elements=["id"]))
            state = transaction.get(SoundOperatorLoginState, 1, with_for_update=True)
            if state.locked_until > now:
                return "limited"
            if now - state.window_started_at >= 300:
                state.window_started_at = now
                state.failed_count = 0
            if hmac.compare_digest(password, _operator_password()):
                state.failed_count = 0
                state.locked_until = 0
                return "ok"
            state.failed_count += 1
            if state.failed_count >= 10:
                state.locked_until = now + 300
                return "limited"
            return "invalid"
    except Exception:
        # A broken or unavailable counter cannot turn into unlimited guesses.
        return "unavailable"


@sound_assignments_bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    password = body.get("password", "") if isinstance(body, dict) else ""
    result = _check_operator_login(password if isinstance(password, str) else "")
    if result == "unavailable":
        return jsonify({"error": "Operator login unavailable."}), 503
    if result == "limited":
        return jsonify({"error": "Operator login temporarily limited."}), 429
    if result != "ok":
        return jsonify({"error": "Invalid operator credentials."}), 401
    session.clear()
    session.permanent = True
    session["sound_operator"] = True
    session["sound_csrf"] = secrets.token_urlsafe(32)
    return jsonify({"authenticated": True, "csrf_token": session["sound_csrf"]})


@sound_assignments_bp.get("/session")
def operator_session():
    if not session.get("sound_operator") or not session.get("sound_csrf"):
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "csrf_token": session.get("sound_csrf", "")})


@sound_assignments_bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"authenticated": False})


def _lab_url(path: str, query: dict | None = None) -> str:
    base = current_app.config["CONTENT_LAB_URL"]
    url = f"{base}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


def _proxy(method: str, path: str, *, json_body=None, query=None, timeout=30):
    """Forward an HTTP call to the lab. Always returns a (Flask response, status) tuple."""
    url = _lab_url(path, query=query)
    api_key = current_app.config.get("CONTENT_LAB_HUB_API_KEY")
    options = {"json": json_body, "timeout": timeout}
    if api_key:
        options["headers"] = {"X-API-Key": api_key}
        options["allow_redirects"] = False
    try:
        resp = requests.request(method, url, **options)
    except requests.RequestException as exc:
        # Invalid-header errors may contain the configured credential.
        detail = "Content Lab request failed" if api_key else str(exc)
        return jsonify({"error": "lab_unreachable", "detail": detail}), 502

    content_type = resp.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            return jsonify(resp.json()), resp.status_code
        except ValueError:
            pass

    # Non-JSON or unparseable JSON — wrap text in an error envelope so the
    # frontend always gets JSON back from this proxy.
    return jsonify({"error": "non_json_response", "body": resp.text[:500]}), resp.status_code


# ── Read endpoints (loaded by the UI on mount) ─────────────────────────────


@sound_assignments_bp.get("/posters")
def get_posters():
    """List all posters with their page assignments."""
    return _proxy("GET", "/api/telegram/posters")


@sound_assignments_bp.get("/pages")
def get_pages():
    """List all roster pages."""
    return _proxy("GET", "/api/roster/")


@sound_assignments_bp.get("/sounds")
def get_sounds():
    """List sounds. Pass active_only=false in query string to include inactive."""
    active_only = request.args.get("active_only", "true")
    return _proxy("GET", "/api/telegram/sounds", query={"active_only": active_only})


@sound_assignments_bp.get("/playlists")
def get_all_playlists():
    """All page playlists in one shot — {integration_id: [sound_id, ...]}."""
    return _proxy("GET", "/api/telegram/playlists")


@sound_assignments_bp.get("/pages/<integration_id>/playlist")
def get_page_playlist(integration_id):
    """Single page playlist with full sound details."""
    return _proxy("GET", f"/api/telegram/pages/{integration_id}/playlist")


@sound_assignments_bp.get("/posters/<poster_id>/preview")
def preview_poster(poster_id):
    """Preview the message a poster would receive — no send."""
    return _proxy("GET", f"/api/telegram/posters/{poster_id}/preview")


@sound_assignments_bp.get("/status")
def get_status():
    """Telegram integration health (bot running, sound counts, etc)."""
    return _proxy("GET", "/api/telegram/status")


# ── Write endpoints (playlist edits) ───────────────────────────────────────


@sound_assignments_bp.put("/pages/<integration_id>/playlist")
def replace_playlist(integration_id):
    """Replace a page's playlist wholesale. Body: {sound_ids: [...]}."""
    return _proxy("PUT", f"/api/telegram/pages/{integration_id}/playlist", json_body=request.get_json())


@sound_assignments_bp.post("/pages/<integration_id>/playlist/songs")
def add_song(integration_id):
    """Append a sound to a page's playlist. Body: {sound_id: '...'}."""
    return _proxy("POST", f"/api/telegram/pages/{integration_id}/playlist/songs", json_body=request.get_json())


@sound_assignments_bp.delete("/pages/<integration_id>/playlist/songs/<sound_id>")
def remove_song(integration_id, sound_id):
    """Remove a sound from a page's playlist."""
    return _proxy("DELETE", f"/api/telegram/pages/{integration_id}/playlist/songs/{sound_id}")


@sound_assignments_bp.delete("/pages/<integration_id>/playlist")
def clear_playlist(integration_id):
    """Wipe a page's playlist entirely."""
    return _proxy("DELETE", f"/api/telegram/pages/{integration_id}/playlist")


# ── Sync + Send ────────────────────────────────────────────────────────────


@sound_assignments_bp.post("/sync")
def sync_sounds():
    """Refresh the sound pool from Hub (active campaigns) + Notion (sound URLs).

    Returns the lab's sync result, including the unmatched-campaigns list which
    the UI surfaces as a warning panel.
    """
    return _proxy("POST", "/api/telegram/sounds/sync", timeout=60)


@sound_assignments_bp.post("/send/<poster_id>")
def send_to_poster(poster_id):
    """Send the personalized daily message to one poster's Sounds topic."""
    return _proxy("POST", f"/api/telegram/sound-assignments/send/{poster_id}", timeout=60)


@sound_assignments_bp.post("/send-all")
def send_to_all():
    """Send personalized daily messages to every poster."""
    return _proxy("POST", "/api/telegram/sound-assignments/send-all", timeout=120)
