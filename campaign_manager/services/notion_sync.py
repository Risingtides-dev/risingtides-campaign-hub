"""Notion -> Postgres full sync service (RTA-8).

Pulls every row from the Notion "🌌 Master Pages" database and mirrors it
into the `notion_master_pages` table. Records one `notion_sync_log` row
per run with counts + per-row errors.

Key design choices:
- Reuses the property extractor helpers from `campaign_manager.services.notion`
  rather than introducing a new SDK dependency.
- Idempotent: a second run with no Notion changes is a no-op.
- Diff key is `notion_page_id` (UUID). Notion-only -> INSERT, both with newer
  `last_edited_time` -> UPDATE, mirror-only -> DELETE, equal timestamps -> skip.
- Password field is intentionally NOT mirrored (security).
- Transactional: all upserts + deletes happen in one session. The sync_log
  row is written in a separate, always-committed session so the audit trail
  survives even when the main transaction rolls back on an unexpected error.

RTA-9 builds the membership resolver on top of this mirror.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import requests

from campaign_manager import db as _db
from campaign_manager.models import NotionMasterPage, NotionSyncLog
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

logger = logging.getLogger(__name__)

# The master attribution database lives at this fixed Notion ID. Override
# via env var only if pointing at a staging/copy database.
MASTER_PAGES_DATABASE_ID = os.environ.get(
    "NOTION_MASTER_PAGES_DATABASE_ID",
    "3271465b-b829-8037-97b8-000bc1612218",
)

# Notion paginates database query results. 100 is the API max page size.
_PAGE_SIZE = 100
_HTTP_TIMEOUT = 30


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
            break

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

    # UPDATE (both sides, Notion edit is newer or timestamps don't match)
    for shared_id in incoming_ids & existing_ids:
        row = incoming_by_id[shared_id]
        existing_row = existing_by_id[shared_id]
        new_ts = _normalize_to_utc(row.get("notion_last_edited_at"))
        old_ts = _normalize_to_utc(existing_row.notion_last_edited_at)
        # Update if Notion's edit timestamp is strictly newer, OR if either side
        # is missing a timestamp (defensive — old mirror rows may pre-date the
        # column). Equal timestamps are no-ops.
        if new_ts is None or old_ts is None or new_ts > old_ts:
            for field_name, value in row.items():
                setattr(existing_row, field_name, value)
            existing_row.synced_at = datetime.now(timezone.utc)
            updated += 1

    # DELETE (mirror-only)
    for stale_id in existing_ids - incoming_ids:
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
