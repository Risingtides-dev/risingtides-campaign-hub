"""Durable CRM edit scan and bounded exact-page reconciliation.

The scan cursor and page-ID backlog commit together. A worker claims due pages
under row locks and acknowledges only the revision it processed. Source errors
retain the page for bounded retry; the scheduler does not equate a failed read
with a deliberate empty CRM field.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from campaign_manager import db
from campaign_manager.models import Campaign, CrmPageQueue, CrmScanState
from campaign_manager.services import notion

logger = logging.getLogger(__name__)
MAX_SCAN_PAGES_PER_TICK = 12
DELTA_SCAN_PAGES_PER_TICK = 4
FULL_SCAN_PAGES_PER_TICK = 8
DELTA_STATE_ID = 2
MAX_WORK_PER_TICK = 100
MAX_REVISION_ATTEMPTS = 8
NEEDS_ACTION_REASONS = ("malformed_client_row", "slug_conflict")
TICK_SECONDS = 50
SCAN_BUDGET_SECONDS = 15
PROPERTY_BUDGET_SECONDS = 20
STALE_LEASE_SECONDS = 90
WARNING_LAG_SECONDS = 120
AUDIT_INTERVAL = timedelta(hours=6)
LOOKBACK = timedelta(minutes=2)
MIN_SOURCE_SPACING = timedelta(milliseconds=500)


def _utcnow():
    return datetime.now(timezone.utc)


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_edited(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as error:
        raise notion.CrmSourceUnavailable("invalid_edit_time") from error
    if parsed.tzinfo is None:
        raise notion.CrmSourceUnavailable("invalid_edit_time")
    return parsed


def _source_paused():
    with db._SessionLocal() as session:
        row = session.get(CrmScanState, 1)
        return bool(row and row.source_pause_until and
                    _aware(row.source_pause_until) > _utcnow())


def _rate_slot(*, deadline):
    # Reserve at most two source requests/sec across PostgreSQL workers.
    with db._SessionLocal.begin() as session:
        session.execute(db.dialect_insert(CrmScanState.__table__).values(id=1)
                        .on_conflict_do_nothing(index_elements=[CrmScanState.id]))
        row = session.execute(select(CrmScanState).where(CrmScanState.id == 1)
                              .with_for_update()).scalar_one()
        now = _utcnow()
        if row.source_pause_until and _aware(row.source_pause_until) > now:
            return False
        slot = max(now, _aware(row.next_request_at) or now)
        delay = max(0.0, (slot - now).total_seconds())
        if time.monotonic() + delay >= deadline:
            return False
        row.next_request_at = slot + MIN_SOURCE_SPACING
    if delay:
        time.sleep(delay)
    return not _source_paused()


def _state(*, state_id=1):
    with db._SessionLocal.begin() as session:
        # Separate durable cursors; both lanes share source pacing on row 1.
        if state_id != 1:
            session.execute(db.dialect_insert(CrmScanState.__table__).values(id=1)
                            .on_conflict_do_nothing(index_elements=[CrmScanState.id]))
        session.execute(db.dialect_insert(CrmScanState.__table__).values(id=state_id)
                        .on_conflict_do_nothing(index_elements=[CrmScanState.id]))
        row = session.execute(select(CrmScanState).where(CrmScanState.id == state_id)
                              .with_for_update()).scalar_one()
        source = session.get(CrmScanState, 1) if state_id != 1 else row
        if source and source.source_pause_until and _aware(source.source_pause_until) > _utcnow():
            return None
        if state_id == DELTA_STATE_ID and row.watermark is None:
            # Start near current time; the original full audit remains responsible
            # for historical discovery, including edits before this lane exists.
            row.watermark = _utcnow() - LOOKBACK
        if row.window_end is None:
            row.window_end = _utcnow()
            row.cursor = None
            row.cursor_reset_count = 0
            row.full_audit_active = (state_id == 1 and
                                     (row.watermark is None or row.last_full_audit_at is None or
                                      _utcnow() - _aware(row.last_full_audit_at) >= AUDIT_INTERVAL))
        return (_aware(row.watermark), _aware(row.window_end), row.cursor,
                bool(row.full_audit_active))


def _pause_source(seconds):
    until = _utcnow() + timedelta(seconds=max(1, seconds))
    with db._SessionLocal.begin() as session:
        session.execute(db.dialect_insert(CrmScanState.__table__).values(id=1)
                        .on_conflict_do_nothing(index_elements=[CrmScanState.id]))
        row = session.execute(select(CrmScanState).where(CrmScanState.id == 1)
                              .with_for_update()).scalar_one()
        if row.source_pause_until is None or _aware(row.source_pause_until) < until:
            row.source_pause_until = until


def _save_scan_page(expected, candidates, next_cursor, *, state_id=1):
    watermark, upper, cursor, full_audit = expected
    now = _utcnow()
    with db._SessionLocal.begin() as session:
        # Both lanes may discover the same page concurrently. Serialize their
        # queue upserts through the shared state row before lane-local CAS.
        if state_id != 1:
            session.execute(select(CrmScanState).where(CrmScanState.id == 1)
                            .with_for_update()).scalar_one()
        row = session.execute(select(CrmScanState).where(CrmScanState.id == state_id)
                              .with_for_update()).scalar_one()
        if (_aware(row.watermark), _aware(row.window_end), row.cursor,
            bool(row.full_audit_active)) != expected:
            return False
        unique_candidates = {}
        lower = None if full_audit or watermark is None else watermark - LOOKBACK
        for page_id, edited_string in candidates:
            edited = _parse_edited(edited_string)
            if edited > upper or (lower is not None and edited < lower):
                raise notion.CrmSourceUnavailable("out_of_window_page")
            previous = unique_candidates.get(page_id)
            if previous is None or edited > previous:
                unique_candidates[page_id] = edited
        for page_id, edited in unique_candidates.items():
            # A repeated inclusive-boundary page is harmless. A newer source
            # revision reopens the item, including one currently leased.
            existing = session.get(CrmPageQueue, page_id)
            if existing is None:
                session.add(CrmPageQueue(page_id=page_id, edited_at=edited,
                                         queued_at=now, due_at=now))
            elif (edited > _aware(existing.edited_at) or
                  (full_audit and existing.completed_at is not None and
                   now - _aware(existing.completed_at) >= AUDIT_INTERVAL)):
                existing.edited_at = edited
                existing.queued_at = now
                existing.due_at = now
                existing.completed_at = None
                existing.attempts = 0
                existing.last_reason = None
        if next_cursor:
            row.cursor = next_cursor
        else:
            row.watermark = upper
            if full_audit:
                row.last_full_audit_at = now
            row.full_audit_active = False
            row.window_end = None
            row.cursor = None
            row.cursor_reset_count = 0
        row.updated_at = now
    return True


def _reset_expired_cursor(expected, *, state_id=1):
    # One reset per pinned window; persistent malformed 400s remain held for
    # diagnosis instead of rescanning the same prefix indefinitely.
    with db._SessionLocal.begin() as session:
        row = session.execute(select(CrmScanState).where(CrmScanState.id == state_id)
                              .with_for_update()).scalar_one()
        current = (_aware(row.watermark), _aware(row.window_end), row.cursor,
                   bool(row.full_audit_active))
        if current != expected:
            return False
        if row.cursor_reset_count >= 1:
            return None
        row.cursor = None
        row.cursor_reset_count += 1
        row.updated_at = _utcnow()
        return True


def scan(*, deadline, state_id=1, max_pages=MAX_SCAN_PAGES_PER_TICK):
    count = 0
    pages = 0
    resets = 0
    while pages < max_pages and time.monotonic() < deadline:
        expected = _state(state_id=state_id)
        if expected is None:
            break
        watermark, upper, cursor, full_audit = expected
        lower = None if full_audit or watermark is None else watermark - LOOKBACK
        if not _rate_slot(deadline=deadline):
            break
        try:
            candidates, next_cursor = notion.query_crm_edit_window(
                lower=lower, upper=upper, cursor=cursor, deadline=deadline)
            if not _save_scan_page(expected, candidates, next_cursor, state_id=state_id):
                # Another worker advanced the same window; retry its current
                # cursor rather than writing duplicate or stale state.
                continue
        except notion.CrmSourceUnavailable as error:
            if error.reason == "expired_query_cursor" and resets < 1:
                reset = _reset_expired_cursor(expected, state_id=state_id)
                if reset is True:
                    resets += 1
                    continue
                if reset is False:
                    continue
                logger.warning("CRM scan held: cursor reset exhausted")
                break
            if error.reason == "rate_limited":
                _pause_source(error.retry_after)
            logger.warning("CRM scan held: %s", error.reason)
            break
        count += len(candidates)
        pages += 1
        if next_cursor is None:
            break
    return {"scan_pages": pages, "enqueued_candidates": count}


def _needs_action_predicate():
    return ((CrmPageQueue.attempts >= MAX_REVISION_ATTEMPTS) &
            func.coalesce(CrmPageQueue.last_reason, "").in_(NEEDS_ACTION_REASONS))


def _claim():
    now = _utcnow()
    with db._SessionLocal.begin() as session:
        row = session.execute(select(CrmPageQueue).where(
            CrmPageQueue.completed_at.is_(None),
            ~_needs_action_predicate(), CrmPageQueue.due_at <= now,
            (CrmPageQueue.lease_until.is_(None) | (CrmPageQueue.lease_until <= now)),
        ).order_by(CrmPageQueue.due_at, CrmPageQueue.queued_at)
          .limit(1).with_for_update(skip_locked=True)).scalar_one_or_none()
        if row is None:
            return None
        token = str(uuid.uuid4())
        row.lease_token = token
        row.lease_until = now + timedelta(seconds=STALE_LEASE_SECONDS)
        return (row.page_id, _aware(row.edited_at), token)


def _release_claim(claim):
    page_id, _edited, token = claim
    with db._SessionLocal.begin() as session:
        row = session.execute(select(CrmPageQueue).where(CrmPageQueue.page_id == page_id)
                              .with_for_update()).scalar_one_or_none()
        if row is not None and row.lease_token == token:
            row.lease_token = None
            row.lease_until = None
            row.due_at = _utcnow() + timedelta(seconds=1)


def _finish(claim, *, reason=None, retry_after=1):
    page_id, edited, token = claim
    now = _utcnow()
    with db._SessionLocal.begin() as session:
        row = session.execute(select(CrmPageQueue).where(CrmPageQueue.page_id == page_id)
                              .with_for_update()).scalar_one_or_none()
        if row is None or row.lease_token != token:
            return False
        row.lease_token = None
        row.lease_until = None
        if _aware(row.edited_at) != edited:
            # The scanner enqueued a newer edit during this attempt.
            return False
        if reason is None:
            row.completed_at = now
            row.last_reason = None
        else:
            reason_code = reason[:40]
            if row.last_reason != reason_code:
                row.attempts = 0
            row.attempts += 1
            row.last_reason = reason_code
            if reason_code in NEEDS_ACTION_REASONS and row.attempts >= MAX_REVISION_ATTEMPTS:
                # Hold this exact source revision for operator action. A newer
                # edit resets attempts and reopens the same durable queue row.
                row.due_at = now
            else:
                delay = max(retry_after, min(3600, 2 ** min(row.attempts, 8)))
                row.due_at = now + timedelta(seconds=delay)
        return True


def _assert_claim_current(session, claim):
    if claim is None:
        return
    page_id, edited, token = claim
    row = session.execute(select(CrmPageQueue).where(CrmPageQueue.page_id == page_id)
                          .with_for_update()).scalar_one_or_none()
    if row is None or row.lease_token != token or _aware(row.edited_at) != edited:
        raise notion.CrmSourceUnavailable("claim_superseded")


def _reconcile_page(page, *, deadline=None, claim=None):
    """Recheck exact page ownership and preserve current create-only behavior."""
    page_id = page["id"]
    props = page["properties"]
    with db._SessionLocal() as session:
        owner = session.execute(select(Campaign).where(Campaign.notion_page_id == page_id))\
                       .scalar_one_or_none()
        owner_slug = owner.slug if owner else None
    if owner_slug:
        captions_prop = props.get(notion.CAPTIONS_PROPERTY)
        captions = notion._parse_internal_captions(page_id, props,
                                                    deadline=deadline, strict=True,
                                                    before_request=_rate_slot)
        if (isinstance(captions_prop, dict) and
            isinstance(captions_prop.get("rich_text"), list) and
            len(captions_prop["rich_text"]) >= notion._INLINE_RICH_TEXT_LIMIT and
            captions is None):
            raise notion.CrmSourceUnavailable("caption_property_unreadable")
        fields = {"content_types": notion._parse_content_types(props),
                  "internal_captions": captions}
        # Re-read under a row lock after source I/O; never retarget a slug that
        # another writer relinked during the request.
        with db._SessionLocal.begin() as session:
            _assert_claim_current(session, claim)
            owner = session.execute(select(Campaign).where(Campaign.slug == owner_slug)
                                    .with_for_update()).scalar_one_or_none()
            if owner is None or owner.notion_page_id != page_id:
                raise notion.CrmSourceUnavailable("owner_changed")
            if owner.completion_status not in ("none", "booked"):
                return
            if fields["content_types"] is not None and fields["content_types"] != owner.content_types:
                owner.content_types = fields["content_types"]
            if fields["internal_captions"] is not None and fields["internal_captions"] != owner.internal_captions:
                owner.internal_captions = fields["internal_captions"]
        return
    if notion._get_status(props.get("Pipeline Status", {})) != "Client":
        return
    entries = notion.parse_client_pages(
        [page], set(), strict_captions=True, deadline=deadline,
        before_request=_rate_slot,
    )
    if not entries:
        # Malformed source content is not proof that the edit was reconciled.
        raise notion.CrmSourceUnavailable("malformed_client_row", 60)
    entry = entries[0]
    slug = entry["slug"]
    if db.campaign_exists(slug):
        # Existing slug owned by another CRM page or local writer. Preserve it;
        # this business conflict stays queued and visible in lag diagnostics.
        raise notion.CrmSourceUnavailable("slug_conflict", 300)
    meta = {
        "title": entry["title"], "name": entry["title"], "slug": slug,
        "artist": entry["artist"], "song": entry["song"],
        "official_sound": entry["official_sound"], "sound_id": entry["sound_id"],
        "start_date": entry["start_date"], "budget": entry["budget"],
        "status": "queued", "platform": "tiktok", "created_at": _utcnow().isoformat(),
        "stats": {"total_views": 0, "total_likes": 0}, "source": "notion",
        "notion_page_id": page_id, "insta_sound": entry.get("insta_sound", ""),
        "cobrand_share_url": entry.get("cobrand_share_url", ""),
        "campaign_stage": entry.get("campaign_stage", ""), "round": entry.get("round", ""),
        "label": entry.get("label", ""), "project_lead": entry.get("project_lead", []),
        "client_email": entry.get("client_email", ""),
        "content_types": entry.get("content_types") or [],
        "internal_captions": entry.get("internal_captions"),
        "platform_split": entry.get("platform_split", {}),
    }
    sound_url = db._canonical_sound_url(meta["official_sound"])
    # Keep the page lease locked through create-only insertion. A stale worker
    # must not write after another worker or scan has taken its revision.
    with db._SessionLocal.begin() as session:
        _assert_claim_current(session, claim)
        result = db.save_campaign(slug, meta,
                                  expected_official_sound="" if sound_url is not None else None,
                                  create_only=True)
    if result in ("conflict", "duplicate", "missing_revision"):
        raise notion.CrmSourceUnavailable("create_conflict", 300)
    if result not in (None, "updated"):
        raise notion.CrmSourceUnavailable("save_failed")


def work(*, deadline):
    handled = 0
    failed = 0
    while handled + failed < MAX_WORK_PER_TICK and time.monotonic() < deadline:
        claim = _claim()
        if claim is None:
            break
        if not _rate_slot(deadline=deadline):
            _release_claim(claim)
            break
        try:
            page = notion.fetch_crm_page_for_queue(claim[0], deadline=deadline)
            if _parse_edited(page.get("last_edited_time")) < claim[1]:
                raise notion.CrmSourceUnavailable("stale_exact_page")
            _reconcile_page(page, deadline=min(deadline, time.monotonic() + PROPERTY_BUDGET_SECONDS),
                            claim=claim)
            _finish(claim)
            handled += 1
        except notion.CrmSourceUnavailable as error:
            _finish(claim, reason=error.reason, retry_after=error.retry_after)
            failed += 1
            if error.reason == "rate_limited":
                _pause_source(error.retry_after)
                break
        except Exception as error:
            logger.warning("CRM queue processing raised %s for one page", type(error).__name__)
            _finish(claim, reason="processing_error")
            failed += 1
    return {"handled": handled, "failed": failed}


def metrics():
    now = _utcnow()
    with db._SessionLocal() as session:
        depth, oldest = session.execute(select(
            func.count(), func.min(CrmPageQueue.queued_at),
        ).where(CrmPageQueue.completed_at.is_(None))).one()
        needs_action, needs_action_oldest = session.execute(select(
            func.count(), func.min(CrmPageQueue.queued_at),
        ).where(CrmPageQueue.completed_at.is_(None),
                _needs_action_predicate())).one()
        reasons = {reason: count for reason, count in session.execute(select(
            CrmPageQueue.last_reason, func.count(),
        ).where(CrmPageQueue.completed_at.is_(None),
                ~_needs_action_predicate(),
                CrmPageQueue.last_reason.isnot(None))
         .group_by(CrmPageQueue.last_reason)).all()}
        needs_action_reasons = {reason: count for reason, count in session.execute(select(
            CrmPageQueue.last_reason, func.count(),
        ).where(CrmPageQueue.completed_at.is_(None),
                _needs_action_predicate(),
                CrmPageQueue.last_reason.isnot(None))
         .group_by(CrmPageQueue.last_reason)).all()}
        state = session.get(CrmScanState, 1)
        delta = session.get(CrmScanState, DELTA_STATE_ID)
    lag = int((now - _aware(oldest)).total_seconds()) if oldest else 0
    needs_action_lag = int((now - _aware(needs_action_oldest)).total_seconds()) if needs_action_oldest else 0
    reference = (state.watermark or state.window_end) if state else None
    watermark_lag = int((now - _aware(reference)).total_seconds()) if reference else None
    delta_reference = (delta.watermark or delta.window_end) if delta else None
    delta_lag = int((now - _aware(delta_reference)).total_seconds()) if delta_reference else None
    return {"depth": depth, "actionable_depth": depth - needs_action,
            "needs_action": needs_action,
            "needs_action_oldest_lag_seconds": needs_action_lag,
            "needs_action_reasons": needs_action_reasons,
            "oldest_queue_lag_seconds": lag,
            "scan_watermark_lag_seconds": watermark_lag,
            "delta_watermark_lag_seconds": delta_lag, "retry_reasons": reasons}


def run_tick():
    if not db.is_active() or getattr(db._engine.dialect, "name", "") != "postgresql":
        logger.warning("CRM queue requires PostgreSQL; refusing non-durable discovery")
        return
    deadline = time.monotonic() + TICK_SECONDS
    scan_started = time.monotonic()
    scan_deadline = min(deadline, scan_started + SCAN_BUDGET_SECONDS)
    delta_result = scan(deadline=scan_deadline, state_id=DELTA_STATE_ID,
                        max_pages=DELTA_SCAN_PAGES_PER_TICK)
    audit_result = scan(deadline=scan_deadline,
                        max_pages=FULL_SCAN_PAGES_PER_TICK)
    scan_result = {"delta": delta_result, "audit": audit_result}
    scan_seconds = round(time.monotonic() - scan_started, 3)
    work_started = time.monotonic()
    if _source_paused():
        work_result = {"handled": 0, "failed": 0, "source_paused": True}
    else:
        work_result = work(deadline=deadline)
    work_seconds = round(time.monotonic() - work_started, 3)
    state = metrics()
    logger.info("CRM queue: scan=%s scan_seconds=%s work=%s work_seconds=%s backlog=%s",
                scan_result, scan_seconds, work_result, work_seconds, state)
    if state["oldest_queue_lag_seconds"] > WARNING_LAG_SECONDS or (
        state["scan_watermark_lag_seconds"] is not None and
        state["scan_watermark_lag_seconds"] > WARNING_LAG_SECONDS
    ) or (
        state["delta_watermark_lag_seconds"] is not None and
        state["delta_watermark_lag_seconds"] > WARNING_LAG_SECONDS
    ):
        logger.warning("CRM queue behind target: %s", state)
