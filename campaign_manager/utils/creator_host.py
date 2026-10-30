"""Creator-only hostname (e.g. creators.risingtidesviral.com).

Creator dashboard links use a separate address from the Hub, so a creator
never lands on the Hub's URL and can't click around into campaigns, budgets
or other creators. On that host ONLY the creator page, its two API calls and
static assets are served; everything else is a plain 404.

This hides the Hub from creators; it does not lock it. The Hub's own address
still has no login.
"""
from __future__ import annotations

from flask import request

# Exact API paths the creator page calls.
_CREATOR_API = {"/api/creator/dashboard", "/api/payout/lookup", "/api/payout/submit"}
# SPA routes that render the creator dashboard.
_CREATOR_PAGES = {"/creator", "/payout"}
_STATIC_PREFIXES = ("/assets/",)
_STATIC_FILES = {"/favicon.svg", "/health"}


def _host() -> str:
    return (request.host or "").split(":", 1)[0].lower()


def is_creator_host(creator_host: str) -> bool:
    return bool(creator_host) and _host() == creator_host.lower()


def creator_path_allowed(path: str) -> bool:
    return (
        path in _CREATOR_API
        or path.rstrip("/") in _CREATOR_PAGES
        or path in _STATIC_FILES
        or path.startswith(_STATIC_PREFIXES)
    )


def install(app) -> None:
    """Register the gate. No-op unless CREATOR_HOST is configured."""

    @app.before_request
    def _creator_host_gate():
        creator_host = (app.config.get("CREATOR_HOST") or "").strip()
        if is_creator_host(creator_host) and not creator_path_allowed(request.path):
            return "Not found", 404, {"Cache-Control": "no-store"}
        return None
