"""Cobrand per-creator outcome data.

The existing `cobrand.py` scrapes the share-page __NEXT_DATA__ for
promotion-LEVEL aggregates only. This module hits Cobrand's submissions API
(`list_promotion_submissions`) to pull PER-CREATOR outcome metrics — the
shares/comments/engagement that actually signal whether a creator delivered
the outcome a label cares about, not just raw views.

Auth: the token embedded in the campaign's `cobrand_share_url` is all that's
needed (no separate API key) — same approach tidestracker uses.

NOTE on "saves": Cobrand's API exposes shares + comments + likes per
submission, but NOT a literal save count. For sound-UGC, shares (sound
spread) and comments (algorithmic reach) are the meaningful outcome proxies;
we surface those rather than fabricate a saves figure.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests

logger = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://api.cobrand.com/brand/v2/shareable/list_promotion_submissions"
_TIMEOUT = 20

# CAMP-66: per-promotion submission cache. fetch_submissions() does a paginated
# Cobrand API fetch keyed only by share_url — but the creator-intelligence
# outcome layer calls it once per (share-url campaign × creator dossier). Two
# dossiers each re-fetch all ~10 campaigns' full submission lists. Caching the
# fetch per share_url collapses that to one fetch per campaign per TTL window,
# regardless of how many creators are inspected.
_SUBMISSIONS_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECS = 600  # 10 min — outcome data doesn't move fast


def parse_share_link(share_url: str) -> Optional[Dict[str, str]]:
    """Pull promotion_id + token out of a Cobrand share URL.

    e.g. https://music.cobrand.com/promote/<promotion_id>/share/?token=<token>
    """
    if not share_url:
        return None
    try:
        parsed = urlparse(share_url)
        token = parse_qs(parsed.query).get("token", [""])[0]
        # promotion id is the path segment after /promote/
        parts = [p for p in parsed.path.split("/") if p]
        promotion_id = ""
        if "promote" in parts:
            i = parts.index("promote")
            if i + 1 < len(parts):
                promotion_id = parts[i + 1]
        if not promotion_id or not token:
            return None
        return {"promotion_id": promotion_id, "token": token}
    except (ValueError, IndexError):
        return None


def fetch_submissions(share_url: str, max_pages: int = 20) -> List[Dict[str, Any]]:
    """Cached wrapper around the paginated Cobrand fetch (CAMP-66).

    Returns the same submission list as before, but serves a cached copy
    when one was fetched within the TTL window — so opening many creator
    dossiers doesn't re-fetch the same campaign's submissions each time.
    """
    if not share_url:
        return []
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _SUBMISSIONS_CACHE.get(share_url)
        if hit and (now - hit[0]) < _CACHE_TTL_SECS:
            return hit[1]
    subs = _fetch_submissions_uncached(share_url, max_pages)
    # Only cache non-empty results so a transient failure doesn't poison the
    # cache for the whole TTL window.
    if subs:
        with _CACHE_LOCK:
            _SUBMISSIONS_CACHE[share_url] = (now, subs)
    return subs


def _fetch_submissions_uncached(share_url: str, max_pages: int = 20) -> List[Dict[str, Any]]:
    """Fetch all per-creator submissions for a campaign's Cobrand promotion.

    Returns a list of dicts: username, views, likes, comments, shares,
    engagement_rate, follower_count. Empty list on any failure (callers should
    degrade gracefully — outcome data is enrichment, not core).
    """
    parsed = parse_share_link(share_url)
    if not parsed:
        return []

    out: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    for _ in range(max_pages):
        payload: Dict[str, Any] = {
            "promotion_id": parsed["promotion_id"],
            "is_draft": False,
            "page_size": 100,
            "order_by": "social_content__play_count",
            "order_by_direction": "desc",
            "search": "",
        }
        if cursor:
            payload["cursor"] = cursor

        try:
            resp = requests.post(
                f"{SUBMISSIONS_URL}?token={parsed['token']}",
                json=payload,
                headers=headers,
                timeout=_TIMEOUT,
            )
            if not resp.ok:
                logger.warning("Cobrand submissions %s: %s", resp.status_code, resp.text[:200])
                break
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("Cobrand submissions fetch failed: %s", e)
            break

        for item in data.get("items", []):
            content = item.get("social_content")
            if not content:
                continue
            author = content.get("author") or {}
            views = content.get("play_count", 0) or 0
            likes = content.get("like_count", 0) or 0
            comments = content.get("comment_count", 0) or 0
            shares = content.get("share_count", 0) or 0
            eng = round((likes + comments + shares) / views * 100, 2) if views else 0.0
            out.append({
                "username": author.get("username", ""),
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "engagement_rate": eng,
                "follower_count": author.get("follower_count", 0) or 0,
                # CAMP-76: PFP + post thumbnail, served live (these are durable
                # storage.googleapis.com/cobrand-public URLs, refetched each
                # load — no signed-URL expiry, no storage build needed for v1).
                "avatar_url": author.get("avatar_url", "") or "",
                "cover_url": content.get("cover_url", "") or "",
            })

        links = data.get("links", {})
        if not links.get("has_next"):
            break
        cursor = links.get("next")
        if not cursor:
            break

    return out


def creator_outcomes(share_url: str, account: str) -> Optional[Dict[str, Any]]:
    """Aggregate outcome metrics for one creator within one campaign's promotion.

    Returns None if no Cobrand data is reachable or the creator has no
    submissions in that promotion.
    """
    norm = account.lstrip("@").lower()
    # Guard against an empty account matching every author-less submission
    # (Cobrand sometimes omits author handles, stored as "") — that would
    # attribute unrelated creators' outcomes to one phantom account.
    if not norm:
        return None
    subs = fetch_submissions(share_url)
    mine = [s for s in subs if s["username"].lstrip("@").lower() == norm]
    if not mine:
        return None

    total_views = sum(s["views"] for s in mine)
    total_likes = sum(s["likes"] for s in mine)
    total_comments = sum(s["comments"] for s in mine)
    total_shares = sum(s["shares"] for s in mine)
    # CAMP-86: follower_count is the only real per-creator follower number in
    # the system (the Creator table has none). Take the max across this
    # creator's submissions — their current/peak follower count.
    follower_count = max((s.get("follower_count", 0) for s in mine), default=0)
    # CAMP-76: PFP — first non-empty avatar_url across this creator's posts.
    avatar_url = next((s.get("avatar_url", "") for s in mine if s.get("avatar_url")), "")
    return {
        "posts": len(mine),
        "views": total_views,
        "likes": total_likes,
        "comments": total_comments,
        "shares": total_shares,
        "follower_count": follower_count,
        "avatar_url": avatar_url,
        "engagement_rate": round(
            (total_likes + total_comments + total_shares) / total_views * 100, 2
        ) if total_views else 0.0,
        # shares + comments = the outcome signal that matters for sound spread
        "outcome_score": total_shares + total_comments,
    }
