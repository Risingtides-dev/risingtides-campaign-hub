"""Batch payout endpoints (admin key required on every route).

  GET  /api/payouts/admin/batches                  recent batches + PayPal connection
  POST /api/payouts/admin/batches                  build today's draft from the Ready list
  POST /api/payouts/admin/batches/add-booking      {slug, username, platform} -> "Pay" one creator
  POST /api/payouts/admin/batches/<id>/approve     {confirm_total} -> sends PayPal/Venmo
  POST /api/payouts/admin/batches/<id>/cancel      draft only
  POST /api/payouts/admin/batches/<id>/sync        pull PayPal status, mark paid
  POST /api/payouts/admin/items/<id>/remove        draft only
  POST /api/payouts/admin/items/<id>/mark-paid     Cash App / other, after paying by hand

Money only moves on /approve, which a human triggers from the Hub.
"""
from __future__ import annotations

from flask import Blueprint, current_app

from campaign_manager import db as _db
from campaign_manager.blueprints.payout_common import (
    admin_guard,
    db_error,
    json_response,
    log,
    request_body,
)
from campaign_manager.services import payout_batches as batches
from campaign_manager.services.paypal_payouts import PayPalConfig, PayPalError, PayPalPayouts

payout_batches_bp = Blueprint("payout_batches", __name__)


def _paypal_client():
    """PayPalPayouts, or None when not configured. Tests inject a fake via
    app.config['PAYPAL_CLIENT_FACTORY']."""
    factory = current_app.config.get("PAYPAL_CLIENT_FACTORY")
    if factory is not None:
        return factory()
    try:
        return PayPalPayouts(PayPalConfig.from_env())
    except PayPalError:
        return None


def _run(where: str, fn):
    blocked = admin_guard()
    if blocked:
        return blocked
    with _db.get_session() as session:
        try:
            return fn(session)
        except batches.BatchError as exc:
            session.rollback()
            return json_response({"error": str(exc)}, 400)
        except PayPalError as exc:
            session.rollback()
            return json_response({"error": str(exc)}, 502)
        except Exception as exc:
            session.rollback()
            return db_error(where, exc)


@payout_batches_bp.get("/api/payouts/admin/batches")
def list_batches():
    def go(session):
        client = _paypal_client()
        return json_response({
            "batches": batches.recent_batches(session),
            "paypal": {"connected": client is not None, "env": client.env if client else ""},
        })
    return _run("list batches", go)


@payout_batches_bp.post("/api/payouts/admin/batches")
def create_batch():
    def go(session):
        batch = batches.create_draft(session)
        if batch is None:
            return json_response({"error": "Nobody is ready and payable right now."}, 400)
        return json_response(batches.batch_dict(batch))
    return _run("create batch", go)


@payout_batches_bp.post("/api/payouts/admin/batches/add-booking")
def add_booking():
    def go(session):
        data = request_body()
        fields = [data.get(k) for k in ("slug", "username", "platform")]
        if not all(isinstance(v, str) and v.strip() for v in fields):
            return json_response({"error": "slug, username and platform are required"}, 400)
        return json_response(batches.batch_dict(batches.add_booking(session, *fields)))
    return _run("add booking", go)


@payout_batches_bp.post("/api/payouts/admin/batches/<int:batch_id>/approve")
def approve_batch(batch_id: int):
    def go(session):
        batch = batches.approve(session, batch_id, request_body().get("confirm_total"), _paypal_client())
        log.warning("payout batch %s approved (env=%s)", batch.id, batch.paypal_env or "manual-only")
        return json_response(batches.batch_dict(batch))
    return _run("approve batch", go)


@payout_batches_bp.post("/api/payouts/admin/batches/<int:batch_id>/cancel")
def cancel_batch(batch_id: int):
    def go(session):
        batches.cancel_draft(session, batch_id)
        return json_response({"ok": True})
    return _run("cancel batch", go)


@payout_batches_bp.post("/api/payouts/admin/batches/<int:batch_id>/sync")
def sync_batch(batch_id: int):
    def go(session):
        client = _paypal_client()
        if client is None:
            return json_response({"error": "PayPal isn't connected yet."}, 400)
        return json_response(batches.batch_dict(batches.sync(session, batch_id, client)))
    return _run("sync batch", go)


@payout_batches_bp.post("/api/payouts/admin/items/<int:item_id>/remove")
def remove_item(item_id: int):
    def go(session):
        batches.remove_item(session, item_id)
        return json_response({"ok": True})
    return _run("remove item", go)


@payout_batches_bp.post("/api/payouts/admin/items/<int:item_id>/mark-paid")
def mark_item_paid(item_id: int):
    def go(session):
        batches.mark_manual_paid(session, item_id)
        return json_response({"ok": True})
    return _run("mark item paid", go)
