"""Notion -> Postgres full sync + membership resolver (RTA-8, RTA-9).

Two-stage pipeline that keeps Hub's `internal_creator_group_members` table
in sync with what Notion's "🌌 Master Pages" database says.

Stage 1 — `sync_master_pages` (RTA-8):
    Pulls every row from Notion and mirrors it into `notion_master_pages`.
    Records one `notion_sync_log` row per run with counts + per-row errors.

Stage 2 — `resolve_memberships` (RTA-9; cluster model per CAMP cluster work):
    Reads `notion_master_pages` and reconciles the
    `internal_creator_group_members` table against it. Each Notion row
    resolves to at most one CLUSTER group (from `notion_subgroup`, i.e. the
    Notion `Group` field), slugified via the canonical `slugify()` helper.
    Missing cluster groups are auto-created. Memberships the mirror no
    longer attests get removed. Label (`notion_group`) and booker (`poster`)
    are NOT read — label is page metadata, booker is not a grouping concept.

    CRITICAL CONSTRAINT: the cleanup pass only touches `kind='cluster'`
    groups. `kind='custom'` (e.g. `general`) and any legacy
    `label`/`booked_by` groups left over from the old model are never
    touched — they're either human-maintained or pending one-time deletion.

Key design choices (apply to both stages):
- Reuses the property extractor helpers from `campaign_manager.services.notion`
  rather than introducing a new SDK dependency.
- Idempotent: a second run with no Notion changes is a no-op.
- Diff key for stage 1 is `notion_page_id` (UUID). Notion-only -> INSERT,
  both with newer `last_edited_time` -> UPDATE, mirror-only -> DELETE.
- Password field is intentionally NOT mirrored (security).
- Transactional: each stage's mutations land in one session. The
  sync_log row is written in a separate, always-committed session so the
  audit trail survives even when the main transaction rolls back.

RTA-10 (cron) chains these two stages every 15 minutes.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

import requests

from campaign_manager import db as _db
from campaign_manager.models import (
    InternalCreatorGroup,
    InternalCreatorGroupMember,
    NotionMasterPage,
    NotionSyncLog,
)
from campaign_manager.services.notion import (
    NOTION_API_BASE,
    NOTION_VERSION,
    _get_api_key,
    _get_date,
    _get_email,
    _get_rich_text,
    _get_select,
    _get_title,
    _get_url,
)
from campaign_manager.utils.helpers import slugify

logger = logging.getLogger(__name__)

# The master attribution database lives at this fixed Notion ID. Override
# via env var only if pointing at a staging/copy database.
MASTER_PAGES_DATABASE_ID = os.environ.get(
    "NOTION_MASTER_PAGES_DATABASE_ID",
    "3271465b-b829-805d-b21e-d6656edcfada",
)

# Notion paginates database query results. 100 is the API max page size.
_PAGE_SIZE = 100
_HTTP_TIMEOUT = 30

# CAMP-94 delete-floor: refuse a sync that would delete more than this fraction
# of the existing mirror in one pass (only when there are at least
# _DELETE_FLOOR_MIN_ROWS rows, so small/empty mirrors aren't blocked). A normal
# sync deletes 0-few rows; a mass delete signals a truncated/anomalous fetch.
_MAX_DELETE_FRACTION = 0.5
_DELETE_FLOOR_MIN_ROWS = 10


@dataclass
class SyncResult:
    pages_fetched: int = 0
    pages_added: int = 0
    pages_updated: int = 0
    pages_deleted: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    sync_log_id: int = 0


# ---------------------------------------------------------------------------
# Notion property extractors not present in services.notion
# ---------------------------------------------------------------------------

def _get_checkbox(prop: Dict) -> bool:
    """Extract value from a Notion checkbox property."""
    return bool(prop.get("checkbox", False))


def _parse_date_to_pydate(s: str):
    """Parse a YYYY-MM-DD or full ISO date string to a `date`. Returns None on failure."""
    if not s:
        return None
    try:
        # Notion 'date' start can be either 'YYYY-MM-DD' or full ISO datetime.
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _parse_iso_datetime(s: Optional[str]) -> Optional[datetime]:
    """Parse Notion's `last_edited_time` ISO-8601 string into an aware datetime."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _normalize_to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Return an aware UTC datetime regardless of input naive/aware-ness.

    Needed because the timestamp on a freshly mapped row is aware (from
    Notion), but a row read back from the DB may be naive on SQLite (which
    drops tzinfo). Comparing the two directly raises TypeError; this
    helper centralizes the normalization.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Notion fetch
# ---------------------------------------------------------------------------

def _headers() -> Dict[str, str]:
    """Local copy so we don't depend on the existing services.notion._headers
    (which is module-private). Same shape, same auth pattern."""
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _fetch_all_pages(database_id: str) -> List[Dict[str, Any]]:
    """Query every page in the master database, following pagination cursors."""
    url = f"{NOTION_API_BASE}/databases/{database_id}/query"
    pages: List[Dict[str, Any]] = []
    cursor: Optional[str] = None

    while True:
        payload: Dict[str, Any] = {"page_size": _PAGE_SIZE}
        if cursor:
            payload["start_cursor"] = cursor

        resp = requests.post(url, headers=_headers(), json=payload, timeout=_HTTP_TIMEOUT)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Notion API returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        body = resp.json()
        pages.extend(body.get("results", []) or [])

        if not body.get("has_more"):
            break
        cursor = body.get("next_cursor")
        if not cursor:
            # CAMP-94: has_more=True but no cursor is a TRUNCATED fetch, not a
            # clean end. Returning the partial list silently would make the
            # caller treat every un-fetched page as a DELETE (mass wipe of the
            # mirror + group memberships). Fail loudly so the sync aborts
            # instead of deleting.
            raise RuntimeError(
                "Notion pagination truncated: has_more=true but next_cursor is empty "
                "— aborting to avoid a partial fetch driving mass deletes."
            )

    return pages


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

def _map_page_to_row(page: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Convert one Notion page dict into a row-shaped dict, or an error dict.

    Returns ``(row, None)`` on success, ``(None, error)`` on a per-row failure
    (e.g. missing Account Username). The sync continues past per-row errors.
    """
    page_id_raw = page.get("id") or ""
    props = page.get("properties") or {}

    try:
        page_uuid = UUID(page_id_raw)
    except (TypeError, ValueError):
        return None, {
            "row_id": page_id_raw,
            "error_kind": "invalid_page_id",
            "detail": "Notion page id was missing or not a UUID",
        }

    account_username = _get_title(props.get("Account Username", {})).strip()
    if not account_username:
        return None, {
            "row_id": str(page_uuid),
            "error_kind": "missing_account_username",
            "detail": "Account Username title was empty",
        }

    row: Dict[str, Any] = {
        "notion_page_id": page_uuid,
        "account_username": account_username,
        "notion_group": _get_select(props.get("Group", {})) or None,
        # Trailing space is intentional — Notion has two distinct properties
        # called "Group" (group) and "Group " (subgroup). Confirmed in spec.
        "notion_subgroup": _get_select(props.get("Group ", {})) or None,
        "poster": _get_rich_text(props.get("Poster", {})) or None,
        "account_type": _get_select(props.get("Account Type", {})) or None,
        "page_type": _get_select(props.get("Page Type", {})) or None,
        "content_engine": _get_select(props.get("ContentEngine", {})) or None,
        "pipeline": _get_select(props.get("Pipeline", {})) or None,
        "status": _get_select(props.get("Status", {})) or None,
        "page_url": _get_url(props.get("Page URL", {})) or None,
        "email": _get_email(props.get("email", {})) or None,
        "notes": _get_rich_text(props.get("NOTES", {})) or None,
        "go_live_date": _parse_date_to_pydate(_get_date(props.get("Go-Live Date", {}))),
        "is_complete": _get_checkbox(props.get("Complete", {})),
        "notion_last_edited_at": _parse_iso_datetime(page.get("last_edited_time")),
    }
    return row, None


# ---------------------------------------------------------------------------
# Diff + persist
# ---------------------------------------------------------------------------

def _row_differs(existing_row: "NotionMasterPage", row: Dict[str, Any]) -> bool:
    """True when any mapped field in ``row`` differs from the mirror row.

    Content comparison, NOT timestamp comparison. Notion does not bump a
    page's ``last_edited_time`` for every change that alters property
    values — renaming a select option rewrites the value on every page
    using it with no timestamp change. A pure timestamp diff therefore
    froze stale values in the mirror forever (seen live 2026-06-09:
    backroaddriver's cluster said 'Warner Test UGC' while Notion said
    'Gannon Fremin', both stamped 2026-05-15T19:47Z).
    """
    for field_name, new_value in row.items():
        if field_name == "notion_page_id":
            continue
        old_value = getattr(existing_row, field_name)
        if field_name == "notion_last_edited_at":
            old_value = _normalize_to_utc(old_value)
            new_value = _normalize_to_utc(new_value)
        if old_value != new_value:
            return True
    return False


def _apply_diff(
    session,
    incoming_rows: List[Dict[str, Any]],
) -> Tuple[int, int, int]:
    """Reconcile the `notion_master_pages` table with the incoming rows.

    Returns ``(added, updated, deleted)``. Mutations happen on the session
    but are NOT committed here — caller controls the transaction.
    """
    incoming_by_id: Dict[UUID, Dict[str, Any]] = {r["notion_page_id"]: r for r in incoming_rows}
    incoming_ids = set(incoming_by_id.keys())

    existing = session.query(NotionMasterPage).all()
    existing_by_id: Dict[UUID, NotionMasterPage] = {e.notion_page_id: e for e in existing}
    existing_ids = set(existing_by_id.keys())

    added = updated = deleted = 0

    # INSERT (Notion-only)
    for new_id in incoming_ids - existing_ids:
        row = incoming_by_id[new_id]
        session.add(NotionMasterPage(**row))
        added += 1

    # UPDATE (both sides, any mapped field differs). Content diff, not
    # timestamp diff — see _row_differs for why timestamps can't be trusted.
    for shared_id in incoming_ids & existing_ids:
        row = incoming_by_id[shared_id]
        existing_row = existing_by_id[shared_id]
        if _row_differs(existing_row, row):
            for field_name, value in row.items():
                setattr(existing_row, field_name, value)
            existing_row.synced_at = datetime.now(timezone.utc)
            updated += 1

    # DELETE (mirror-only) — with a CAMP-94 safety floor.
    stale_ids = existing_ids - incoming_ids
    # Guardrail: if a single sync would delete more than _MAX_DELETE_FRACTION of
    # the existing mirror (and there's a meaningful number of rows), that's
    # almost certainly a truncated/anomalous fetch, not a real bulk-unassign.
    # Skip the delete pass and log it loudly rather than wipe attribution data;
    # the INSERT/UPDATE work above still applies. (The _fetch_all_pages
    # truncation guard above catches the cursor case; this catches any OTHER
    # path that returns an anomalously small set without raising.)
    if (
        len(existing_ids) >= _DELETE_FLOOR_MIN_ROWS
        and len(stale_ids) > _MAX_DELETE_FRACTION * len(existing_ids)
    ):
        logger.error(
            "notion_sync: REFUSING to delete %d/%d mirror rows in one sync "
            "(> %.0f%% — likely a partial/anomalous fetch). Skipping delete pass; "
            "added=%d updated=%d. Investigate the Notion fetch.",
            len(stale_ids), len(existing_ids), _MAX_DELETE_FRACTION * 100,
            added, updated,
        )
    else:
        for stale_id in stale_ids:
            session.delete(existing_by_id[stale_id])
            deleted += 1

    return added, updated, deleted


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_master_pages(triggered_by: str = "cron") -> SyncResult:
    """Pull every row from Notion's Master Pages database and upsert into
    ``notion_master_pages``. Idempotent on rerun.

    A ``notion_sync_log`` row is ALWAYS written, even when the run fails.
    The main upsert/delete batch runs in a single transaction; if it
    raises, the transaction rolls back and the log row records the
    failure with an error entry.

    Args:
        triggered_by: free-form provenance string. Examples:
            ``"cron"``, ``"manual:smoke"``, ``"webhook"``, ``"manual:<username>"``.

    Returns:
        SyncResult with counts, errors, and the sync_log row id.
    """
    result = SyncResult()
    started_at = datetime.now(timezone.utc)
    fetch_error: Optional[Dict[str, Any]] = None
    pages: List[Dict[str, Any]] = []

    # --- Fetch ----------------------------------------------------------
    try:
        pages = _fetch_all_pages(MASTER_PAGES_DATABASE_ID)
        result.pages_fetched = len(pages)
    except Exception as exc:
        fetch_error = {
            "row_id": "",
            "error_kind": "fetch_failed",
            "detail": str(exc)[:500],
        }
        result.errors.append(fetch_error)
        logger.exception("Notion fetch failed during sync_master_pages")

    # --- Map ------------------------------------------------------------
    rows: List[Dict[str, Any]] = []
    if fetch_error is None:
        for page in pages:
            row, err = _map_page_to_row(page)
            if err is not None:
                result.errors.append(err)
            elif row is not None:
                rows.append(row)

    # --- Persist mirror -------------------------------------------------
    if fetch_error is None:
        try:
            with _db.get_session() as session:
                added, updated, deleted = _apply_diff(session, rows)
                session.commit()
                result.pages_added = added
                result.pages_updated = updated
                result.pages_deleted = deleted
        except Exception as exc:
            result.errors.append({
                "row_id": "",
                "error_kind": "persist_failed",
                "detail": str(exc)[:500],
            })
            logger.exception("Persist phase failed during sync_master_pages")

    # --- Always write sync_log -----------------------------------------
    sync_type = "full"
    log_id = 0
    try:
        with _db.get_session() as log_session:
            log_row = NotionSyncLog(
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                sync_type=sync_type,
                pages_fetched=result.pages_fetched,
                pages_added=result.pages_added,
                pages_updated=result.pages_updated,
                pages_deleted=result.pages_deleted,
                memberships_added=None,
                memberships_removed=None,
                errors=result.errors or [],
                triggered_by=triggered_by,
            )
            log_session.add(log_row)
            log_session.commit()
            log_id = int(log_row.id or 0)
    except Exception:
        logger.exception("Failed to write notion_sync_log row")

    result.sync_log_id = log_id
    return result


# ===========================================================================
# RTA-9: Membership resolver
# ===========================================================================


@dataclass
class ResolveResult:
    rows_processed: int = 0
    memberships_added: int = 0
    memberships_removed: int = 0
    groups_created: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    sync_log_id: int = 0


# Only memberships in this group kind are managed by the resolver. Anything
# else (notably `kind='custom'`, e.g. the `general` group, and any legacy
# `label`/`booked_by` groups pending cleanup) is human-maintained and survives
# the cleanup pass intact.
#
# A `cluster` is one bucket of pages — sourced 1:1 from Notion's `Group` field
# (mirrored as `notion_subgroup`) and mapped 1:1 to a Cobrand sheet /
# TidesTracker. This is the ONLY axis the resolver classifies by. Label is
# metadata the resolver never reads; booker is not a grouping concept at all.
_MANAGED_KINDS = ("cluster",)


def _title_from_notion_value(value: str, kind: str) -> str:
    """Produce a human-readable group title from a raw Notion value.

    For labels, Notion stores ALL-CAPS strings ('WARNER', 'ATLANTIC') —
    title-case is the right display form. For bookers, the input is
    already free-text human ('Jake Balik') — keep as-is, just stripped.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        return cleaned
    if kind == "label":
        return cleaned.title()
    return cleaned


def _ensure_group(
    session,
    *,
    slug: str,
    kind: str,
    title_source: str,
    cache: Dict[str, InternalCreatorGroup],
) -> Tuple[InternalCreatorGroup, bool]:
    """Return ``(group, was_created)`` for ``slug``. Creates with ``kind`` if missing.

    ``cache`` is a per-resolve dict that maps slug -> group, used to skip
    repeat queries within a single run. Mutated in place.
    """
    if slug in cache:
        return cache[slug], False

    existing = (
        session.query(InternalCreatorGroup)
        .filter(InternalCreatorGroup.slug == slug)
        .one_or_none()
    )
    if existing is not None:
        cache[slug] = existing
        return existing, False

    created = InternalCreatorGroup(
        slug=slug,
        title=_title_from_notion_value(title_source, kind) or slug,
        kind=kind,
        sort_order=999,
    )
    session.add(created)
    session.flush()  # populate .id so subsequent membership inserts can FK it
    cache[slug] = created
    return created, True


def _desired_memberships_from_mirror(
    session,
    errors: List[Dict[str, Any]],
    rows_processed: List[int],
    groups_created: List[int],
) -> Set[Tuple[int, str]]:
    """Walk `notion_master_pages` and return the set of (group_id, username)
    tuples that the Notion mirror currently attests.

    Classifies pages by ONE axis — the cluster (Notion `Group`, mirrored as
    `notion_subgroup`). Label and booker are deliberately ignored: label is
    metadata, booker isn't a grouping concept. Side effects: auto-creates
    missing cluster groups, appends informational "group_created" entries to
    ``errors``, and increments the mutable counters passed in by the caller.
    """
    cache: Dict[str, InternalCreatorGroup] = {}
    desired: Set[Tuple[int, str]] = set()

    for row in session.query(NotionMasterPage).all():
        rows_processed[0] += 1
        page_id = str(row.notion_page_id)
        username = (row.account_username or "").strip().lower()

        if not username:
            # The sync stage already guards against this, but defensive.
            errors.append({
                "row_id": page_id,
                "error_kind": "missing_account_username",
                "detail": "mirror row had empty account_username at resolve time",
            })
            continue

        cluster_raw = (row.notion_subgroup or "").strip()

        resolved_any = False

        if cluster_raw:
            cluster_slug = slugify(cluster_raw)
            if cluster_slug:
                group, created = _ensure_group(
                    session, slug=cluster_slug, kind="cluster",
                    title_source=cluster_raw, cache=cache,
                )
                if created:
                    groups_created[0] += 1
                    errors.append({
                        "row_id": page_id,
                        "error_kind": "group_created",
                        "detail": f"cluster group {cluster_slug!r} created",
                    })
                desired.add((int(group.id), username))
                resolved_any = True

        if not resolved_any:
            errors.append({
                "row_id": page_id,
                "error_kind": "no_attribution",
                "detail": "no cluster (Group) on this Notion page",
            })

    return desired


def _apply_membership_diff(
    session,
    desired: Set[Tuple[int, str]],
) -> Tuple[int, int]:
    """Apply the desired (group_id, username) set to
    `internal_creator_group_members`. Only mutates rows whose group's kind
    is in ``_MANAGED_KINDS``.

    Returns ``(added, removed)``.
    """
    # Pull existing memberships that belong to a managed-kind group. Anything
    # in a custom-kind group is invisible to this function — both for diffing
    # and for removal. That keeps `general` and friends safe.
    existing_rows = (
        session.query(
            InternalCreatorGroupMember.group_id,
            InternalCreatorGroupMember.username,
            InternalCreatorGroup.kind,
        )
        .join(
            InternalCreatorGroup,
            InternalCreatorGroup.id == InternalCreatorGroupMember.group_id,
        )
        .filter(InternalCreatorGroup.kind.in_(_MANAGED_KINDS))
        .all()
    )
    existing: Set[Tuple[int, str]] = {
        (int(gid), (uname or "").lower()) for gid, uname, _kind in existing_rows
    }

    to_add = desired - existing
    to_remove = existing - desired

    # ON CONFLICT DO NOTHING instead of blind session.add: the resolver
    # cron can race a manual add_group_members call in another gunicorn
    # worker for the same (group_id, username) pair, which used to abort
    # the whole resolve transaction with IntegrityError. RETURNING keeps
    # the added-count honest when the other writer wins.
    added_count = 0
    if to_add:
        member_t = InternalCreatorGroupMember.__table__
        stmt = _db.dialect_insert(member_t).values([
            {"group_id": group_id, "username": username}
            for group_id, username in sorted(to_add)
        ]).on_conflict_do_nothing(
            index_elements=["group_id", "username"],
        ).returning(member_t.c.username)
        added_count = len(session.execute(stmt).all())

    for group_id, username in to_remove:
        session.query(InternalCreatorGroupMember).filter(
            InternalCreatorGroupMember.group_id == group_id,
            InternalCreatorGroupMember.username == username,
        ).delete(synchronize_session=False)

    return added_count, len(to_remove)


def resolve_memberships(
    triggered_by: str = "cron",
    sync_log_id: Optional[int] = None,
) -> ResolveResult:
    """Reconcile `internal_creator_group_members` against `notion_master_pages`.

    For each mirrored Notion page:
      - Slugify ``notion_group`` -> resolve/create a ``kind='label'`` group.
      - Slugify ``poster`` -> resolve/create a ``kind='booked_by'`` group.
      - Ensure a membership row exists for each resolved group.

    After processing all rows, remove memberships in managed-kind groups
    that the mirror no longer attests. Custom-kind groups are never touched.

    If ``sync_log_id`` is provided, the membership counts are written back
    onto that existing row (typically the row produced by `sync_master_pages`
    earlier in the same cron cycle). Otherwise a fresh ``sync_type='resolve'``
    log row is written.
    """
    result = ResolveResult()
    started_at = datetime.now(timezone.utc)

    rows_processed = [0]
    groups_created = [0]

    try:
        with _db.get_session() as session:
            desired = _desired_memberships_from_mirror(
                session, result.errors, rows_processed, groups_created,
            )
            added, removed = _apply_membership_diff(session, desired)
            session.commit()
            result.memberships_added = added
            result.memberships_removed = removed
    except Exception as exc:
        result.errors.append({
            "row_id": "",
            "error_kind": "resolve_failed",
            "detail": str(exc)[:500],
        })
        logger.exception("resolve_memberships transaction failed")

    result.rows_processed = rows_processed[0]
    result.groups_created = groups_created[0]

    # ---- Audit log (always written) -----------------------------------
    finished_at = datetime.now(timezone.utc)
    log_id_written = 0
    try:
        with _db.get_session() as log_session:
            row: Optional[NotionSyncLog] = None
            if sync_log_id:
                row = (
                    log_session.query(NotionSyncLog)
                    .filter(NotionSyncLog.id == sync_log_id)
                    .one_or_none()
                )
            if row is not None:
                # Updating the existing sync_master_pages row in place — keep
                # the original started_at, refresh finished_at, layer on the
                # resolver counts, and merge the error arrays.
                row.finished_at = finished_at
                row.memberships_added = result.memberships_added
                row.memberships_removed = result.memberships_removed
                existing_errors = list(row.errors or [])
                if result.errors:
                    existing_errors.extend(result.errors)
                row.errors = existing_errors
                log_session.commit()
                log_id_written = int(row.id)
            else:
                fresh = NotionSyncLog(
                    started_at=started_at,
                    finished_at=finished_at,
                    sync_type="resolve",
                    pages_fetched=None,
                    pages_added=None,
                    pages_updated=None,
                    pages_deleted=None,
                    memberships_added=result.memberships_added,
                    memberships_removed=result.memberships_removed,
                    errors=result.errors or [],
                    triggered_by=triggered_by,
                )
                log_session.add(fresh)
                log_session.commit()
                log_id_written = int(fresh.id or 0)
    except Exception:
        logger.exception("Failed to write notion_sync_log row for resolve stage")

    result.sync_log_id = log_id_written
    return result


# ===========================================================================
# RTA-10: Cron tick (sync -> resolve, every N minutes)
# ===========================================================================


# Defaults + bounds for the scheduler interval. The job is fast (a few
# hundred ms on the current ~50-row mirror) so even 1 minute is safe; the
# 1440 ceiling is just a sanity guard so a typo can't disable the cron.
NOTION_SYNC_DEFAULT_INTERVAL_MINUTES = 15
NOTION_SYNC_MIN_INTERVAL_MINUTES = 1
NOTION_SYNC_MAX_INTERVAL_MINUTES = 1440


# In-flight guard. The scheduler is configured single-worker (file lock in
# `create_app`), but `coalesce=True + max_instances=1` plus this boolean
# belt-and-suspenders ensures a slow Notion API can never produce two
# concurrent runs that step on each other's diffs.
_notion_sync_in_progress = False
_notion_sync_lock = __import__("threading").Lock()


def get_notion_sync_interval_minutes() -> int:
    """Resolve the cron interval from the env var, clamped to defensive bounds.

    Bounds: ``NOTION_SYNC_MIN_INTERVAL_MINUTES`` <= n <= ``NOTION_SYNC_MAX_INTERVAL_MINUTES``.
    Falls back to the default on missing / unparseable / out-of-bounds values.
    """
    raw = os.environ.get("NOTION_SYNC_INTERVAL_MINUTES", "")
    if not raw:
        return NOTION_SYNC_DEFAULT_INTERVAL_MINUTES
    try:
        n = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "NOTION_SYNC_INTERVAL_MINUTES=%r is not an integer; using default %d",
            raw, NOTION_SYNC_DEFAULT_INTERVAL_MINUTES,
        )
        return NOTION_SYNC_DEFAULT_INTERVAL_MINUTES
    if n < NOTION_SYNC_MIN_INTERVAL_MINUTES or n > NOTION_SYNC_MAX_INTERVAL_MINUTES:
        logger.warning(
            "NOTION_SYNC_INTERVAL_MINUTES=%d out of bounds [%d, %d]; using default %d",
            n, NOTION_SYNC_MIN_INTERVAL_MINUTES, NOTION_SYNC_MAX_INTERVAL_MINUTES,
            NOTION_SYNC_DEFAULT_INTERVAL_MINUTES,
        )
        return NOTION_SYNC_DEFAULT_INTERVAL_MINUTES
    return n


def run_notion_sync() -> None:
    """One cron tick: sync_master_pages -> resolve_memberships.

    - Skipped (no-op) when a previous tick is still running.
    - Never raises. Any exception from either stage is caught and logged at
      ERROR so APScheduler's worker thread stays alive.
    - resolve_memberships is only invoked when the sync stage returns a
      non-zero log id AND fetched at least one page. A failed fetch leaves
      the mirror unchanged, so there's nothing new for the resolver to
      reconcile against.
    """
    global _notion_sync_in_progress

    with _notion_sync_lock:
        if _notion_sync_in_progress:
            logger.info("CRON: notion_sync skipped (previous tick still in flight)")
            return
        _notion_sync_in_progress = True

    sync_log_id: Optional[int] = None
    try:
        logger.info("CRON: starting notion_sync")
        try:
            sync_result = sync_master_pages(triggered_by="cron")
            sync_log_id = sync_result.sync_log_id or None
            logger.info(
                "CRON: notion_sync stage 1 (sync) done — fetched=%d added=%d updated=%d deleted=%d errors=%d log_id=%s",
                sync_result.pages_fetched,
                sync_result.pages_added,
                sync_result.pages_updated,
                sync_result.pages_deleted,
                len(sync_result.errors),
                sync_log_id,
            )
        except Exception:
            logger.exception("CRON: notion_sync stage 1 (sync) raised; skipping resolve")
            return

        if sync_result.pages_fetched == 0:
            # Either no Notion data or fetch_failed (sync_master_pages handles
            # both internally and never raises). Nothing for resolve to do.
            logger.info("CRON: notion_sync resolve skipped (sync fetched 0 pages)")
            return

        try:
            resolve_result = resolve_memberships(
                triggered_by="cron", sync_log_id=sync_log_id,
            )
            logger.info(
                "CRON: notion_sync stage 2 (resolve) done — rows=%d added=%d removed=%d groups_created=%d errors=%d log_id=%s",
                resolve_result.rows_processed,
                resolve_result.memberships_added,
                resolve_result.memberships_removed,
                resolve_result.groups_created,
                len(resolve_result.errors),
                resolve_result.sync_log_id,
            )
        except Exception:
            logger.exception("CRON: notion_sync stage 2 (resolve) raised")
    finally:
        with _notion_sync_lock:
            _notion_sync_in_progress = False
