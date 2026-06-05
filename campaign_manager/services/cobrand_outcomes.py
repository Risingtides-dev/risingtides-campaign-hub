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
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import requests

logger = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://api.cobrand.com/brand/v2/shareable/list_promotion_submissions"
_TIMEOUT = 20


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
    subs = fetch_submissions(share_url)
    mine = [s for s in subs if s["username"].lstrip("@").lower() == norm]
    if not mine:
        return None

    total_views = sum(s["views"] for s in mine)
    total_likes = sum(s["likes"] for s in mine)
    total_comments = sum(s["comments"] for s in mine)
    total_shares = sum(s["shares"] for s in mine)
    return {
        "posts": len(mine),
        "views": total_views,
        "likes": total_likes,
        "comments": total_comments,
        "shares": total_shares,
        "engagement_rate": round(
            (total_likes + total_comments + total_shares) / total_views * 100, 2
        ) if total_views else 0.0,
        # shares + comments = the outcome signal that matters for sound spread
        "outcome_score": total_shares + total_comments,
    }
