"""Sound Assignments proxy.

Thin pass-through to the Content Posting Lab's Telegram + Roster + Sounds
APIs. The lab is the source of truth for Telegram state (posters, pages,
sounds, page playlists). Campaign Hub provides the user-facing UI on top.

Single-origin frontend → no CORS, no exposing the lab URL in the bundle.
"""
from __future__ import annotations

from urllib.parse import urlencode

import requests
from flask import Blueprint, current_app, jsonify, request

sound_assignments_bp = Blueprint("sound_assignments", __name__, url_prefix="/api/sound-assignments")


def _lab_url(path: str, query: dict | None = None) -> str:
    base = current_app.config["CONTENT_LAB_URL"]
    url = f"{base}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


def _proxy(method: str, path: str, *, json_body=None, query=None, timeout=30):
    """Forward an HTTP call to the lab. Always returns a (Flask response, status) tuple."""
    url = _lab_url(path, query=query)
    try:
        resp = requests.request(method, url, json=json_body, timeout=timeout)
    except requests.RequestException as exc:
        return jsonify({"error": "lab_unreachable", "detail": str(exc)}), 502

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
