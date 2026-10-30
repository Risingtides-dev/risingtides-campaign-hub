"""Batch payouts: draft -> Jake approves -> PayPal/Venmo via API, Cash App /
other as a manual checklist -> bookings marked paid when money lands.

Safety rails:
  - Nothing is sent without approve(), which needs the exact API-lane total
    typed back (guards against a stray click).
  - Destinations are re-checked at approval; any change since the draft was
    built aborts the send.
  - A booking can sit in only one open item, and drops out of the queue
    while it does, so it can't be paid twice.
  - PayPal's sender_batch_id makes a retried send idempotent.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import func, select, update

from campaign_manager.models import Creator, CreatorProfile, PayoutBatch, PayoutItem
from campaign_manager.services.payout_readiness import build_queue
from campaign_manager.services.paypal_payouts import PayPalError

API_METHODS = ("paypal", "venmo")
OPEN_ITEM_STATUSES = ("queued", "pending", "succeeded", "unclaimed")
_PAYPAL_SUCCESS = {"SUCCESS"}
_PAYPAL_FAILED = {"FAILED", "RETURNED", "BLOCKED", "REFUNDED", "REVERSED", "DENIED", "CANCELED"}
_PAYPAL_UNCLAIMED = {"UNCLAIMED"}


class BatchError(ValueError):
    """Message is safe to show Jake."""


def open_item_keys(session) -> set[tuple]:
    rows = session.execute(
        select(PayoutItem.campaign_id, PayoutItem.username, PayoutItem.platform)
        .where(PayoutItem.status.in_(OPEN_ITEM_STATUSES))
    ).all()
    return {tuple(r) for r in rows}


def _open_batch(session):
    return session.execute(
        select(PayoutBatch).where(PayoutBatch.status.in_(("draft", "sending")))
    ).scalars().first()


def create_draft(session) -> PayoutBatch | None:
    """Snapshot everyone ready AND payable (confirmed, unflagged details).
    Returns the existing open batch instead of making a second one."""
    existing = _open_batch(session)
    if existing is not None:
        return existing
    rows = [r for r in build_queue(session)["ready"] if not r["destination_issue"]]
    if not rows:
        return None
    batch = PayoutBatch(status="draft", sender_batch_id=f"rt-{date.today():%Y%m%d}-{uuid.uuid4().hex[:12]}")
    session.add(batch)
    session.flush()
    for r in rows:
        session.add(PayoutItem(
            batch_id=batch.id, campaign_id=r["campaign_id"], campaign_title=r["campaign"],
            username=r["username"], platform=r["platform"], amount=r["amount"],
            method=r["method"], destination=r["destination"],
            lane="api" if r["method"] in API_METHODS else "manual", status="queued",
        ))
    session.commit()
    return batch


def _get(session, batch_id: int) -> PayoutBatch:
    batch = session.get(PayoutBatch, batch_id)
    if batch is None:
        raise BatchError("Batch not found.")
    return batch


def _live_items(batch, lane=None):
    return [i for i in batch.items if i.status != "removed" and (lane is None or i.lane == lane)]


def remove_item(session, item_id: int) -> None:
    item = session.get(PayoutItem, item_id)
    if item is None or item.batch.status != "draft":
        raise BatchError("Only items in a draft batch can be removed.")
    item.status = "removed"
    session.commit()


def cancel_draft(session, batch_id: int) -> None:
    batch = _get(session, batch_id)
    if batch.status != "draft":
        raise BatchError("Only a draft batch can be cancelled.")
    batch.status = "cancelled"
    for item in batch.items:
        item.status = "removed"
    session.commit()


def _check_destinations_unchanged(session, items) -> None:
    for item in items:
        profile = session.get(CreatorProfile, item.username)
        current = (profile.payout_method, profile.payout_destination) if profile else ("", "")
        if current != (item.method, item.destination) or (profile and profile.payout_change_flagged):
            raise BatchError(
                f"@{item.username}'s payment details changed after this batch was built. "
                "Remove them or cancel and rebuild the batch."
            )


def approve(session, batch_id: int, confirm_total, client) -> PayoutBatch:
    """Send the API lane through PayPal and open the manual lane.

    `client` is a PayPalPayouts, or None when PayPal isn't connected (only
    allowed if the batch has no PayPal/Venmo items)."""
    batch = _get(session, batch_id)
    if batch.status not in ("draft", "sending"):
        raise BatchError("This batch was already approved.")
    api_items = _live_items(batch, "api")
    expected = round(sum(i.amount for i in api_items), 2)
    try:
        typed = round(float(confirm_total), 2)
    except (TypeError, ValueError):
        raise BatchError("Type the PayPal/Venmo total to approve.") from None
    if typed != expected:
        raise BatchError(f"Total doesn't match — the PayPal/Venmo total is ${expected:,.2f}.")
    _check_destinations_unchanged(session, _live_items(batch))
    if api_items and client is None:
        raise BatchError("PayPal isn't connected yet, so PayPal/Venmo items can't be sent.")

    batch.approved_at = batch.approved_at or datetime.now()
    if api_items:
        batch.status = "sending"  # survives a crash mid-call; a retry reuses sender_batch_id
        batch.paypal_env = client.env
        session.commit()
        try:
            resp = client.create_payout(batch.sender_batch_id, api_items)
        except PayPalError as exc:
            batch.error = str(exc)
            session.commit()
            raise BatchError(f"{exc} Nothing was marked paid. You can retry safely.") from None
        batch.paypal_batch_id = (resp.get("batch_header") or {}).get("payout_batch_id", "")
        for item in api_items:
            item.status = "pending"
    for item in _live_items(batch, "manual"):
        item.status = "pending"
    batch.status = "sent"
    batch.error = ""
    session.commit()
    return batch


def _mark_booking_paid(session, item: PayoutItem, when: datetime) -> None:
    """In-place UPDATE (never save_creators, which rewrites every row)."""
    handle = func.lower(func.trim(Creator.username))
    session.execute(
        update(Creator)
        .where(Creator.campaign_id == item.campaign_id)
        .where(handle.in_([item.username, f"@{item.username}"]))
        .where(func.lower(func.coalesce(Creator.platform, "tiktok")) == item.platform)
        .where(func.coalesce(Creator.status, "active") != "removed")
        .values(paid="yes", payment_date=when.date().isoformat())
        .execution_options(synchronize_session=False)
    )


def _settle(session, item: PayoutItem, succeeded: bool) -> None:
    if succeeded and item.status != "succeeded":
        item.status = "succeeded"
        item.paid_at = datetime.now()
        _mark_booking_paid(session, item, item.paid_at)


def mark_manual_paid(session, item_id: int) -> None:
    item = session.get(PayoutItem, item_id)
    if item is None or item.lane != "manual":
        raise BatchError("Only Cash App / other items are marked paid by hand.")
    if item.batch.status not in ("sent", "closed") or item.status != "pending":
        raise BatchError("Approve the batch first, then mark each manual payment as sent.")
    _settle(session, item, True)
    _maybe_close(item.batch)
    session.commit()


def _maybe_close(batch) -> None:
    if all(i.status in ("succeeded", "failed", "removed") for i in batch.items):
        batch.status = "closed"


def sync(session, batch_id: int, client) -> PayoutBatch:
    """Pull per-item status from PayPal; mark successful bookings paid.
    Failed items go back to the queue for the next batch."""
    batch = _get(session, batch_id)
    if not batch.paypal_batch_id:
        return batch
    data = client.get_batch(batch.paypal_batch_id)
    by_id = {f"item-{i.id}": i for i in batch.items}
    for row in data.get("items") or []:
        sender_item_id = ((row.get("payout_item") or {}).get("sender_item_id")) or ""
        item = by_id.get(sender_item_id)
        if item is None or item.status in ("succeeded", "removed"):
            continue
        status = str(row.get("transaction_status") or "").upper()
        item.provider_status = status
        item.provider_item_id = row.get("payout_item_id") or item.provider_item_id
        if status in _PAYPAL_SUCCESS:
            _settle(session, item, True)
        elif status in _PAYPAL_FAILED:
            item.status = "failed"
            item.error = ((row.get("errors") or {}).get("message") or status)[:500]
        elif status in _PAYPAL_UNCLAIMED:
            item.status = "unclaimed"
    batch.last_synced_at = datetime.now()
    _maybe_close(batch)
    session.commit()
    return batch


def batch_dict(batch: PayoutBatch) -> dict:
    items = [i.to_dict() for i in batch.items if i.status != "removed"]
    total = lambda lane: round(sum(i["amount"] for i in items if i["lane"] == lane), 2)  # noqa: E731
    return {
        "id": batch.id,
        "status": batch.status,
        "paypal_env": batch.paypal_env or "",
        "created_at": batch.created_at.isoformat() if batch.created_at else "",
        "approved_at": batch.approved_at.isoformat() if batch.approved_at else "",
        "last_synced_at": batch.last_synced_at.isoformat() if batch.last_synced_at else "",
        "error": batch.error or "",
        "items": items,
        "totals": {"api": total("api"), "manual": total("manual"), "all": round(total("api") + total("manual"), 2)},
    }


def recent_batches(session, limit: int = 15) -> list[dict]:
    rows = session.execute(
        select(PayoutBatch).where(PayoutBatch.status != "cancelled")
        .order_by(PayoutBatch.created_at.desc(), PayoutBatch.id.desc()).limit(limit)
    ).scalars().all()
    return [batch_dict(b) for b in rows]
