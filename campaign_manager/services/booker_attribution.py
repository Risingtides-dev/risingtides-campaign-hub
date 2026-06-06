"""Booker-axis attribution rollup (CAMP-34, the complement to label_attribution).

The Notion `poster` field is the BOOKER axis — who books each page. Unlike the
label axis it is FREE TEXT and not normalized in Notion: the same person shows
up as "Eric Cromartie", "eric", "eric ", "Eric" (4 variants splitting one
roster). So the real work here is canonicalizing the booker name into a stable
slug BEFORE aggregating — a naive group-by raw `poster` fragments each booker's
numbers across several buckets.

Verified against prod: normalization collapses Eric's 4 variants -> one
`eric_cromartie` bucket (13 pages), Johnny's 3 -> `johnny_balik` (5), etc.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from campaign_manager.services.label_attribution import _within_window

logger = logging.getLogger(__name__)

# First-name / known-alias collapse. Keys are already lowercased + whitespace
# collapsed; values are the canonical full name.
_BOOKER_ALIASES = {
    "eric": "eric cromartie",
    "jake": "jake balik",
}
_UNASSIGNED = {"no poster", "none", "", "n/a", "-"}


def booker_slug(name: Optional[str]) -> str:
    """Canonical slug for a free-text Notion `poster` value. '' = unassigned."""
    if not name:
        return ""
    n = re.sub(r"\s+", " ", name.strip().lower())
    if n in _UNASSIGNED:
        return ""
    n = _BOOKER_ALIASES.get(n, n)
    return re.sub(r"[^a-z0-9]+", "_", n).strip("_")


def booker_stats(session, slug: str, days: int = 30) -> Optional[Dict[str, Any]]:
    """Roll up internal-video views for one booker's roster (by normalized
    `poster`), within the day window. None if the slug matches no pages."""
    from campaign_manager.models import NotionMasterPage, InternalVideoCache

    want = slug.lower().strip()
    if not want:
        return None

    # 1. Accounts this booker is responsible for (normalized poster == slug),
    #    keeping each account's label for the per-label breakdown.
    accounts: Dict[str, str] = {}  # normalized account -> its label
    display_name = None
    rows = session.query(
        NotionMasterPage.account_username,
        NotionMasterPage.notion_group,
        NotionMasterPage.poster,
    ).all()
    for acct, group, poster in rows:
        if booker_slug(poster) != want:
            continue
        key = (acct or "").lstrip("@").lower()
        if key:
            accounts[key] = (group or "UNLABELED")
            # Prefer the longest raw variant as the display name (collapses
            # "eric"/"Eric" in favour of "Eric Cromartie").
            cand = (poster or "").strip()
            if cand and (display_name is None or len(cand) > len(display_name)):
                display_name = cand

    if not accounts:
        return None

    # 2. Sum their cached internal videos in the window, with a per-label split.
    cutoff = (datetime.now() - timedelta(days=days)).date()
    vids = session.query(
        InternalVideoCache.username,
        InternalVideoCache.views,
        InternalVideoCache.likes,
        InternalVideoCache.upload_date,
    ).all()

    total_views = total_likes = post_count = 0
    by_label: Dict[str, Dict[str, int]] = {}
    per_account: Dict[str, Dict[str, Any]] = {}
    for username, views, likes, upload_date in vids:
        key = (username or "").lstrip("@").lower()
        label = accounts.get(key)
        if label is None:
            continue
        if not _within_window(upload_date, cutoff):
            continue
        v = int(views or 0)
        lk = int(likes or 0)
        total_views += v
        total_likes += lk
        post_count += 1
        lab = by_label.setdefault(label, {"views": 0, "likes": 0, "posts": 0})
        lab["views"] += v
        lab["likes"] += lk
        lab["posts"] += 1
        acc = per_account.setdefault(key, {"account": key, "label": label, "views": 0, "likes": 0, "posts": 0})
        acc["views"] += v
        acc["likes"] += lk
        acc["posts"] += 1

    top = sorted(per_account.values(), key=lambda r: r["views"], reverse=True)[:25]

    return {
        "slug": want,
        "booker": display_name or want.replace("_", " ").title(),
        "days": days,
        "account_count": len(accounts),
        "accounts_with_videos": len(per_account),
        "total_views": total_views,
        "total_likes": total_likes,
        "post_count": post_count,
        "by_label": [{"label": k, **v} for k, v in sorted(by_label.items(), key=lambda x: -x[1]["views"])],
        "top_accounts": top,
    }


def list_bookers(session, days: int = 30) -> List[Dict[str, Any]]:
    """All bookers ranked by roster views — the unified RT-tracker view."""
    from campaign_manager.models import NotionMasterPage

    slugs = set()
    for (poster,) in session.query(NotionMasterPage.poster).distinct().all():
        sl = booker_slug(poster)
        if sl:
            slugs.add(sl)

    out = []
    for sl in slugs:
        st = booker_stats(session, sl, days)
        if st:
            out.append({
                "slug": st["slug"],
                "booker": st["booker"],
                "account_count": st["account_count"],
                "total_views": st["total_views"],
                "post_count": st["post_count"],
            })
    out.sort(key=lambda r: r["total_views"], reverse=True)
    return out
