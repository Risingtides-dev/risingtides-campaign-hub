"""Campaign stats read-through wrapper (RTA-43).

The single source of truth for per-campaign performance numbers (views,
likes, comments, shares, engagement, post URLs) is now the Tides Tracker
public API. This module hides the read path so blueprints don't care
where the bytes came from.

Read flow:

  1. Resolve a campaign slug -> tracker_id (campaigns.tracker_campaign_id
     first, then tracker_campaign_links overlay; mirrors
     `db.get_tracker_id_for_campaign`).
  2. If we have a tracker_id, ask the in-process cache. Fresh hits
     return immediately. Expired or missing entries trigger a single
     live `fetch_campaign_submissions(tracker_id)` call.
  3. On API success: cache the response, return submissions tagged
     `source="api"` with `fetched_at`.
  4. On API failure: serve the most recent cached entry (if any) with
     `source="api_cached"` and `stale_since=<cache_fetched_at>`.
  5. If no cache and the API errored — or the campaign has no tracker
     linked at all — fall back to scraper-populated `matched_videos`
     and synthesize a Submission-shaped record per row. Tagged
     `source="scraper_fallback"` with `stale_since` from
     `scrape_logs.last_scrape` when available.

The two fields the public API doesn't return yet (`follower_count` and
`posted_at`) are hydrated from the scraper data when the primary source
is the API — matched by `video_url`. Where the scraper also lacks a
value (no matching row), they degrade to `0` / `""` rather than
breaking the response shape. RTA-43 surfaces this gap; a future ticket
adds the columns to the API.

Cache TTL is `TIDES_TRACKER_CACHE_TTL_SECONDS` (env, default 300s).
The 30-minute cron from RTA-42 will keep this warm in practice, but
the short TTL means a manual refresh in the UI returns within one
HTTP round-trip rather than waiting for the next tick.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from campaign_manager import db as _db
from campaign_manager.utils.helpers import video_posted_before_start
from campaign_manager.services.tides_tracker import (
    Submission,
    fetch_campaign_submissions,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


_DEFAULT_CACHE_TTL_SECONDS = 300


def _cache_ttl_seconds() -> int:
    raw = os.environ.get("TIDES_TRACKER_CACHE_TTL_SECONDS", "")
    if not raw:
        return _DEFAULT_CACHE_TTL_SECONDS
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_CACHE_TTL_SECONDS
    # Negative or zero means "no caching" — handled by the freshness check.
    return n if n >= 0 else _DEFAULT_CACHE_TTL_SECONDS


@dataclass
class _CacheEntry:
    submissions: List[Submission]
    fetched_at: datetime  # UTC, monotonic enough for TTL freshness
    api_fetched_at: str   # the API's reported fetched_at string (echoed in responses)


_cache: Dict[str, _CacheEntry] = {}
_cache_lock = threading.Lock()


def _submissions_to_json(submissions: List[Submission]) -> list:
    from dataclasses import asdict
    return [asdict(s) for s in submissions]


def _submissions_from_json(rows) -> List[Submission]:
    out: List[Submission] = []
    for r in rows or []:
        try:
            out.append(Submission(**r))
        except (TypeError, ValueError):
            # Tolerate a schema drift in stored rows — skip the bad one rather
            # than poison the whole cached entry.
            continue
    return out


# ---------------------------------------------------------------------------
# Refresh attempt cooldown (per worker)
#
# A tracker whose upstream fetch fails — or exceeds the list endpoint's 5s
# prewarm timeout — never gets a cache write, so before this every single
# /api/campaigns request re-attempted it and burned the full timeout again.
# One slow tracker (sombr_june_release: 7.5s upstream, 262KB) held the whole
# campaigns page at ~5-7s for every user until the cron happened to rescue it.
# Record every live-fetch attempt; don't re-attempt the same tracker from the
# request path until the cooldown passes. Stale data (or scraper fallback)
# serves in the meantime — the 30-min cron with its 15s timeout remains the
# thing that actually heals slow trackers.
# ---------------------------------------------------------------------------

_REFRESH_COOLDOWN_SECONDS = 120
_refresh_attempts: Dict[str, datetime] = {}
_refresh_attempts_lock = threading.Lock()


def _in_cooldown(tracker_id: str) -> bool:
    with _refresh_attempts_lock:
        at = _refresh_attempts.get(tracker_id)
    if at is None:
        return False
    return (datetime.now(timezone.utc) - at).total_seconds() < _REFRESH_COOLDOWN_SECONDS


def _mark_attempt(tracker_id: str) -> None:
    with _refresh_attempts_lock:
        _refresh_attempts[tracker_id] = datetime.now(timezone.utc)


def _refresh_trackers_sync(tracker_ids: List[str], *, timeout: float) -> None:
    """Fetch + cache each tracker; failures are recorded, never raised."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not tracker_ids:
        return
    with ThreadPoolExecutor(max_workers=len(tracker_ids)) as ex:
        futures = {
            ex.submit(fetch_campaign_submissions, tid, timeout=timeout): tid
            for tid in tracker_ids
        }
        for fut in as_completed(futures):
            tid = futures[fut]
            try:
                fres = fut.result()
            except Exception:
                logger.exception(
                    "campaign_stats: refresh fetch raised for tracker %s", tid,
                )
                continue
            if not fres.ok:
                # Don't poison the cache with a failure; the cooldown mark
                # (set before dispatch) keeps request paths from re-burning
                # the timeout until it expires.
                continue
            _cache_set(tid, _CacheEntry(
                submissions=fres.submissions,
                fetched_at=datetime.now(timezone.utc),
                api_fetched_at=fres.fetched_at,
            ))


def _spawn_background_refresh(tracker_ids: List[str]) -> None:
    """Refresh stale-but-present trackers off the request thread.

    Uses the full 15s upstream timeout — the whole point is that trackers
    too slow for the list endpoint's 5s budget (the sombr class) can still
    heal here, instead of being permanently unwarmable from the request
    path. Tests monkeypatch this to run inline / record calls.
    """
    threading.Thread(
        target=_refresh_trackers_sync,
        args=(tracker_ids,),
        kwargs={"timeout": 15},
        daemon=True,
        name="tides-stats-bg-refresh",
    ).start()


def _cache_get(tracker_id: str) -> Optional[_CacheEntry]:
    # L1: fast in-process dict (per worker).
    with _cache_lock:
        entry = _cache.get(tracker_id)
    if entry is not None:
        return entry
    # L2: Postgres (CAMP-9) — survives redeploys + shared across workers. On an
    # L1 miss, hydrate from the DB so a fetch by any worker / pre-restart warms
    # this worker too. Best-effort; falls through to None if the DB is absent.
    try:
        from campaign_manager import db as _db
        hit = _db.get_tides_stats_cache(tracker_id)
        if hit is not None:
            submissions_json, api_fetched_at, fetched_at = hit
            entry = _CacheEntry(
                submissions=_submissions_from_json(submissions_json),
                fetched_at=fetched_at,
                api_fetched_at=api_fetched_at,
            )
            with _cache_lock:
                _cache[tracker_id] = entry  # promote into L1
            return entry
    except Exception:
        pass
    return None


def _cache_set(tracker_id: str, entry: _CacheEntry) -> None:
    # Write-through: L1 in-process + L2 Postgres.
    with _cache_lock:
        _cache[tracker_id] = entry
    try:
        from campaign_manager import db as _db
        _db.upsert_tides_stats_cache(
            tracker_id,
            _submissions_to_json(entry.submissions),
            entry.api_fetched_at,
            entry.fetched_at,
        )
    except Exception:
        pass


def warm_cache(tracker_id: str, submissions, api_fetched_at: str = "") -> None:
    """Public write-through so the Tides Tracker cron can warm the request-path
    cache (CAMP-74). The cron already fetches each tracker's submissions for
    its audit log; calling this keeps the in-process read cache that
    get_campaign_stats() consults warm across the 30-min tick, instead of going
    cold after every redeploy. No-op on falsy tracker_id.
    """
    if not tracker_id:
        return
    _cache_set(
        tracker_id,
        _CacheEntry(
            submissions=submissions,
            fetched_at=datetime.now(timezone.utc),
            api_fetched_at=api_fetched_at,
        ),
    )


def _is_fresh(entry: _CacheEntry, ttl_seconds: int) -> bool:
    if ttl_seconds <= 0:
        return False
    age = (datetime.now(timezone.utc) - entry.fetched_at).total_seconds()
    return age < ttl_seconds


def invalidate_cache(tracker_id: Optional[str] = None) -> None:
    """Drop one tracker's cached entry, or the whole cache.

    Also clears the matching refresh-attempt cooldown marks: a caller
    invalidating a tracker wants the next read to actually go live, not
    to sit out the rest of a cooldown started by an earlier attempt.
    (The test suite's autouse cache reset relies on this too.)
    """
    with _cache_lock:
        if tracker_id is None:
            _cache.clear()
        else:
            _cache.pop(tracker_id, None)
    with _refresh_attempts_lock:
        if tracker_id is None:
            _refresh_attempts.clear()
        else:
            _refresh_attempts.pop(tracker_id, None)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


SOURCE_API = "api"
SOURCE_API_CACHED = "api_cached"
SOURCE_SCRAPER_FALLBACK = "scraper_fallback"
SOURCE_EMPTY = "empty"


@dataclass
class CampaignStatsResult:
    """Per-campaign performance numbers + provenance.

    `source` is one of: ``api``, ``api_cached``, ``scraper_fallback``,
    ``empty``. The API path (`api` / `api_cached`) is authoritative
    when present. Frontend can show a "stale data" indicator when
    `stale_since` is set.
    """
    slug: str
    tracker_id: str = ""
    source: str = SOURCE_EMPTY
    submissions: List[Submission] = field(default_factory=list)
    fetched_at: str = ""
    stale_since: str = ""
    error_kind: str = ""

    # Derived rollups callers commonly need.
    @property
    def total_views(self) -> int:
        return sum(s.views for s in self.submissions)

    @property
    def total_likes(self) -> int:
        return sum(s.likes for s in self.submissions)

    @property
    def total_comments(self) -> int:
        return sum(s.comments for s in self.submissions)

    @property
    def total_shares(self) -> int:
        return sum(s.shares for s in self.submissions)

    @property
    def post_count(self) -> int:
        return len(self.submissions)


# ---------------------------------------------------------------------------
# Fallback: synthesize submissions from scraper data
# ---------------------------------------------------------------------------


def _submissions_from_matched_videos(matched_videos: List[Dict[str, Any]]) -> List[Submission]:
    """Map scraper-populated `matched_videos` rows to Submission shape.

    Dismissed rows are excluded — they're soft-deleted false positives
    that the API would have excluded anyway. Comments/shares/engagement
    aren't tracked by the scraper, so they degrade to zero. `posted_at`
    falls back to `upload_date` (the scraper's nearest equivalent).
    """
    out: List[Submission] = []
    for v in matched_videos or []:
        if v.get("dismissed_at"):
            continue
        out.append(
            Submission(
                video_url=str(v.get("url") or ""),
                creator_username=str(v.get("account") or "").lstrip("@"),
                views=int(v.get("views", 0) or 0),
                likes=int(v.get("likes", 0) or 0),
                comments=0,
                shares=0,
                engagement_rate=0.0,
                follower_count=0,
                posted_at=str(v.get("upload_date") or ""),
                raw=dict(v),
            )
        )
    return out


def _hydrate_field_gaps(
    api_submissions: List[Submission],
    matched_videos: List[Dict[str, Any]],
) -> List[Submission]:
    """Fill `follower_count` / `posted_at` from scraper data when the API
    returned zero / empty for them.

    The public Tides Tracker API doesn't include either field today.
    Rather than dropping them silently, we look up the matching scraper
    row by URL and reuse what we have. If no scraper match exists, the
    field stays at its default (0 / ""). The scraper data is older than
    the API but better than nothing; consumers should treat these two
    fields as best-effort.

    URL match is done after normalizing trailing slashes and ignoring
    query params — TikTok URLs frequently round-trip with different
    cruft.
    """
    if not api_submissions:
        return api_submissions

    by_norm_url: Dict[str, Dict[str, Any]] = {}
    for v in matched_videos or []:
        url = (v.get("url") or "").strip()
        if not url:
            continue
        by_norm_url[_normalize_url(url)] = v

    hydrated: List[Submission] = []
    for s in api_submissions:
        if s.follower_count and s.posted_at:
            hydrated.append(s)
            continue
        match = by_norm_url.get(_normalize_url(s.video_url))
        if not match:
            hydrated.append(s)
            continue
        # Build a new Submission rather than mutating — the original
        # may be sitting in the module-level cache, and we want the
        # cache to represent exactly what the API returned. The
        # follower_count gap stays at the default 0 until the public
        # API surfaces it (RTA-43 follow-up).
        new_posted = s.posted_at or str(match.get("upload_date") or "")
        hydrated.append(_dc_replace(s, posted_at=new_posted))
    return hydrated


def _normalize_url(url: str) -> str:
    """Crude URL normalizer for cross-source matching.

    Strips query string, trailing slash, lowercases host. Good enough
    for matching the same TikTok post across the API + scraper without
    pulling in a dependency.
    """
    u = (url or "").strip().lower()
    if not u:
        return u
    if "?" in u:
        u = u.split("?", 1)[0]
    return u.rstrip("/")


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------


def _scrape_log_stale_since(slug: str) -> str:
    """Return the last scrape's `last_scrape` ISO string, or empty."""
    try:
        log = _db.get_scrape_log(slug)
    except Exception:
        return ""
    if not log:
        return ""
    ts = log.get("last_scrape")
    if not ts:
        return ""
    return str(ts)


def get_campaign_stats(
    slug: str,
    *,
    matched_videos: Optional[List[Dict[str, Any]]] = None,
    tracker_id: Optional[str] = None,
    start_date: str = "",
    force_refresh: bool = False,
    allow_live_fetch: bool = True,
) -> CampaignStatsResult:
    """Resolve performance stats for one campaign.

    Args:
        slug: campaign slug.
        matched_videos: optional pre-loaded scraper rows for fallback +
            field-gap hydration. Pass when the caller already has them
            in hand (e.g. campaign_detail, list-endpoint bulk path) to
            avoid a redundant DB query.
        tracker_id: optional pre-resolved tracker UUID. Pass empty string
            to declare "no tracker, go straight to fallback" (saves a DB
            lookup in the list-endpoint bulk path). When None, the
            function resolves the tracker itself (legacy single-call
            behaviour).
        start_date: campaign's ``start_date`` ("YYYY-MM-DD"). Used by the
            scraper-fallback path to drop pre-start matched videos (CAMP-
            55 / CAMP-42 follow-up). Empty disables the filter — the
            API path is already round-scoped via its tracker, so this
            only matters when ``tracker_id`` is empty or the API call
            fails. Fail-open on missing/unparseable dates per
            ``video_posted_before_start``.
        force_refresh: bypass the cache and re-fetch from the API.

    Never raises. Always returns a populated result — `source` tells
    the caller what they're looking at.
    """
    s = (slug or "").strip()
    if not s:
        return CampaignStatsResult(slug=s, source=SOURCE_EMPTY)

    # Resolve linked tracker. No tracker = scraper-only campaign.
    if tracker_id is None:
        tracker_id = ""
        try:
            tracker_id = _db.get_tracker_id_for_campaign(s)
        except Exception:
            logger.exception("campaign_stats: failed to resolve tracker_id for %s", s)
            tracker_id = ""

    if not tracker_id:
        return _fallback(
            s, matched_videos, tracker_id="", error_kind="no_tracker",
            start_date=start_date,
        )

    ttl = _cache_ttl_seconds()
    cached = None if force_refresh else _cache_get(tracker_id)

    if cached and _is_fresh(cached, ttl):
        return _result_from_api(
            slug=s,
            tracker_id=tracker_id,
            submissions=cached.submissions,
            api_fetched_at=cached.api_fetched_at,
            matched_videos=matched_videos,
            source=SOURCE_API,
        )

    # The list endpoint has a fixed latency budget. When its bulk pre-warm
    # did not fetch this tracker, return cached/scraper data rather than
    # turning the request into an unbounded series of upstream calls.
    if not allow_live_fetch:
        if cached is not None:
            return _result_from_api(
                slug=s,
                tracker_id=tracker_id,
                submissions=cached.submissions,
                api_fetched_at=cached.api_fetched_at,
                matched_videos=matched_videos,
                source=SOURCE_API_CACHED,
                stale_since=cached.fetched_at.isoformat(),
                error_kind="refresh_deferred",
            )
        return _fallback(
            s, matched_videos, tracker_id=tracker_id,
            error_kind="refresh_deferred", start_date=start_date,
        )

    # Cache miss or expired — go live.
    fetch = fetch_campaign_submissions(tracker_id)
    if fetch.ok:
        entry = _CacheEntry(
            submissions=fetch.submissions,
            fetched_at=datetime.now(timezone.utc),
            api_fetched_at=fetch.fetched_at,
        )
        _cache_set(tracker_id, entry)
        return _result_from_api(
            slug=s,
            tracker_id=tracker_id,
            submissions=fetch.submissions,
            api_fetched_at=fetch.fetched_at,
            matched_videos=matched_videos,
            source=SOURCE_API,
        )

    # API failed. Serve last-known cache if we have one.
    if cached is not None:
        logger.warning(
            "campaign_stats: serving stale cache for tracker %s (slug=%s): %s",
            tracker_id, s, fetch.error_kind,
        )
        return _result_from_api(
            slug=s,
            tracker_id=tracker_id,
            submissions=cached.submissions,
            api_fetched_at=cached.api_fetched_at,
            matched_videos=matched_videos,
            source=SOURCE_API_CACHED,
            stale_since=cached.fetched_at.isoformat(),
            error_kind=fetch.error_kind,
        )

    # No cache, no API. Last resort: scraper data.
    return _fallback(
        s, matched_videos, tracker_id=tracker_id, error_kind=fetch.error_kind,
        start_date=start_date,
    )


def _result_from_api(
    *,
    slug: str,
    tracker_id: str,
    submissions: List[Submission],
    api_fetched_at: str,
    matched_videos: Optional[List[Dict[str, Any]]],
    source: str,
    stale_since: str = "",
    error_kind: str = "",
) -> CampaignStatsResult:
    if matched_videos is None:
        try:
            matched_videos = _db.get_matched_videos(slug)
        except Exception:
            matched_videos = []
    hydrated = _hydrate_field_gaps(list(submissions), matched_videos or [])
    return CampaignStatsResult(
        slug=slug,
        tracker_id=tracker_id,
        source=source,
        submissions=hydrated,
        fetched_at=api_fetched_at,
        stale_since=stale_since,
        error_kind=error_kind,
    )


def _fallback(
    slug: str,
    matched_videos: Optional[List[Dict[str, Any]]],
    *,
    tracker_id: str,
    error_kind: str,
    start_date: str = "",
) -> CampaignStatsResult:
    if matched_videos is None:
        try:
            matched_videos = _db.get_matched_videos(slug)
        except Exception:
            matched_videos = []
    # CAMP-55: scope scraper rows to this campaign's date window before
    # synthesising submissions. Mirrors the CAMP-42 display-layer filter
    # on the scrape-tasks queue + campaign detail; without it a round-2
    # campaign that's still on the fallback path (no tracker, or API
    # erroring with no cache) would inflate stats with round-1 posts.
    # Fail-open on missing/unparseable post dates per
    # ``video_posted_before_start``.
    in_window = [
        v for v in (matched_videos or [])
        if not video_posted_before_start(v, start_date)
    ]
    subs = _submissions_from_matched_videos(in_window)
    return CampaignStatsResult(
        slug=slug,
        tracker_id=tracker_id,
        source=SOURCE_SCRAPER_FALLBACK if subs else SOURCE_EMPTY,
        submissions=subs,
        stale_since=_scrape_log_stale_since(slug) if subs else "",
        error_kind=error_kind,
    )


def overlay_video_stats(
    matched_videos: List[Dict[str, Any]],
    submissions: List[Submission],
) -> List[Dict[str, Any]]:
    """Overlay API stats onto scraper-populated matched_videos rows.

    Mutates a copy of each input row in place — view/like counts get
    rewritten from the matching API submission, plus
    `comments`/`shares`/`engagement_rate` are *added* to rows where the
    URL matches. Row identity (`id`, `dismissed_at`, `song`, `artist`,
    `music_id`, etc.) is preserved so the frontend's existing renderers
    keep working.

    Rows with no matching API submission stay untouched — that means a
    creator's video that the scraper found but Tides Tracker hasn't
    pulled stats for yet still shows the scraper's last-known numbers.
    Acceptable for now; RTA-44 will remove the scraper's stat
    responsibility entirely.
    """
    if not matched_videos:
        return []
    by_url: Dict[str, Submission] = {
        _normalize_url(s.video_url): s for s in submissions if s.video_url
    }
    out: List[Dict[str, Any]] = []
    for v in matched_videos:
        row = dict(v)
        s = by_url.get(_normalize_url(row.get("url", "")))
        if s is not None:
            row["views"] = s.views
            row["likes"] = s.likes
            row["comments"] = s.comments
            row["shares"] = s.shares
            row["engagement_rate"] = s.engagement_rate
        else:
            # Make these keys always present so frontend doesn't need to
            # branch on undefined.
            row.setdefault("comments", 0)
            row.setdefault("shares", 0)
            row.setdefault("engagement_rate", 0.0)
        out.append(row)
    return out


def get_campaign_stats_bulk(
    slugs: List[str],
    *,
    matched_videos_by_slug: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    start_date_by_slug: Optional[Dict[str, str]] = None,
    tracker_id_by_slug: Optional[Dict[str, str]] = None,
    frozen_slugs: Optional[set] = None,
) -> Dict[str, CampaignStatsResult]:
    """Resolve stats for many campaigns in one call.

    Pre-warms the in-process tides-tracker cache for every tracker
    that's currently cold/stale, in parallel, BEFORE calling
    ``get_campaign_stats`` per slug. Each per-slug call then hits a
    fresh cache and returns immediately.

    Why the pre-warm: ``/api/campaigns`` calls this for ~25 active
    campaigns. Without parallelism, a cold cache (any time after a
    Railway deploy resets the in-process dict) means 25 sequential
    ~50ms HTTP calls = 1.2s on the user's first page load. Pre-warming
    in parallel collapses that to one round-trip (~150ms).

    Pass ``start_date_by_slug`` so each campaign's fallback path scopes
    its matched videos to the right date window (CAMP-55). Slugs absent
    from the map fall through with no date filter (fail-open).

    Pass ``tracker_id_by_slug`` when the caller already resolved
    slug->tracker_id in bulk (campaigns list endpoint does) to avoid
    re-querying per-slug. Falls back to per-slug resolution when not
    provided.

    Pass ``frozen_slugs`` (completed campaigns) to exclude their
    trackers from the cold-fetch batch. Completed campaigns' numbers
    don't move, but the ``tides_tracker_pull`` cron only warms ACTIVE
    campaigns' trackers — so a finished campaign's cache entry is
    stale forever, and without this exclusion every ``?include_finished``
    page load burned the whole 10-tracker cold batch (at timeout=5s,
    ~6.5s wall) re-fetching stats that cannot change, crowding out the
    active trackers the batch exists for. Frozen slugs still get served
    below — from the durable L2 cache (stale is fine: the campaign is
    done) or the scraper fallback. A tracker shared with a non-frozen
    slug still gets fetched.
    """
    out: Dict[str, CampaignStatsResult] = {}
    mv = matched_videos_by_slug or {}
    sd = start_date_by_slug or {}
    tracker_map = tracker_id_by_slug
    if tracker_map is None:
        tracker_map = {}
        for s in slugs:
            try:
                tracker_map[s] = _db.get_tracker_id_for_campaign(s) or ""
            except Exception:
                tracker_map[s] = ""

    # Sort distinct non-fresh trackers into two buckets. Frozen slugs
    # never nominate their tracker — but iterate non-frozen slugs only
    # (rather than filtering trackers), so a tracker shared by an active
    # and a finished campaign is still refreshed for the active one.
    #
    #   stale (cache entry exists, just old)  -> serve the stale entry NOW,
    #       refresh in a background thread with the full 15s timeout
    #       (stale-while-revalidate). This is the common case and it must
    #       never block: one tracker whose upstream exceeded the old 5s
    #       inline budget used to hold EVERY page load at ~5-7s, because a
    #       timed-out fetch writes no cache and next request retried it.
    #   missing (no cache anywhere)           -> block briefly (5s cap) so
    #       brand-new trackers show data on first load. Rare: only ever a
    #       just-linked tracker, and only until its first successful fetch
    #       lands in the durable L2.
    #
    # Both buckets respect the attempt cooldown so a dead/slow upstream is
    # probed at most once per _REFRESH_COOLDOWN_SECONDS per worker, not on
    # every request.
    frozen = frozen_slugs or set()
    ttl = _cache_ttl_seconds()
    stale_ids: List[str] = []
    missing_ids: List[str] = []
    seen: set = set()
    for s in slugs:
        if s in frozen:
            continue
        tid = tracker_map.get(s, "")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        cached = _cache_get(tid)
        if cached and _is_fresh(cached, ttl):
            continue
        if _in_cooldown(tid):
            continue
        (stale_ids if cached is not None else missing_ids).append(tid)

    if stale_ids:
        stale_ids = stale_ids[:10]
        for tid in stale_ids:
            _mark_attempt(tid)
        _spawn_background_refresh(stale_ids)

    # One bounded batch keeps a slow Tracker upstream from occupying every
    # sync Gunicorn worker. Later requests fill the remaining cold entries.
    if missing_ids:
        missing_ids = missing_ids[:10]
        for tid in missing_ids:
            _mark_attempt(tid)
        _refresh_trackers_sync(missing_ids, timeout=5)

    # Per-slug pass — now hitting a warm cache for every tracker we
    # successfully pre-warmed.
    for s in slugs:
        out[s] = get_campaign_stats(
            s,
            matched_videos=mv.get(s),
            tracker_id=tracker_map.get(s, ""),
            start_date=sd.get(s, ""),
            allow_live_fetch=False,
        )
    return out
