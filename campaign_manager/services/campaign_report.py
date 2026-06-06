"""Client-facing campaign report (CAMP-84).

Assembles a clean, shareable performance summary for a campaign — the surface
the agency hands to labels. Everything internal/financial (budget, rates,
payment status) is deliberately EXCLUDED; this is the outcome story:
headline reach, top-performing posts, and per-creator delivery with the
Cobrand sound-spread signal (shares/comments) labels actually care about.

Reuses the existing stats pipeline (campaign_stats) + cobrand_outcomes — no
new data, no new scrape.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_report(slug: str) -> Optional[Dict[str, Any]]:
    """Build the client report payload for a campaign, or None if not found."""
    from campaign_manager import db as _db
    from campaign_manager.services.campaign_stats import get_campaign_stats, overlay_video_stats
    from campaign_manager.utils.helpers import campaign_title

    if not _db.is_active():
        return None
    meta = _db.get_campaign(slug)
    if not meta:
        return None

    creators = _db.get_creators(slug)
    matched_videos = _db.get_matched_videos(slug)

    # Live stats overlay (Tides Tracker / Cobrand), same path the detail page uses.
    stats_result = get_campaign_stats(
        slug,
        matched_videos=matched_videos,
        tracker_id=meta.get("tracker_campaign_id"),
        start_date=meta.get("start_date", ""),
    )
    matched_videos = overlay_video_stats(matched_videos, stats_result.submissions)

    # Exclude dismissed (false-positive) matches from everything client-facing.
    live = [v for v in matched_videos if not v.get("dismissed_at")]

    total_views = sum(int(v.get("views", 0) or 0) for v in live)
    total_likes = sum(int(v.get("likes", 0) or 0) for v in live)

    # Top posts by views (the highlight reel).
    top_posts = sorted(live, key=lambda v: int(v.get("views", 0) or 0), reverse=True)[:10]
    top_posts_out = [
        {
            "url": v.get("url", ""),
            "account": v.get("account", ""),
            "views": int(v.get("views", 0) or 0),
            "likes": int(v.get("likes", 0) or 0),
            "upload_date": v.get("upload_date", ""),
        }
        for v in top_posts
    ]

    # Per-creator delivery: posts + views from matched data; Cobrand
    # shares/comments from the outcome layer where reachable.
    creator_rows = _per_creator(live, creators, meta.get("cobrand_share_url", ""))

    # Source / freshness badge (so a client knows how fresh the numbers are).
    source = getattr(stats_result, "source", "") or ""
    stale_since = getattr(stats_result, "stale_since", "") or ""

    return {
        "slug": slug,
        "title": campaign_title(meta),
        "artist": meta.get("artist", ""),
        "song": meta.get("song", ""),
        "start_date": meta.get("start_date", ""),
        "headline": {
            "total_views": total_views,
            "total_likes": total_likes,
            "post_count": len(live),
            "creator_count": len([c for c in creators if c.get("status", "active") != "removed"]),
        },
        "top_posts": top_posts_out,
        "creators": creator_rows,
        "source": source,
        "stale_since": stale_since,
    }


def _per_creator(
    live_videos: List[Dict[str, Any]],
    creators: List[Dict[str, Any]],
    cobrand_share_url: str,
) -> List[Dict[str, Any]]:
    """Per-creator rollup: posts + views from matched data, enriched with
    Cobrand shares/comments when the campaign exposes a share URL."""
    # views/posts per account from matched videos
    by_account: Dict[str, Dict[str, int]] = {}
    for v in live_videos:
        acct = (v.get("account", "") or "").lstrip("@").lower()
        if not acct:
            continue
        row = by_account.setdefault(acct, {"posts": 0, "views": 0, "likes": 0})
        row["posts"] += 1
        row["views"] += int(v.get("views", 0) or 0)
        row["likes"] += int(v.get("likes", 0) or 0)

    # Cobrand outcomes (shares/comments) keyed by account, best-effort.
    outcomes_by_account: Dict[str, Dict[str, Any]] = {}
    if cobrand_share_url:
        try:
            from campaign_manager.services.cobrand_outcomes import fetch_submissions
            for sub in fetch_submissions(cobrand_share_url):
                acct = (sub.get("username", "") or "").lstrip("@").lower()
                if not acct:
                    continue
                o = outcomes_by_account.setdefault(acct, {"shares": 0, "comments": 0})
                o["shares"] += int(sub.get("shares", 0) or 0)
                o["comments"] += int(sub.get("comments", 0) or 0)
        except Exception:
            logger.debug("campaign_report: cobrand outcomes unavailable for %s", cobrand_share_url, exc_info=True)

    # Build rows for booked creators (so the report reflects the roster, not
    # just whoever was matched). Match on username.
    rows: List[Dict[str, Any]] = []
    for c in creators:
        if c.get("status", "active") == "removed":
            continue
        uname = (c.get("username", "") or "").strip()
        if not uname:
            continue
        key = uname.lstrip("@").lower()
        mv = by_account.get(key, {"posts": 0, "views": 0, "likes": 0})
        oc = outcomes_by_account.get(key, {})
        rows.append({
            "username": uname,
            "posts": mv["posts"],
            "views": mv["views"],
            "likes": mv["likes"],
            "shares": oc.get("shares", 0),
            "comments": oc.get("comments", 0),
        })

    rows.sort(key=lambda r: r["views"], reverse=True)
    return rows
