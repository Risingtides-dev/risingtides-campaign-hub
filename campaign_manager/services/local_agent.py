"""Delegate on-demand scrapes to the local scraper node (John's Mac).

Railway's IP gets TikTok-blocked, so the real scraper runs on a Mac via a
token-gated webhook (tools/yt-scraper/pi_control_server.py, exposed over a
Tailscale Funnel). When LOCAL_AGENT_URL is set, the Hub's "Run now" forwards
here instead of scraping on Railway — which also means a stray POST to the
trigger endpoint can't spin up a blocked Railway run.

Env:
    LOCAL_AGENT_URL    e.g. https://mac-mini.tail168656.ts.net:8443
    LOCAL_AGENT_TOKEN  shared secret (== the node's PI_CONTROL_TOKEN)
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def is_configured() -> bool:
    return bool(os.environ.get("LOCAL_AGENT_URL", "").strip())


def dispatch_scrape(only_slugs=None) -> dict:
    """POST a 'scrape' action to the local node. Returns a JSON-able dict.

    `ok` is True when the node accepted the request. Never raises — a dead/
    offline Mac comes back as {"ok": False, "error": ...} so the caller can
    surface "local scraper offline" instead of 500ing.
    """
    base = os.environ.get("LOCAL_AGENT_URL", "").strip().rstrip("/")
    token = os.environ.get("LOCAL_AGENT_TOKEN", "").strip()
    if not base:
        return {"ok": False, "error": "LOCAL_AGENT_URL not set"}

    url = f"{base}/api/run-now?token={urllib.parse.quote(token)}"
    payload = json.dumps({"action": "scrape", "slugs": list(only_slugs or [])}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
        return {"ok": True, "delegated_to": "local_agent", "node": body}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"local scraper unreachable: {exc}",
            "hint": "Is the Mac on with the control server + Tailscale funnel up?",
        }
