"""Shared plumbing for the payout blueprints: admin-key guard, rate
limiters, no-store JSON responses, log-safe DB errors."""
from __future__ import annotations

import hmac
import logging

from flask import current_app, jsonify, request

from campaign_manager import db as _db
from campaign_manager.utils.rate_limit import SlidingWindowLimiter, client_ip

log = logging.getLogger("campaign_manager.blueprints.payouts")

# Generous for a real creator (open page, fix a typo, resubmit), useless
# for guessing 256-bit tokens.
public_limiter = SlidingWindowLimiter(max_events=30, window_seconds=600)
admin_fail_limiter = SlidingWindowLimiter(max_events=10, window_seconds=600)

MAX_LINK_BATCH = 500
MIN_ADMIN_KEY_LENGTH = 32
_INVALID_LINK = "This link isn't valid anymore. Message us and we'll send you a fresh one."


def no_store(response, status=200):
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def json_response(payload, status=200):
    return no_store(jsonify(payload), status)


def db_unavailable():
    return json_response({"error": "Service unavailable. Try again in a minute."}, 503)


def db_error(where: str, exc: Exception):
    # Type name only: SQLAlchemy error text can include bound values
    # (tokens, destinations) — those must never reach the logs.
    log.error("payout %s failed: %s", where, type(exc).__name__)
    return db_unavailable()


def request_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def admin_guard():
    key = (current_app.config.get("PAYOUT_ADMIN_KEY") or "").strip()
    if len(key) < MIN_ADMIN_KEY_LENGTH:
        return json_response({"error": "Payout admin is disabled until a strong PAYOUT_ADMIN_KEY "
                               f"({MIN_ADMIN_KEY_LENGTH}+ characters) is set.",
                      "code": "payout_admin_unconfigured"}, 503)
    ip = client_ip()
    supplied = request.headers.get("X-Payout-Admin-Key", "")
    if not hmac.compare_digest(supplied.encode(), key.encode()):
        if not admin_fail_limiter.allow(ip):
            return json_response({"error": "Too many attempts.", "code": "rate_limited"}, 429)
        return json_response({"error": "Admin key required.", "code": "unauthorized"}, 401)
    if not _db.is_active():
        return db_unavailable()
    return None
