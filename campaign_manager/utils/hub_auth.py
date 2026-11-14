"""Hub write-key guard for operator write routes.

Same shape as the payout admin guard (blueprints/payout_common.py
``admin_guard``): the key comes from ``HUB_WRITE_KEY``, the caller sends it in
``X-Hub-Write-Key``, comparison is constant-time on bytes, failures are
rate-limited per client IP, and a missing or short key FAILS CLOSED (503) —
the route never runs unauthenticated because configuration is absent.
"""
from __future__ import annotations

import functools
import hmac
import os

from flask import jsonify, request

from campaign_manager.utils.rate_limit import SlidingWindowLimiter, client_ip

HEADER = "X-Hub-Write-Key"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MIN_HUB_WRITE_KEY_LENGTH = 32

write_fail_limiter = SlidingWindowLimiter(max_events=10, window_seconds=600)


def configured_key() -> str:
    return (os.environ.get("HUB_WRITE_KEY") or "").strip()


def presented_key_valid() -> bool:
    """True only when a strong key is configured and the request carries it."""
    key = configured_key()
    if len(key) < MIN_HUB_WRITE_KEY_LENGTH:
        return False
    supplied = request.headers.get(HEADER, "")
    return hmac.compare_digest(supplied.encode("utf-8", "surrogateescape"), key.encode())


def hub_write_guard():
    """None when the caller may write; otherwise the error response."""
    key = configured_key()
    if len(key) < MIN_HUB_WRITE_KEY_LENGTH:
        return jsonify({
            "error": "Hub writes are disabled until a strong HUB_WRITE_KEY "
                     f"({MIN_HUB_WRITE_KEY_LENGTH}+ characters) is set.",
            "code": "hub_write_unconfigured",
        }), 503
    if not presented_key_valid():
        if not write_fail_limiter.allow(client_ip()):
            return jsonify({"error": "Too many attempts.", "code": "rate_limited"}), 429
        return jsonify({"error": f"{HEADER} required.", "code": "unauthorized"}), 401
    return None


def guard_mutating_methods():
    """``before_request`` hook for a blueprint whose every write needs the key."""
    if request.method in MUTATING_METHODS:
        return hub_write_guard()
    return None


def require_hub_write_key(view):
    """Decorator form of ``hub_write_guard`` for individual routes."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        denied = hub_write_guard()
        if denied is not None:
            return denied
        return view(*args, **kwargs)

    return wrapped


# ── App-wide gate (security-fix-1112 CH-F3) ─────────────────────────────────
#
# Every POST/PUT/PATCH/DELETE needs the Hub write key, EXCEPT endpoints that
# authenticate themselves with their own fail-closed mechanism:
#   - creator payout link routes: 256-bit body token + per-IP rate limit
#   - payout admin routes: PAYOUT_ADMIN_KEY (blueprints/payout_common.admin_guard)
#   - Slack events: Slack request signature (blueprints/slack_events.slack_events)
#   - Notion intake webhook: NOTION_WEBHOOK_SECRET (blueprints/webhooks.py)
# Reads (GET/HEAD) are unchanged by default so the control-plane Worker's two
# credential-less reads keep working; a few reads that only leak PII/debug
# data always need the key, and HUB_READ_KEY_REQUIRED=true gates the rest of
# /api/* reads (the Worker's two routes stay open even then).

SELF_AUTHENTICATED_ENDPOINTS = frozenset({
    "payouts.payout_lookup",
    "payouts.creator_dashboard",
    "payouts.payout_submit",
    "slack_events.slack_events",
    "webhooks.notion_webhook",
})
SELF_AUTHENTICATED_PREFIXES = ("payouts.admin_", "payout_batches.")

WORKER_READ_PATHS = frozenset({"/api/campaigns", "/api/campaigns/captions"})

ALWAYS_KEYED_READ_ENDPOINTS = frozenset({
    "campaigns.api_paypal",          # PayPal lookup by username
    "campaigns.get_cobrand_raw",     # debug dump; fetches a stored URL server-side
    "slack_events.slack_debug",      # booking-channel text, raw LLM output, tracebacks
})


def self_authenticated(endpoint: str | None) -> bool:
    endpoint = endpoint or ""
    return endpoint in SELF_AUTHENTICATED_ENDPOINTS or endpoint.startswith(SELF_AUTHENTICATED_PREFIXES)


def read_gate_enabled() -> bool:
    return (os.environ.get("HUB_READ_KEY_REQUIRED") or "").strip().lower() in ("1", "true", "yes")


def _gate_decision():
    method = request.method
    if method == "OPTIONS":
        return None  # CORS preflight carries no credentials
    endpoint = request.endpoint
    if method in MUTATING_METHODS:
        if self_authenticated(endpoint):
            return None
        return hub_write_guard()
    if endpoint in ALWAYS_KEYED_READ_ENDPOINTS:
        return hub_write_guard()
    if (read_gate_enabled() and request.path.startswith("/api/")
            and request.path not in WORKER_READ_PATHS and not self_authenticated(endpoint)):
        return hub_write_guard()
    return None


def install_write_gate(app) -> None:
    """Register the app-wide gate. Always on; fails closed without HUB_WRITE_KEY."""
    app.before_request(_gate_decision)
