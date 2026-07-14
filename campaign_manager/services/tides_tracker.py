"""Tides Tracker public-API stats client + cron (RTA-42).
See also: services/tidestracker.py — folder overlay + scrape-queue cross-check.

Pulls per-tracker submission stats from the Tides Tracker public
endpoint:

    GET https://risingtides-tracker.com/api/public/<tracker_id>

The endpoint is auth-free — the UUID is the access token. Each response
returns every Cobrand submission for that tracker with per-creator
stats (views, likes, comments, shares, engagement rate, post URLs,
follower counts). Used by RTA-43 / RTA-44 to drive campaign performance
views in Hub.

Two callables:

- `fetch_campaign_submissions(tracker_id)` — typed wrapper around one
  HTTP call. Fail-soft: never raises on 4xx/5xx/timeout/bad JSON.
  Returns a `TidesTrackerFetchResult` carrying either a list of typed
  `Submission` records or a structured error.

- `pull_all_trackers(triggered_by="cron")` — walks `tracker_names`,
  calls the typed fetcher for every known tracker, writes one
  `tides_tracker_sync_log` audit row with aggregate counts + per-tracker
  outcomes. Returns a `PullResult` so the cron tick + manual smoke
  script can log structured output.

Audit log mirrors RTA-7's `notion_sync_log` shape — per-tracker errors
land in the `errors` JSONB, including success markers, so a single log
row tells the whole story of a tick.

The cron tick lives in `run_tides_tracker_pull()` and is wired into
APScheduler from `services/scheduler.py` on a 30-minute default
interval, env-overridable via ``TIDES_TRACKER_PULL_INTERVAL_MINUTES``
(clamped 1..1440). An in-flight guard prevents overlap if the
public API stalls.

Key non-decisions:
- We do NOT persist the per-submission rows here. This service owns
  the fetch/cache/audit layer. RTA-43/44 will consume the typed
  records and decide where they land (campaign stats table, etc.).
- We do NOT mirror the existing `get_tracked_videos` cache in
  `services/tidestracker.py` — that one only extracts URLs for
  cross-checking the scrape queue, runs on demand, and lives next to
  the rest of the tracker overlay code. This new service is the
  stats pipeline.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

import requests

from campaign_manager import db as _db
from campaign_manager.models import TidesTrackerSyncLog

logger = logging.getLogger(__name__)

# TikTok URL pattern: /video/<19-ish-digit-id>. Used to dedupe Scrape Tasks
# queue rows against the URLs already submitted to a Tides Tracker /
# Cobrand campaign — same video_id means the same TikTok post regardless
# of host (vm.tiktok.com vs www.tiktok.com) or query-string noise.
_TIKTOK_VIDEO_ID_RE = re.compile(r"/video/(\d{6,25})")


def _extract_tiktok_video_id(url: str) -> str:
    if not url:
        return ""
    m = _TIKTOK_VIDEO_ID_RE.search(url)
    return m.group(1) if m else ""


# Pinned to the canonical Tides Tracker domain. The auth-free public
# endpoint lives at /api/public/<tracker_id>. Env override only for
# dev/staging.
TIDES_TRACKER_PUBLIC_BASE = os.environ.get(
    "TIDES_TRACKER_PUBLIC_BASE_URL",
    "https://risingtides-tracker.com",
).rstrip("/")

_HTTP_TIMEOUT_SECONDS = 15


# ---------------------------------------------------------------------------
# Typed records
# ---------------------------------------------------------------------------


@dataclass
class Submission:
    """One Cobrand submission as returned by the public stats endpoint.

    Field shapes are inferred from Eric's discovery + the existing
    URL-extracting client in `services/tidestracker.py`. The payload
    historically uses snake_case (`video_url`, `view_count`), so we
    accept either snake_case or camelCase aliases when parsing and
    normalize to snake_case here.

    `raw` keeps the original dict so RTA-43/44 can pull fields we
    haven't typed yet without a service change.
    """
    video_url: str = ""
    creator_username: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    engagement_rate: float = 0.0
    follower_count: int = 0
    posted_at: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "video_url": self.video_url,
            "creator_username": self.creator_username,
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "engagement_rate": self.engagement_rate,
            "follower_count": self.follower_count,
            "posted_at": self.posted_at,
        }


@dataclass
class TidesTrackerFetchResult:
    """Result of one ``fetch_campaign_submissions`` call.

    `ok=False` carries an `error_kind` so the cron audit log can
    bucket failures (timeout vs HTTP 4xx vs HTTP 5xx vs bad JSON vs
    missing tracker_id). Callers should not branch on the string
    `detail` — it's diagnostic, not contract.
    """
    ok: bool
    tracker_id: str
    submissions: List[Submission] = field(default_factory=list)
    fetched_at: str = ""
    error_kind: str = ""
    detail: str = ""
    status_code: int = 0

    @property
    def count(self) -> int:
        return len(self.submissions)


# ---------------------------------------------------------------------------
# Single-tracker fetch
# ---------------------------------------------------------------------------


def _coerce_int(v: Any) -> int:
    """Best-effort int coercion. Returns 0 on None / non-numeric input."""
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            # Some payloads return numeric strings like "1.2k" or floats.
            return int(float(v))
        except (TypeError, ValueError):
            return 0


def _coerce_float(v: Any) -> float:
    """Best-effort float coercion. Returns 0.0 on None / non-numeric input."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _coerce_str(v: Any) -> str:
    """None-safe string coercion. Returns '' for None, else str(v)."""
    if v is None:
        return ""
    return str(v)


def _pick(d: Dict[str, Any], *keys: str) -> Any:
    """Return the first non-None value from `d` for any of `keys`.

    Lets us accept both snake_case and camelCase variants without
    branching all over the parser.
    """
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _parse_submission(v: Dict[str, Any]) -> Submission:
    """Map one video dict from the public API to a typed `Submission`.

    Defensive: unknown shapes degrade to defaults rather than raising.
    The raw dict is preserved on the record so RTA-43/44 can dig into
    fields we haven't surfaced.
    """
    return Submission(
        video_url=_coerce_str(_pick(v, "video_url", "videoUrl", "url")),
        creator_username=_coerce_str(
            _pick(v, "creator_username", "creatorUsername", "username", "creator")
        ),
        views=_coerce_int(_pick(v, "views", "view_count", "viewCount")),
        likes=_coerce_int(_pick(v, "likes", "like_count", "likeCount")),
        comments=_coerce_int(_pick(v, "comments", "comment_count", "commentCount")),
        shares=_coerce_int(_pick(v, "shares", "share_count", "shareCount")),
        engagement_rate=_coerce_float(
            _pick(v, "engagement_rate", "engagementRate")
        ),
        follower_count=_coerce_int(
            _pick(v, "follower_count", "followerCount", "followers")
        ),
        posted_at=_coerce_str(
            _pick(v, "posted_at", "postedAt", "created_at", "createdAt")
        ),
        raw=dict(v),
    )


def fetch_campaign_submissions(
    tracker_id: str, *, timeout: float = _HTTP_TIMEOUT_SECONDS,
) -> TidesTrackerFetchResult:
    """Fetch every submission for one tracker from the public API.

    Never raises. Always returns a result — `ok=False` paths populate
    `error_kind` from this closed set:

        - ``missing_tracker_id`` — empty/None input
        - ``invalid_tracker_id`` — non-UUID input
        - ``timeout``            — `requests.Timeout`
        - ``connection``         — `requests.ConnectionError`
        - ``request_error``      — any other `requests.RequestException`
        - ``http_4xx`` / ``http_5xx`` — non-200 response
        - ``bad_json``           — 200 but body wasn't JSON
        - ``bad_payload``        — JSON returned but no `videos` array

    The cron caller (`pull_all_trackers`) buckets these in the audit
    log; this lets us tell "tracker doesn't exist anymore (404)" from
    "Tides Tracker is down (5xx)" from "Railway can't reach it
    (connection)" at a glance.
    """
    tid = (tracker_id or "").strip()
    if not tid:
        return TidesTrackerFetchResult(
            ok=False,
            tracker_id="",
            error_kind="missing_tracker_id",
            detail="tracker_id was empty",
        )
    try:
        UUID(tid)
    except ValueError:
        return TidesTrackerFetchResult(
            ok=False,
            tracker_id=tid,
            error_kind="invalid_tracker_id",
            detail="tracker_id must be a UUID",
        )

    url = f"{TIDES_TRACKER_PUBLIC_BASE}/api/public/{tid}"

    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
    except requests.Timeout as exc:
        return TidesTrackerFetchResult(
            ok=False, tracker_id=tid,
            error_kind="timeout", detail=str(exc)[:300],
        )
    except requests.ConnectionError as exc:
        return TidesTrackerFetchResult(
            ok=False, tracker_id=tid,
            error_kind="connection", detail=str(exc)[:300],
        )
    except requests.RequestException as exc:
        return TidesTrackerFetchResult(
            ok=False, tracker_id=tid,
            error_kind="request_error", detail=str(exc)[:300],
        )

    if resp.status_code != 200:
        bucket = "http_4xx" if 400 <= resp.status_code < 500 else "http_5xx"
        return TidesTrackerFetchResult(
            ok=False, tracker_id=tid,
            error_kind=bucket,
            detail=(resp.text or "")[:300],
            status_code=resp.status_code,
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        return TidesTrackerFetchResult(
            ok=False, tracker_id=tid,
            error_kind="bad_json", detail=str(exc)[:300],
            status_code=resp.status_code,
        )

    if not isinstance(payload, dict) or "videos" not in payload:
        return TidesTrackerFetchResult(
            ok=False, tracker_id=tid,
            error_kind="bad_payload",
            detail="response missing `videos` array",
            status_code=resp.status_code,
        )

    videos = payload.get("videos") or []
    submissions = [_parse_submission(v) for v in videos if isinstance(v, dict)]

    return TidesTrackerFetchResult(
        ok=True,
        tracker_id=tid,
        submissions=submissions,
        fetched_at=_coerce_str(payload.get("fetched_at")) or datetime.now(timezone.utc).isoformat(),
        status_code=resp.status_code,
    )


# ---------------------------------------------------------------------------
# All-trackers pull + audit log
# ---------------------------------------------------------------------------


@dataclass
class PullResult:
    trackers_total: int = 0
    trackers_succeeded: int = 0
    trackers_failed: int = 0
    submissions_fetched: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    sync_log_id: int = 0
    results_by_tracker: Dict[str, TidesTrackerFetchResult] = field(default_factory=dict)


def _list_tracker_ids() -> List[str]:
    """Tracker UUIDs to pull, sourced from `tracker_names`, EXCLUDING any whose
    linked campaign is completed.

    RTA-41 made this table the single source of truth post-link creation
    (every link writes a name row atomically), so it naturally skips trackers
    not yet adopted by Campaign Hub.

    CAMP-1 (Gap 1): the pull cron used to fetch EVERY tracker every tick — and
    ~68% of prod trackers (71/104) link to a `completed` campaign whose numbers
    are final and won't change. Those were wasted Tides Tracker API calls each
    tick. We now exclude a tracker ONLY when its linked campaign is explicitly
    `completion_status = 'completed'`. Trackers that are unlinked, or linked to
    a 'booked'/'none' campaign, still pull (a tracker with no completion signal
    must NOT be silently dropped). A tracker linked to BOTH a completed and a
    live campaign still pulls (the live one wins via the NOT-completed match).
    """
    import sqlalchemy as sa
    with _db.get_session() as s:
        rows = s.execute(sa.text("""
            SELECT tn.tracker_id
            FROM tracker_names tn
            WHERE tn.tracker_id IS NOT NULL
              AND NOT EXISTS (
                    SELECT 1
                    FROM tracker_campaign_links tcl
                    JOIN campaigns c ON c.slug = tcl.campaign_slug
                    WHERE tcl.tracker_id = tn.tracker_id
                      AND c.completion_status = 'completed'
              )
              -- but DO keep a tracker that also links a non-completed campaign
              OR EXISTS (
                    SELECT 1
                    FROM tracker_campaign_links tcl2
                    JOIN campaigns c2 ON c2.slug = tcl2.campaign_slug
                    WHERE tcl2.tracker_id = tn.tracker_id
                      AND (c2.completion_status IS NULL
                           OR c2.completion_status <> 'completed')
              )
        """)).fetchall()
        return [r[0] for r in rows if r[0]]


def pull_all_trackers(triggered_by: str = "cron") -> PullResult:
    """Fetch submissions for every tracker in `tracker_names`.

    Each fetch result is recorded in the audit log's `errors` array
    (yes, including successes — the field is "outcomes" in spirit, the
    column name is a holdover from the Notion log shape we're
    mirroring). A successful fetch lands as

        {"tracker_id": "<uuid>", "error_kind": "ok",
         "detail": "<n> submissions"}

    so a single sync_log row tells the whole story of one tick. A
    failed fetch lands with the typed `error_kind` from
    `fetch_campaign_submissions`.

    The audit row is always written, even when an unexpected exception
    bubbles up from the loop — so an opaque crash still leaves a
    record. The function itself never raises.
    """
    result = PullResult()
    started_at = datetime.now(timezone.utc)

    try:
        tracker_ids = _list_tracker_ids()
    except Exception as exc:
        logger.exception("tides_tracker pull: failed to load tracker_names")
        result.errors.append({
            "tracker_id": "",
            "error_kind": "tracker_list_failed",
            "detail": str(exc)[:300],
        })
        tracker_ids = []

    result.trackers_total = len(tracker_ids)

    for tid in tracker_ids:
        try:
            fetch = fetch_campaign_submissions(tid)
        except Exception as exc:
            # Defensive: `fetch_campaign_submissions` is documented to
            # never raise, but if a future change regresses that we
            # want the loop to keep going.
            logger.exception("tides_tracker pull: unexpected raise for tracker %s", tid)
            result.trackers_failed += 1
            result.errors.append({
                "tracker_id": tid,
                "error_kind": "unexpected_exception",
                "detail": str(exc)[:300],
            })
            continue

        result.results_by_tracker[tid] = fetch

        if fetch.ok:
            result.trackers_succeeded += 1
            result.submissions_fetched += fetch.count
            result.errors.append({
                "tracker_id": tid,
                "error_kind": "ok",
                "detail": f"{fetch.count} submissions",
            })
            # CAMP-74: warm the REQUEST-PATH stats cache the cron used to skip.
            # Before this, the cron only fetched submissions for the audit log;
            # the in-process cache get_campaign_stats() reads stayed cold after
            # every redeploy, so the first user request paid a full round-trip.
            # Writing through here means the cron's 30-min tick keeps the read
            # cache warm. (Still per-worker — the durable cross-worker Postgres
            # cache is the larger follow-up half of CAMP-74.)
            try:
                from campaign_manager.services import campaign_stats as _cs
                _cs.warm_cache(tid, fetch.submissions, fetch.fetched_at)
            except Exception:
                logger.debug("tides_tracker pull: cache warm skipped for %s", tid, exc_info=True)
        else:
            result.trackers_failed += 1
            result.errors.append({
                "tracker_id": tid,
                "error_kind": fetch.error_kind or "unknown",
                "detail": fetch.detail or "",
            })

    # Always write the audit row.
    finished_at = datetime.now(timezone.utc)
    try:
        with _db.get_session() as log_session:
            row = TidesTrackerSyncLog(
                started_at=started_at,
                finished_at=finished_at,
                sync_type="pull",
                trackers_total=result.trackers_total,
                trackers_succeeded=result.trackers_succeeded,
                trackers_failed=result.trackers_failed,
                submissions_fetched=result.submissions_fetched,
                errors=result.errors or [],
                triggered_by=triggered_by,
            )
            log_session.add(row)
            log_session.commit()
            result.sync_log_id = int(row.id or 0)
    except Exception:
        logger.exception("Failed to write tides_tracker_sync_log row")

    return result


# ===========================================================================
# Cron tick (every N minutes)
# ===========================================================================


# Defaults + bounds for the scheduler interval. 30-minute default per
# the RTA-42 ticket; bounds match the Notion sync resolver (RTA-10) so
# operators have one mental model for cron knobs.
TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES = 30
TIDES_TRACKER_MIN_INTERVAL_MINUTES = 1
TIDES_TRACKER_MAX_INTERVAL_MINUTES = 1440


# In-flight guard. APScheduler is configured with `coalesce=True +
# max_instances=1` from `scheduler.py`, but this boolean is the
# belt-and-suspenders that lets a slow public-API run never overlap
# with a fresh tick.
_tides_tracker_pull_in_progress = False
_tides_tracker_pull_lock = threading.Lock()


def get_tides_tracker_interval_minutes() -> int:
    """Resolve the cron interval from `TIDES_TRACKER_PULL_INTERVAL_MINUTES`.

    Falls back to the default on missing / unparseable / out-of-bounds
    values. Bounds: ``TIDES_TRACKER_MIN_INTERVAL_MINUTES`` <= n <=
    ``TIDES_TRACKER_MAX_INTERVAL_MINUTES``.
    """
    raw = os.environ.get("TIDES_TRACKER_PULL_INTERVAL_MINUTES", "")
    if not raw:
        return TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES
    try:
        n = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "TIDES_TRACKER_PULL_INTERVAL_MINUTES=%r is not an integer; using default %d",
            raw, TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES,
        )
        return TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES
    if n < TIDES_TRACKER_MIN_INTERVAL_MINUTES or n > TIDES_TRACKER_MAX_INTERVAL_MINUTES:
        logger.warning(
            "TIDES_TRACKER_PULL_INTERVAL_MINUTES=%d out of bounds [%d, %d]; "
            "using default %d",
            n, TIDES_TRACKER_MIN_INTERVAL_MINUTES, TIDES_TRACKER_MAX_INTERVAL_MINUTES,
            TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES,
        )
        return TIDES_TRACKER_DEFAULT_INTERVAL_MINUTES
    return n


def run_tides_tracker_pull() -> None:
    """One cron tick: `pull_all_trackers(triggered_by="cron")`.

    - Skipped (no-op) when a previous tick is still in flight.
    - Never raises. Any unexpected exception is caught and logged at
      ERROR so APScheduler's worker thread stays alive.
    """
    global _tides_tracker_pull_in_progress

    with _tides_tracker_pull_lock:
        if _tides_tracker_pull_in_progress:
            logger.info("CRON: tides_tracker_pull skipped (previous tick still in flight)")
            return
        _tides_tracker_pull_in_progress = True

    try:
        logger.info("CRON: starting tides_tracker_pull")
        try:
            result = pull_all_trackers(triggered_by="cron")
            logger.info(
                "CRON: tides_tracker_pull done — trackers=%d ok=%d failed=%d "
                "submissions=%d log_id=%s",
                result.trackers_total,
                result.trackers_succeeded,
                result.trackers_failed,
                result.submissions_fetched,
                result.sync_log_id,
            )
        except Exception:
            logger.exception("CRON: tides_tracker_pull raised")
    finally:
        with _tides_tracker_pull_lock:
            _tides_tracker_pull_in_progress = False


# ---------------------------------------------------------------------------
# Scrape Tasks queue ↔ Tides Tracker dedupe
# ---------------------------------------------------------------------------


@dataclass
class AutoTrackResult:
    """Outcome of one ``auto_track_submitted_videos`` pass."""

    trackers_polled: int = 0
    trackers_failed: int = 0
    submission_ids_found: int = 0
    queue_rows_auto_tracked: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)


def auto_track_submitted_videos(triggered_by: str = "cron") -> AutoTrackResult:
    """Mark Scrape Tasks queue rows as tracked when the same TikTok video
    has already been submitted to a Cobrand tracker.

    Walks every tracker_id in ``tracker_names``, fetches its public-API
    submissions in parallel, builds a set of TikTok video IDs, then marks
    any matched_videos row (untracked + undismissed) whose URL parses to
    one of those video IDs as ``tracked_by='auto:tides_tracker'`` —
    distinguishable from a human tick in audits.

    Designed to be called at the tail of the ``campaign_refresh`` cron
    so the Scrape Tasks queue self-cleans on every run: human only has
    to handle the truly-new work.

    Fail-soft: per-tracker fetch errors are bucketed into ``errors`` but
    the function still applies dedupes for the trackers it did reach.
    Returns whatever it managed to do — never raises.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    result = AutoTrackResult()

    try:
        tracker_ids = _list_tracker_ids()
    except Exception as exc:
        logger.exception("auto_track_submitted_videos: list tracker ids failed")
        result.errors.append({"phase": "list_trackers", "detail": str(exc)[:300]})
        return result

    if not tracker_ids:
        return result

    submitted: set = set()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(fetch_campaign_submissions, tid): tid for tid in tracker_ids}
        for fut in as_completed(futures):
            tid = futures[fut]
            try:
                fres = fut.result()
            except Exception as exc:
                result.trackers_failed += 1
                result.errors.append({
                    "tracker_id": tid,
                    "error_kind": "unexpected",
                    "detail": str(exc)[:300],
                })
                continue
            result.trackers_polled += 1
            if not fres.ok:
                result.trackers_failed += 1
                result.errors.append({
                    "tracker_id": tid,
                    "error_kind": fres.error_kind,
                    "detail": fres.detail[:300] if fres.detail else "",
                })
                continue
            for sub in fres.submissions:
                vid = _extract_tiktok_video_id(sub.video_url)
                if vid:
                    submitted.add(vid)

    result.submission_ids_found = len(submitted)
    if not submitted:
        return result

    # Pull the current untracked queue and intersect in Python. Keeps the
    # SQL simple (no regex extraction in WHERE) and the queue sizes
    # involved (a few thousand rows max) make this cheap.
    try:
        import sqlalchemy as sa
        with _db.get_session() as s:
            rows = s.execute(sa.text(
                "SELECT id, url FROM matched_videos "
                "WHERE tracked_at IS NULL AND dismissed_at IS NULL"
            )).fetchall()
            matching_ids: List[int] = []
            for row_id, url in rows:
                vid = _extract_tiktok_video_id(url or "")
                if vid and vid in submitted:
                    matching_ids.append(int(row_id))

            if matching_ids:
                upd = s.execute(sa.text(
                    "UPDATE matched_videos "
                    "SET tracked_at = NOW(), tracked_by = :marker "
                    "WHERE id = ANY(:ids) "
                    "  AND tracked_at IS NULL"
                ), {"marker": "auto:tides_tracker", "ids": matching_ids})
                result.queue_rows_auto_tracked = upd.rowcount or 0
                s.commit()
    except Exception as exc:
        logger.exception("auto_track_submitted_videos: UPDATE phase failed")
        result.errors.append({"phase": "update", "detail": str(exc)[:300]})

    logger.info(
        "auto_track_submitted_videos (%s): trackers polled=%d failed=%d "
        "submitted_ids=%d queue_rows_auto_tracked=%d",
        triggered_by, result.trackers_polled, result.trackers_failed,
        result.submission_ids_found, result.queue_rows_auto_tracked,
    )
    return result
