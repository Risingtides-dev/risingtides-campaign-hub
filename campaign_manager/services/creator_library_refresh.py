"""Refresh Creator Library performance from the Tides Trackers.

The Hub overlays live tracker stats onto matched videos, but only for
campaigns that aren't marked complete — completed campaigns deliberately
skip the fetch on the grounds that their numbers are final. They aren't:
TikTok views keep climbing for weeks, so a campaign closed a few days after
posting freezes an undercount permanently. Measured against live tracker
data the gap ran about 4x across the roster, and individual posts were out
by an order of magnitude (one read 177,500 in the Hub against 1,058,471
live).

This job walks every tracker, dedupes posts across campaigns, and caches
per-creator windows on `CreatorProfile.stats`. It writes only the
performance fields, so tags, rates and notes are untouched.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from campaign_manager.models import Campaign, CreatorProfile
from campaign_manager.services.creator_library import (
    get_or_create_profile,
    normalize_username,
)
from campaign_manager.services.creator_library_stats import (
    build_windows,
    dedupe_posts,
)

log = logging.getLogger(__name__)

# Concurrent tracker fetches. Bounded well below the tracker API's comfort
# level — this is one internal service politely reading another, not a
# reason to hammer it.
DEFAULT_FETCH_WORKERS = 12

Row = Tuple[str, date, int]


def _parse_published(value) -> Optional[date]:
    """Tracker timestamps are ISO-8601; we only need the calendar day."""
    text = str(value or "")[:10]
    if len(text) != 10:
        return None
    try:
        return date(int(text[:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, TypeError):
        return None


def extract_rows(
    videos: Sequence[Dict],
) -> Tuple[Dict[str, List[Row]], Dict[str, int], Dict[str, Tuple[date, str]]]:
    """Turn a tracker payload into per-creator rows, followers and covers.

    Returns:
        ({username: [(url, date, views)]},
         {username: followers},
         {username: (date, cover_url)})

    Entries without a parseable date are dropped — they cannot be placed in
    a window, and guessing would corrupt the recency signal that the whole
    ranking depends on.
    """
    rows: Dict[str, List[Row]] = {}
    followers: Dict[str, int] = {}
    covers: Dict[str, Tuple[date, str]] = {}

    for video in videos or []:
        username = normalize_username(video.get("username"))
        if not username:
            continue

        published = _parse_published(video.get("published_at"))
        if published is None:
            continue

        url = video.get("video_url") or video.get("url") or ""
        views = int(video.get("views") or 0)
        rows.setdefault(username, []).append((url, published, views))

        count = int(video.get("author_followers") or 0)
        if count > followers.get(username, 0):
            followers[username] = count

        # Newest post's cover stands in for a profile picture.
        cover = video.get("cover_url") or ""
        if cover:
            current = covers.get(username)
            if current is None or published > current[0]:
                covers[username] = (published, cover)

    return rows, followers, covers


def collect_tracker_ids(session, list_trackers: Optional[Callable] = None) -> List[str]:
    """Every tracker UUID worth walking.

    Two sources, because neither is complete on its own:

    * `Campaign.tracker_campaign_id` — trackers linked to a Hub campaign.
      Completed campaigns are the whole point of this job, so unlike the
      read-time overlay we deliberately do not filter them out.
    * The TidesTracker campaign list — trackers that exist but were never
      linked back to a Hub campaign. In production that was the difference
      between 148 and 255 trackers, i.e. most of a creator's history.

    The remote list is best-effort: if it fails we still walk everything
    the Hub knows about locally rather than aborting the run.
    """
    seen: List[str] = []
    known = set()

    def add(value) -> None:
        cleaned = (value or "").strip()
        if cleaned and cleaned not in known:
            known.add(cleaned)
            seen.append(cleaned)

    for (tracker_id,) in session.query(Campaign.tracker_campaign_id).all():
        add(tracker_id)

    if list_trackers is None:
        try:
            from campaign_manager.services.tidestracker import list_tracker_campaigns

            list_trackers = list_tracker_campaigns
        except Exception:  # pragma: no cover - import guard
            list_trackers = None

    if list_trackers is not None:
        try:
            for tracker in list_trackers() or []:
                add(tracker.get("id"))
        except Exception as exc:
            log.warning("library refresh: tracker list unavailable (%s)", exc)

    return seen


def _default_fetch(tracker_id: str) -> List[Dict]:
    from campaign_manager.services.tidestracker import get_tracked_videos

    result = get_tracked_videos(tracker_id, force=True)
    return result.get("raw_videos") or []


def refresh_creator_stats(
    session,
    fetch_videos: Optional[Callable[[str], Sequence[Dict]]] = None,
    tracker_ids: Optional[Sequence[str]] = None,
    today: Optional[date] = None,
    max_workers: int = DEFAULT_FETCH_WORKERS,
) -> Dict:
    """Rebuild cached performance windows for every creator on a tracker.

    `fetch_videos` is injectable so this can be tested without network and
    driven from a cron job in production.

    Tracker fetches run concurrently. Sequentially, ~255 trackers at up to
    15s each overran gunicorn's 120s worker timeout and the request died
    with a 500; the work is pure network wait, so a small pool collapses it
    to well under a minute.

    Returns a summary suitable for a cron log:
        {trackers, failed, creators, posts, updated_at}
    """
    fetch = fetch_videos or _default_fetch
    ids = list(tracker_ids) if tracker_ids is not None else collect_tracker_ids(session)
    today = today or date.today()

    all_rows: Dict[str, List[Row]] = {}
    followers: Dict[str, int] = {}
    covers: Dict[str, Tuple[date, str]] = {}
    failed = 0

    def _safe_fetch(tracker_id: str):
        try:
            return tracker_id, fetch(tracker_id) or [], None
        except Exception as exc:  # noqa: BLE001 — reported per tracker below
            return tracker_id, [], exc

    if ids:
        workers = max(1, min(max_workers, len(ids)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_safe_fetch, ids))
    else:
        results = []

    for tracker_id, videos, error in results:
        if error is not None:
            # One unreachable tracker must not cost us the other 250.
            failed += 1
            log.warning("library refresh: tracker %s failed: %s", tracker_id, error)
            continue

        rows, counts, shots = extract_rows(videos)
        for username, items in rows.items():
            all_rows.setdefault(username, []).extend(items)
        for username, count in counts.items():
            if count > followers.get(username, 0):
                followers[username] = count
        for username, shot in shots.items():
            current = covers.get(username)
            if current is None or shot[0] > current[0]:
                covers[username] = shot

    stamped = datetime.now()
    posts_seen = 0

    for username, rows in all_rows.items():
        deduped = dedupe_posts(rows)
        posts_seen += len(deduped)

        # No rate here on purpose: CPM is derived at read time from the
        # creator's current rate, so an edited rate takes effect at once.
        windows = build_windows(deduped, today=today, rate=None)

        profile = get_or_create_profile(session, username, commit=False)
        profile.stats = windows
        profile.stats_updated_at = stamped
        if followers.get(username):
            profile.followers = followers[username]
        if covers.get(username):
            profile.avatar_url = covers[username][1]

    session.commit()

    return {
        "trackers": len(ids) - failed,
        "failed": failed,
        "creators": len(all_rows),
        "posts": posts_seen,
        "updated_at": stamped.isoformat(),
    }


# ── cron entry point ───────────────────────────────────────────────────

# Six hours by default. View counts climb over days, not minutes, and each
# run costs one HTTP call per tracker (~255 today), so anything tighter
# spends real time to move numbers that have barely changed.
DEFAULT_INTERVAL_MINUTES = 360


def get_library_stats_interval_minutes() -> int:
    try:
        value = int(os.environ.get("LIBRARY_STATS_INTERVAL_MINUTES", ""))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_MINUTES
    return value if value > 0 else DEFAULT_INTERVAL_MINUTES


def run_library_stats_refresh() -> Dict:
    """Scheduled refresh, wrapped in a cron log so failures are visible."""
    from campaign_manager import db as _db

    if not _db.is_active():
        return {"skipped": "database not active"}

    log_id = _db.create_cron_log("library_stats")
    session = _db.get_session()
    try:
        summary = refresh_creator_stats(session)
        _db.finish_cron_log(log_id, "completed", summary)
        log.info("library stats refresh: %s", summary)
        return summary
    except Exception as exc:
        log.exception("library stats refresh failed")
        _db.finish_cron_log(log_id, "failed", {"error": str(exc)})
        raise
    finally:
        session.close()
