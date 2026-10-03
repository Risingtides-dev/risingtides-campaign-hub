"""Per-creator unified rollup (CAMP-34, endpoint #1).

"Everything this creator did — internal pages + external campaigns — in one
view." The Creator Intelligence drilldown already tells the external
sound-breaking story; this unions it with the creator's INTERNAL page activity
(InternalVideoCache) so a profile can show total reach across both worlds.

Internal side: videos this account posted on internal pages (InternalVideoCache,
keyed by username) — enriched with the Notion label tag where known.
External side: matched campaign videos (MatchedVideo, keyed by account),
grouped by campaign.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def creator_rollup(session, username: str, days: int = 90) -> Dict[str, Any]:
    """Union a creator's internal + external video activity within the window."""
    from campaign_manager.models import (
        InternalVideoCache,
        MatchedVideo,
        Campaign,
        NotionMasterPage,
    )
    from campaign_manager.services.label_attribution import _within_window

    norm = username.lstrip("@").lower()
    cutoff = (datetime.now() - timedelta(days=days)).date()

    # ---- INTERNAL: pages this account posts on ----
    internal_rows = (
        session.query(
            InternalVideoCache.views,
            InternalVideoCache.likes,
            InternalVideoCache.upload_date,
            InternalVideoCache.song,
            InternalVideoCache.artist,
        )
        .filter(func_lower_strip(InternalVideoCache.username) == norm)
        .all()
    ) if _exists(session) else []

    internal_views = internal_likes = internal_posts = 0
    for views, likes, upload_date, _song, _artist in internal_rows:
        if not _within_window(upload_date, cutoff):
            continue
        internal_views += int(views or 0)
        internal_likes += int(likes or 0)
        internal_posts += 1

    # Label tag for this account (from Notion), if it's an internal page.
    label = None
    page = (
        session.query(NotionMasterPage.notion_group)
        .filter(func_lower_strip(NotionMasterPage.account_username) == norm)
        .first()
    )
    if page:
        label = page[0]

    # ---- EXTERNAL: matched campaign videos, grouped by campaign ----
    ext_rows = (
        session.query(
            MatchedVideo.campaign_id,
            MatchedVideo.views,
            MatchedVideo.likes,
            MatchedVideo.upload_date,
        )
        .filter(func_lower_strip(MatchedVideo.account) == norm)
        .filter(MatchedVideo.dismissed_at.is_(None))
        .all()
    )

    by_campaign: Dict[int, Dict[str, int]] = {}
    external_views = external_likes = external_posts = 0
    for campaign_id, views, likes, upload_date in ext_rows:
        if not _within_window(upload_date, cutoff):
            continue
        v = int(views or 0)
        lk = int(likes or 0)
        external_views += v
        external_likes += lk
        external_posts += 1
        c = by_campaign.setdefault(campaign_id, {"views": 0, "likes": 0, "posts": 0})
        c["views"] += v
        c["likes"] += lk
        c["posts"] += 1

    # Resolve campaign names for the external breakdown.
    campaigns_out: List[Dict[str, Any]] = []
    if by_campaign:
        camp_names = dict(
            session.query(Campaign.id, Campaign.slug)
            .filter(Campaign.id.in_(list(by_campaign.keys())))
            .all()
        )
        for cid, stats in by_campaign.items():
            campaigns_out.append({
                "campaign_id": cid,
                "slug": camp_names.get(cid, str(cid)),
                **stats,
            })
        campaigns_out.sort(key=lambda r: r["views"], reverse=True)

    return {
        "username": norm,
        "days": days,
        "label": label,
        "totals": {
            "views": internal_views + external_views,
            "likes": internal_likes + external_likes,
            "posts": internal_posts + external_posts,
        },
        "internal": {
            "views": internal_views,
            "likes": internal_likes,
            "posts": internal_posts,
            "label": label,
        },
        "external": {
            "views": external_views,
            "likes": external_likes,
            "posts": external_posts,
            "campaigns": campaigns_out,
        },
    }


# --- small helpers (case/@-insensitive joins without importing func everywhere) ---
def func_lower(col):
    from sqlalchemy import func
    return func.lower(col)


def func_lower_strip(col):
    from sqlalchemy import func
    return func.lower(func.replace(col, "@", ""))


def _exists(session) -> bool:
    """InternalVideoCache may be empty/absent in some envs — guard defensively."""
    try:
        from campaign_manager.models import InternalVideoCache
        session.query(InternalVideoCache.id).limit(1).all()
        return True
    except Exception:
        return False
