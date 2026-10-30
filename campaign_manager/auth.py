"""App-wide API auth gate (CAMP-96) — STAGED, OFF BY DEFAULT.

The app currently ships with no authentication (sweep #6). This module adds a
shared-secret gate that protects the JSON API — but it is **disabled unless
``APP_API_KEY`` is set in the environment**, so merging/deploying this changes
NOTHING until an operator deliberately turns it on. That's the safety property:
it is impossible to accidentally lock anyone out by shipping this code.

When APP_API_KEY IS set, every ``/api/*`` request must present the key via the
``X-API-Key`` header (or ``?api_key=`` query param, for share-style links),
compared in constant time. Exempt paths:
  - ``/health``                — Railway healthcheck must stay open
  - the SPA + static assets    — anything not under ``/api/``
  - ``/api/share/``            — the intentionally-public client-report path
                                 (CAMP-97); read-only, financial-free

Frontend wiring (sending the key) is a SEPARATE step the operator does when
enabling — see CAMP-96. Until APP_API_KEY is set, none of this runs.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Optional

from flask import Flask, jsonify, request

log = logging.getLogger(__name__)

# Paths that must remain reachable WITHOUT the key even when the gate is on.
_EXEMPT_PREFIXES = (
    "/health",
    "/api/share/",   # CAMP-97: the one intentionally-public, read-only surface
)


def _configured_key() -> Optional[str]:
    key = os.environ.get("APP_API_KEY", "").strip()
    return key or None


def _presented_key() -> str:
    # Header first, then a query param (for shareable links / curl convenience).
    return (request.headers.get("X-API-Key") or request.args.get("api_key") or "")


def install_auth_gate(app: Flask) -> None:
    """Register the before_request gate. No-op at request time unless APP_API_KEY
    is set, so installing it is always safe."""
    enabled = _configured_key() is not None
    log.info("API auth gate installed (enabled=%s — set APP_API_KEY to enable)", enabled)

    @app.before_request
    def _require_api_key():  # noqa: ANN202
        configured = _configured_key()
        if configured is None:
            return None  # gate disabled — current behavior, no change

        path = request.path or ""
        # Only the JSON API is gated; the SPA + static assets stay open so the
        # app shell can load (it will then send the key on its API calls).
        if not path.startswith("/api/"):
            return None
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return None
        # CORS preflight must pass through.
        if request.method == "OPTIONS":
            return None

        presented = _presented_key()
        if presented and hmac.compare_digest(presented, configured):
            return None

        return jsonify({"error": "Unauthorized — missing or invalid API key."}), 401
