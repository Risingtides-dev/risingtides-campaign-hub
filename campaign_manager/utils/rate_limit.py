"""Small in-process sliding-window rate limiter.

Per gunicorn worker (4 in prod), so the effective ceiling is ~4x the
configured limit. That's fine for its job — slowing token guessing on the
public payout endpoints — because tokens are 256-bit and unguessable anyway.
No new dependency, no Redis.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from flask import request


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float, max_keys: int = 10_000):
        self.max_events = max_events
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record a hit for `key`; False if it is over the limit."""
        now = time.monotonic() if now is None else now
        cutoff = now - self.window
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self.max_keys:
                    self._prune(cutoff)
                hits = self._hits[key] = deque()
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.max_events:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _prune(self, cutoff: float) -> None:
        stale = [k for k, h in self._hits.items() if not h or h[-1] <= cutoff]
        for k in stale:
            del self._hits[k]
        if len(self._hits) >= self.max_keys:
            # Still full of active keys: drop the oldest-touched half.
            ordered = sorted(self._hits.items(), key=lambda kv: kv[1][-1])
            for k, _ in ordered[: len(ordered) // 2]:
                del self._hits[k]


def client_ip() -> str:
    """Best-effort client IP behind Railway's proxy.

    Uses the RIGHTMOST X-Forwarded-For entry — the one Railway's edge
    appended. Leftmost entries are client-supplied and trivially spoofed.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.remote_addr or "unknown"
