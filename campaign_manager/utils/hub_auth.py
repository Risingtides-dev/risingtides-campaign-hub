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
