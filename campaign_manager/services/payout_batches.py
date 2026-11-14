"""Batch payouts: draft -> Jake approves -> PayPal/Venmo via API, Cash App /
other as a manual checklist -> bookings marked paid when money lands.

Safety rails:
  - Nothing is sent without approve(), which needs the exact API-lane total
    typed back (guards against a stray click).
  - Destinations are re-checked at approval; any change since the draft was
    built aborts the send.
  - A booking can sit in only one open item, and drops out of the queue
    while it does, so it can't be paid twice.
  - A persisted attempt is dispatched once; unknown outcomes are held for
    exact original-receipt reconciliation with GET, never another POST.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, text

from campaign_manager.models import (
    Campaign, Creator, CreatorProfile, OPEN_PAYOUT_ITEM_STATUSES, PayoutBatch, PayoutItem,
)
from campaign_manager.services.creator_library import normalize_username
from campaign_manager.services.payout_readiness import booking_state, build_queue, find_booking
from campaign_manager.services.paypal_payouts import PayPalError, validate_provider_id

API_METHODS = ("paypal", "venmo")
OPEN_ITEM_STATUSES = OPEN_PAYOUT_ITEM_STATUSES
MAX_BATCH_ITEMS = 500
# One lock id for every batch mutation: serializes create/approve across
# gunicorn workers so two drafts can never claim the same bookings.
_BATCH_LOCK_ID = 7_241_030
_PAYPAL_SUCCESS = {"SUCCESS"}
# Definitely not delivered -> safe to put back in the queue.
_PAYPAL_FAILED = {"FAILED", "RETURNED", "BLOCKED", "DENIED", "CANCELED"}
# Money was delivered then pulled back -> a human decides; never auto-requeue.
_PAYPAL_REVIEW = {"REFUNDED", "REVERSED"}
_PAYPAL_UNCLAIMED = {"UNCLAIMED"}
_PAYPAL_PENDING = {"PENDING", "ONHOLD", "NEW"}
_KNOWN_ITEM_STATUSES = _PAYPAL_SUCCESS | _PAYPAL_FAILED | _PAYPAL_REVIEW | _PAYPAL_UNCLAIMED | _PAYPAL_PENDING
_BATCH_STATUSES = {"PENDING", "PROCESSING", "SUCCESS", "DENIED", "CANCELED"}
_UNKNOWN_SEND = "Payment outcome is unknown. Reconcile the original PayPal receipt before any further payment; this attempt will not be sent again."


class BatchError(ValueError):
    """Message is safe to show Jake."""


def _lock(session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _BATCH_LOCK_ID})


def has_open_item(session, campaign_id: int, username: str, platform: str) -> bool:
    return session.execute(
        select(PayoutItem.id)
        .where(PayoutItem.campaign_id == campaign_id)
        .where(PayoutItem.username == normalize_username(username))
        .where(PayoutItem.platform == (platform or "tiktok").lower())
        .where(PayoutItem.status.in_(OPEN_ITEM_STATUSES))
    ).first() is not None


def open_item_keys(session) -> set[tuple]:
    rows = session.execute(
        select(PayoutItem.campaign_id, PayoutItem.username, PayoutItem.platform)
        .where(PayoutItem.status.in_(OPEN_ITEM_STATUSES))
    ).all()
    return {tuple(r) for r in rows}


def open_items_by_key(session) -> dict[tuple, dict]:
    """(campaign_id, username, platform) -> the open payout item for it."""
    rows = session.execute(
        select(PayoutItem, PayoutBatch)
        .join(PayoutBatch, PayoutItem.batch_id == PayoutBatch.id)
        .where(PayoutItem.status.in_(OPEN_ITEM_STATUSES))
    ).all()
    return {
        (i.campaign_id, i.username, i.platform): {
            "item_id": i.id, "item_status": i.status, "batch_id": b.id, "batch_status": b.status,
        }
        for i, b in rows
    }


def _open_batch(session):
    return session.execute(
        select(PayoutBatch).where(PayoutBatch.status.in_(("draft", "sending")))
    ).scalars().first()


def _draft(session, *, create: bool) -> PayoutBatch | None:
    """The open draft ("today's payments"), optionally creating it."""
    existing = _open_batch(session)
    if existing is not None:
        if existing.status == "sending":
            raise BatchError("Today's payments have an unresolved send. Reconcile the original receipt first.")
        return existing
    if not create:
        return None
    batch = PayoutBatch(status="draft", sender_batch_id=f"rt-{date.today():%Y%m%d}-{uuid.uuid4().hex[:12]}")
    session.add(batch)
    session.flush()
    return batch


def _add_item(session, batch: PayoutBatch, row: dict) -> None:
    if len(_live_items(batch)) >= MAX_BATCH_ITEMS:
        raise BatchError(f"Today's payments are full ({MAX_BATCH_ITEMS}). Send these first.")
    session.add(PayoutItem(
        batch_id=batch.id, campaign_id=row["campaign_id"], campaign_title=row["campaign"],
        username=row["username"], platform=row["platform"], amount=row["amount"],
        method=row["method"], destination=row["destination"],
        lane="api" if row["method"] in API_METHODS else "manual", status="queued",
    ))
    session.flush()
    session.refresh(batch)


def create_draft(session) -> PayoutBatch | None:
    """Add everyone ready AND payable (confirmed, unflagged details, a real
    amount) to today's payments. Reuses the open draft if there is one."""
    _lock(session)
    rows = [r for r in build_queue(session)["ready"]
            if not r["destination_issue"] and _payable_amount(r["amount"])]
    batch = _draft(session, create=bool(rows))
    if batch is None:
        return None
    for r in rows:
        _add_item(session, batch, r)
    session.commit()
    return batch


def add_booking(session, slug: str, username: str, platform: str) -> PayoutBatch:
    """The per-creator "Pay" button: add one ready booking to today's payments."""
    _lock(session)
    user, plat = normalize_username(username), (platform or "tiktok").lower()
    row = next((r for r in build_queue(session)["ready"]
                if (r["slug"], r["username"], r["platform"]) == (slug, user, plat)), None)
    if row is None:
        raise BatchError(f"@{user} isn't ready to pay on this campaign (or is already in a payment).")
    if row["destination_issue"] == "missing":
        raise BatchError(f"@{user} hasn't given payment info yet — send them their link.")
    if row["destination_issue"] == "changed":
        raise BatchError(f"@{user}'s payment info changed — review it on the Payment info tab first.")
    if row["destination_issue"] == "unconfirmed":
        raise BatchError(f"@{user} hasn't confirmed their payment info yet — send them their link.")
    if not _payable_amount(row["amount"]):
        raise BatchError(f"@{user} has no rate on this booking — add one on the campaign page.")
    batch = _draft(session, create=True)
    _add_item(session, batch, row)
    session.commit()
    return batch


def _payable_amount(amount) -> bool:
    """A $0 / negative / NaN item makes PayPal reject the whole batch."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0


def _get(session, batch_id: int, *, lock: bool = False) -> PayoutBatch:
    batch = session.get(PayoutBatch, batch_id, with_for_update=lock, populate_existing=lock)
    if batch is None:
        raise BatchError("Batch not found.")
    if lock:
        session.expire(batch, ["items"])
    return batch


def _live_items(batch, lane=None):
    return [i for i in batch.items if i.status != "removed" and (lane is None or i.lane == lane)]


def remove_item(session, item_id: int) -> None:
    _lock(session)
    item = session.get(PayoutItem, item_id, with_for_update=True, populate_existing=True)
    if item is None or _get(session, item.batch_id, lock=True).status != "draft":
        raise BatchError("Only items in a draft batch can be removed.")
    item.status = "removed"
    session.commit()


def cancel_draft(session, batch_id: int) -> None:
    _lock(session)
    batch = _get(session, batch_id, lock=True)
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
        if (current != (item.method, item.destination) or not profile
                or profile.payout_change_flagged or not profile.payout_confirmed_by_creator):
            raise BatchError(
                f"@{item.username}'s payment details changed after this batch was built. "
                "Remove them or cancel and rebuild the batch."
            )


def _check_bookings_still_payable(session, items) -> None:
    """Re-read every booking at approval: the draft is a snapshot, and the
    rate / paid flag / posts can change in between (F2)."""
    for item in items:
        booking, campaign, state = booking_state(session, item.campaign_id, item.username, item.platform)
        who = f"@{item.username} ({item.campaign_title})"
        if booking is None or campaign is None:
            raise BatchError(f"{who}: booking is missing or ambiguous. Remove it from the batch.")
        if (campaign.completion_status or "none") == "completed":
            raise BatchError(f"{who}: campaign was marked finished. Remove it from the batch.")
        if state == "paid":
            raise BatchError(f"{who}: already marked paid in the Hub. Remove it from the batch.")
        if state != "ready":
            raise BatchError(f"{who}: no longer ready for payment. Remove it from the batch.")
        if round(float(booking.total_rate or 0), 2) != round(item.amount, 2):
            raise BatchError(
                f"{who}: rate changed from ${item.amount:,.2f} to ${float(booking.total_rate or 0):,.2f} "
                "since the batch was built. Cancel and rebuild."
            )


def approve(session, batch_id: int, confirm_total, client) -> PayoutBatch:
    """Send the API lane through PayPal and open the manual lane.

    `client` is a PayPalPayouts, or None when PayPal isn't connected (only
    allowed if the batch has no PayPal/Venmo items)."""
    _lock(session)
    batch = _get(session, batch_id, lock=True)
    if batch.status == "sending":
        raise BatchError(_UNKNOWN_SEND)
    if batch.status != "draft":
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
    _check_bookings_still_payable(session, _live_items(batch))
    if api_items and client is None:
        raise BatchError("PayPal isn't connected yet, so PayPal/Venmo items can't be sent.")
    if api_items:
        prepare = getattr(client, "prepare_payout", None)
        if callable(prepare):
            prepare()  # OAuth failure leaves the draft untouched; no funds POST happened.

    batch.approved_at = datetime.now()
    if api_items:
        if client.env not in ("live", "sandbox"):
            raise BatchError("Invalid PayPal environment.")
        batch.status = "sending"
        batch.paypal_env = client.env
        # Commit the immutable attempt before crossing the provider boundary.
        session.commit()
        try:
            response = client.create_payout(batch.sender_batch_id, api_items)
        except Exception:
            response = None
        # Reconciliation may have completed while the create response was in
        # flight. Never overwrite its settlement or downgrade its item states.
        _lock(session)
        session.expire_all()
        batch = _get(session, batch_id, lock=True)
        if batch.status != "sending" or batch.paypal_batch_id:
            return batch
        try:
            provider_id = _verify_header(response, batch)
        except BatchError:
            batch.error = _UNKNOWN_SEND
            session.commit()
            raise BatchError(_UNKNOWN_SEND) from None
        batch.paypal_batch_id = provider_id
        for item in _live_items(batch, "api"):
            item.status = "pending"
    for item in _live_items(batch, "manual"):
        item.status = "pending"
    batch.status = "sent"
    batch.error = ""
    session.commit()
    return batch


def _cents(value) -> Decimal:
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise InvalidOperation
        cents = number.quantize(Decimal("0.01"))
        if number != cents:
            raise InvalidOperation
        return cents
    except (InvalidOperation, ValueError, TypeError):
        raise BatchError("Payment receipt has an invalid amount.") from None


def _valid_provider_id(value) -> str:
    try:
        return validate_provider_id(value)
    except PayPalError:
        raise BatchError("Enter a valid original PayPal batch ID.") from None


def _verify_header(data, batch, requested_id=None) -> str:
    if not isinstance(data, dict) or not isinstance(data.get("batch_header"), dict):
        raise BatchError("PayPal receipt is missing its batch header.")
    header = data["batch_header"]
    provider_id = _valid_provider_id(header.get("payout_batch_id"))
    sender = header.get("sender_batch_header")
    status = header.get("batch_status")
    if (not isinstance(sender, dict) or sender.get("sender_batch_id") != batch.sender_batch_id
            or (requested_id is not None and provider_id != requested_id)
            or not isinstance(status, str) or status not in _BATCH_STATUSES):
        raise BatchError("PayPal receipt does not match the original batch.")
    return provider_id


def _verify_receipt(data, batch, requested_id) -> list[tuple]:
    """Validate the entire API lane before applying any financial state."""
    _verify_header(data, batch, requested_id)
    expected = {f"item-{item.id}": item for item in _live_items(batch, "api")}
    rows = data.get("items")
    if not expected or not isinstance(rows, list) or len(rows) != len(expected):
        raise BatchError("PayPal receipt has incomplete or unexpected items.")
    reported_count = data.get("total_items")
    if reported_count is not None and (
            isinstance(reported_count, bool) or not isinstance(reported_count, int)
            or reported_count != len(rows)):
        raise BatchError("PayPal receipt's item count is incomplete or inconsistent.")
    seen, provider_ids, verified = set(), set(), []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("payout_item"), dict):
            raise BatchError("PayPal receipt contains an invalid item.")
        payout = row["payout_item"]
        identity = payout.get("sender_item_id")
        if not isinstance(identity, str) or identity not in expected or identity in seen:
            raise BatchError("PayPal receipt has duplicate or unexpected item identities.")
        item = expected[identity]
        provider_item_id = _valid_provider_id(row.get("payout_item_id"))
        if provider_item_id in provider_ids or (item.provider_item_id and item.provider_item_id != provider_item_id):
            raise BatchError("PayPal receipt changed an item's provider identity.")
        amount = payout.get("amount")
        expected_type = "USER_HANDLE" if item.method == "venmo" else "EMAIL"
        wallet = payout.get("recipient_wallet", "PAYPAL" if item.method == "paypal" else "")
        expected_wallet = "VENMO" if item.method == "venmo" else "PAYPAL"
        status = row.get("transaction_status")
        if (not isinstance(amount, dict)
                or amount.get("currency") != (item.currency or "USD")
                or _cents(amount.get("value")) != _cents(f"{item.amount:.2f}")
                or payout.get("receiver") != item.destination
                or payout.get("recipient_type") != expected_type
                or not isinstance(wallet, str) or wallet.upper() != expected_wallet
                or not isinstance(status, str) or status not in _KNOWN_ITEM_STATUSES):
            raise BatchError("PayPal receipt does not match the original amount, destination or wallet.")
        if data["batch_header"]["batch_status"] in {"DENIED", "CANCELED"} and status not in _PAYPAL_FAILED:
            raise BatchError("PayPal receipt has conflicting batch and payment outcomes.")
        seen.add(identity)
        provider_ids.add(provider_item_id)
        verified.append((item, row))
    return verified


def _mark_booking_paid(session, item: PayoutItem, when: datetime) -> bool:
    """Settle one unchanged canonical obligation; never choose or update aliases."""
    booking = find_booking(session, item.campaign_id, item.username, item.platform, lock=True)
    if booking is None:
        item.error = "Payment delivered, but the booking is missing or ambiguous. Reconcile the booking before any further payment."
        return False
    try:
        unchanged = _cents(booking.total_rate) == _cents(f"{item.amount:.2f}")
    except BatchError:
        unchanged = False
    if not unchanged:
        item.error = "Payment delivered, but the booking amount changed. Reconcile the outstanding obligation before any further payment."
        return False
    if str(booking.paid or "").strip().lower() == "yes":
        item.error = "Payment delivered, but the booking was already marked paid. Reconcile possible duplicate payment; existing history was preserved."
        return False
    booking.paid = "yes"
    booking.payment_date = when.date().isoformat()
    return True


def _settle(session, item: PayoutItem, succeeded: bool) -> None:
    if not succeeded or item.status == "succeeded":
        return
    if item.lane == "api" and item.batch.paypal_env != "live":
        # Sandbox rehearsal: record it, but never mark real bookings paid,
        # and release the booking back to the queue.
        item.status = "sandbox_ok"
        return
    item.paid_at = item.paid_at or datetime.now()
    item.status = "succeeded" if _mark_booking_paid(session, item, item.paid_at) else "review"


def mark_manual_paid(session, item_id: int) -> None:
    _lock(session)
    item = session.get(PayoutItem, item_id, with_for_update=True, populate_existing=True)
    if item is None or item.lane != "manual":
        raise BatchError("Only Cash App / other items are marked paid by hand.")
    batch = _get(session, item.batch_id, lock=True)
    if batch.status not in ("sent", "closed") or item.status != "pending":
        raise BatchError("Approve the batch first, then mark each manual payment as sent.")
    _settle(session, item, True)
    _maybe_close(batch)
    session.commit()


def _maybe_close(batch) -> None:
    if all(i.status in ("succeeded", "sandbox_ok", "failed", "removed") for i in batch.items):
        batch.status = "closed"
    elif batch.status == "closed":
        batch.status = "sent"  # a later reversal requires review


def reconcile(session, batch_id: int, paypal_batch_id, client) -> PayoutBatch:
    """Bind and reconcile an original provider receipt using GET only."""
    provider_id = _valid_provider_id(paypal_batch_id)
    _lock(session)
    batch = _get(session, batch_id, lock=True)
    if batch.status not in ("sending", "sent", "closed"):
        raise BatchError("Approve the batch before reconciling its original receipt.")
    if client is None or client.env != batch.paypal_env:
        raise BatchError(f"Use the original PayPal {batch.paypal_env} environment to reconcile this payment.")
    if batch.paypal_batch_id and batch.paypal_batch_id != provider_id:
        raise BatchError("This batch is already bound to a different PayPal receipt.")
    data = client.get_batch(provider_id)
    verified = _verify_receipt(data, batch, provider_id)
    # No binding, timestamps, item status or paid flags change until every
    # header and item has matched the immutable original snapshot.
    batch.paypal_batch_id = provider_id
    for item, row in verified:
        status = row["transaction_status"]
        if item.status in ("removed", "failed"):
            continue  # failed items may already belong to a later payment
        item.provider_status = status
        item.provider_item_id = row["payout_item_id"]
        if status in _PAYPAL_REVIEW:
            item.status = "review"
            item.error = f"PayPal says {status} — reconcile the original payment before paying again."
        elif item.status in ("succeeded", "sandbox_ok", "review"):
            if item.status == "succeeded" and status not in _PAYPAL_SUCCESS:
                item.status = "review"
                item.error = "PayPal changed a settled payment's outcome. Reconcile it before paying again."
        elif status in _PAYPAL_SUCCESS:
            _settle(session, item, True)
        elif status in _PAYPAL_FAILED:
            item.status = "failed"
            item.error = f"PayPal reports {status}."
        elif status in _PAYPAL_UNCLAIMED:
            item.status = "unclaimed"
        else:
            item.status = "pending"
    for item in _live_items(batch, "manual"):
        if item.status == "queued":
            item.status = "pending"
    batch.status = "sent"
    batch.error = ""
    batch.last_synced_at = datetime.now()
    _maybe_close(batch)
    session.commit()
    return batch


def sync(session, batch_id: int, client) -> PayoutBatch:
    batch = _get(session, batch_id)
    if not batch.paypal_batch_id:
        raise BatchError("Reconcile this payment with its original PayPal batch ID; it will not be sent again.")
    return reconcile(session, batch_id, batch.paypal_batch_id, client)


def batch_dict(batch: PayoutBatch) -> dict:
    items = [i.to_dict() for i in batch.items if i.status != "removed"]
    total = lambda lane: round(sum(i["amount"] for i in items if i["lane"] == lane), 2)  # noqa: E731
    return {
        "id": batch.id,
        "status": batch.status,
        "paypal_env": batch.paypal_env or "",
        "paypal_batch_id": batch.paypal_batch_id or "",
        "sender_batch_id": batch.sender_batch_id,
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
