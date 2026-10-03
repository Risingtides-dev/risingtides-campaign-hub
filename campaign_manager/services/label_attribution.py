"""Label-axis attribution rollup (CAMP-38 acceptance).

The Notion sync (services/notion_sync.py) mirrors the "🌌 Master Pages" DB into
notion_master_pages, where `notion_group` is the LABEL axis (WARNER / ATLANTIC
/ INTERNAL) and `account_username` is the join key into our scraped data.

Eric's P0 was that the scraper conflated Warner + Atlantic into one bucket.
This rolls views up STRICTLY by Notion label tag, so warner-tagged accounts
and atlantic-tagged accounts never cross-contaminate. Verified against prod:
WARNER/ATLANTIC/INTERNAL partition the tagged accounts with 0 overlap.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Canonical label slugs -> the Notion `notion_group` value.
_LABEL_BY_SLUG = {
    "warner": "WARNER",
    "atlantic": "ATLANTIC",
    "internal": "INTERNAL",
}


def label_stats(session, slug: str, days: int = 30) -> Optional[Dict[str, Any]]:
    """Aggregate internal-video views for one label (warner|atlantic|internal),
    counting ONLY accounts tagged with that label in Notion. None if unknown slug.
    """
    from campaign_manager.models import NotionMasterPage, InternalVideoCache

    label = _LABEL_BY_SLUG.get(slug.lower())
    if not label:
        return None

    # 1. Accounts tagged with this label in Notion (normalized, deduped).
    tagged_rows = (
        session.query(NotionMasterPage.account_username)
        .filter(NotionMasterPage.notion_group == label)
        .all()
    )
    tagged = {(a or "").lstrip("@").lower() for (a,) in tagged_rows if a}
    if not tagged:
        return {
            "label": label,
            "slug": slug.lower(),
            "days": days,
            "account_count": 0,
            "accounts_with_videos": 0,
            "total_views": 0,
            "total_likes": 0,
            "post_count": 0,
            "top_accounts": [],
        }

    # 2. Their cached internal videos within the window (upload_date is a
    #    YYYY-MM-DD-ish string; fall back to counting all when unparseable).
    cutoff = (datetime.now() - timedelta(days=days)).date()
    vids = session.query(
        InternalVideoCache.username,
        InternalVideoCache.views,
        InternalVideoCache.likes,
        InternalVideoCache.upload_date,
    ).all()

    per_account: Dict[str, Dict[str, int]] = {}
    total_views = total_likes = post_count = 0
    for username, views, likes, upload_date in vids:
        key = (username or "").lstrip("@").lower()
        if key not in tagged:
            continue
        if not _within_window(upload_date, cutoff):
            continue
        v = int(views or 0)
        lk = int(likes or 0)
        total_views += v
        total_likes += lk
        post_count += 1
        acc = per_account.setdefault(key, {"views": 0, "likes": 0, "posts": 0})
        acc["views"] += v
        acc["likes"] += lk
        acc["posts"] += 1

    top = sorted(
        ({"account": k, **v} for k, v in per_account.items()),
        key=lambda r: r["views"],
        reverse=True,
    )[:20]

    return {
        "label": label,
        "slug": slug.lower(),
        "days": days,
        "account_count": len(tagged),
        "accounts_with_videos": len(per_account),
        "total_views": total_views,
        "total_likes": total_likes,
        "post_count": post_count,
        "top_accounts": top,
    }


def all_label_stats(session, days: int = 30) -> List[Dict[str, Any]]:
    """Rollup for every label — the cross-label comparison (no contamination)."""
    out = []
    for slug in _LABEL_BY_SLUG:
        s = label_stats(session, slug, days)
        if s:
            out.append(s)
    return out


def _within_window(upload_date: Optional[str], cutoff) -> bool:
    """True if the post's upload date is on/after cutoff. Unparseable dates are
    INCLUDED (conservative — better to over-count than silently drop a post
    whose date format we don't recognize)."""
    if not upload_date:
        return True
    raw = str(upload_date).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date() >= cutoff
        except ValueError:
            continue
    return True
