"""Payment attempts are never replayed; settlement requires the original receipt."""
from copy import deepcopy

import pytest

from campaign_manager.models import Campaign, Creator, CreatorProfile
from campaign_manager.services.paypal_payouts import PayPalError, _item_payload

ADMIN_KEY = "synthetic-payout-review-key-0000000000"
ADMIN = {"X-Payout-Admin-Key": ADMIN_KEY}


class ReceiptPayPal:
    env = "live"

    def __init__(self):
        self.posts = []
        self.gets = []
        self.lost_response = False
        self.receipt = None

    def create_payout(self, sender_batch_id, items):
        self.posts.append(sender_batch_id)
        self.receipt = {
            "batch_header": {"payout_batch_id": "PB-ORIGINAL", "batch_status": "SUCCESS",
                             "sender_batch_header": {"sender_batch_id": sender_batch_id}},
            "items": [{"payout_item_id": f"PI-{item.id}", "transaction_status": "SUCCESS",
                       "payout_item": _item_payload(item)} for item in items],
        }
        if self.lost_response:
            raise PayPalError("Synthetic accepted POST lost its response")
        return {"batch_header": deepcopy(self.receipt["batch_header"])}

    def get_batch(self, batch_id):
        self.gets.append(batch_id)
        return deepcopy(self.receipt)


@pytest.fixture
def provider(app, db):
    fake = ReceiptPayPal()
    app.config.update(PAYOUT_ADMIN_KEY=ADMIN_KEY, PAYPAL_CLIENT_FACTORY=lambda: fake)
    with db.get_session() as session:
        campaign = Campaign(slug="payout-review", title="Payout review")
        session.add(campaign)
        session.flush()
        session.add(Creator(campaign_id=campaign.id, username="alice", posts_owed=1,
                            posts_done=1, total_rate=100))
        session.add(CreatorProfile(username="alice", payout_method="paypal",
                                   payout_destination="alice@example.test", payout_confirmed_by_creator=True))
        session.commit()
    return fake


def _post(client, suffix, **body):
    return client.post(f"/api/payouts/admin/{suffix}", headers=ADMIN, json=body)


def _draft(client):
    response = _post(client, "batches")
    assert response.status_code == 200
    return response.json


def _approve(client, bid):
    return _post(client, f"batches/{bid}/approve", confirm_total="100")


def _booking(db):
    with db.get_session() as session:
        row = session.query(Creator).filter_by(username="alice").one()
        return row.paid, row.total_rate, row.payment_date


@pytest.mark.parametrize("next_env", ["live", "sandbox"])
def test_unknown_attempt_never_replays_even_with_environment_or_account_drift(client, provider, next_env):
    draft = _draft(client)
    provider.lost_response = True
    first = _approve(client, draft["id"])
    assert first.status_code == 400
    assert "retry safely" not in first.json["error"]
    provider.lost_response = False
    provider.env = next_env  # a new account in the same env must be held too
    second = _approve(client, draft["id"])
    assert second.status_code == 400
    assert len(provider.posts) == 1
    stored = client.get("/api/payouts/admin/batches", headers=ADMIN).json["batches"][0]
    assert stored["status"] == "sending"
    assert stored["paypal_env"] == "live"


def test_unknown_attempt_reconciles_original_receipt_using_only_get(client, provider, db):
    draft = _draft(client)
    provider.lost_response = True
    assert _approve(client, draft["id"]).status_code == 400
    response = _post(client, f"batches/{draft['id']}/reconcile", paypal_batch_id="PB-ORIGINAL")
    assert response.status_code == 200, response.json
    assert len(provider.posts) == 1
    assert provider.gets == ["PB-ORIGINAL"]
    assert response.json["paypal_batch_id"] == "PB-ORIGINAL"
    assert response.json["items"][0]["status"] == "succeeded"
    assert _booking(db)[0] == "yes"


def _corrupt(receipt, field):
    if field == "batch_id": receipt["batch_header"]["payout_batch_id"] = "PB-OTHER"
    elif field == "sender_batch_id": receipt["batch_header"]["sender_batch_header"]["sender_batch_id"] = "other-attempt"
    elif field == "missing": receipt["items"] = []
    elif field == "duplicate": receipt["items"] *= 2
    elif field == "extra":
        extra = deepcopy(receipt["items"][0]); extra["payout_item"]["sender_item_id"] = "item-999"; receipt["items"].append(extra)
    elif field == "amount": receipt["items"][0]["payout_item"]["amount"]["value"] = "999.00"
    elif field == "currency": receipt["items"][0]["payout_item"]["amount"]["currency"] = "EUR"
    elif field == "receiver": receipt["items"][0]["payout_item"]["receiver"] = "other@example.test"
    elif field == "wallet": receipt["items"][0]["payout_item"]["recipient_wallet"] = "VENMO"
    elif field == "recipient_type": receipt["items"][0]["payout_item"]["recipient_type"] = "USER_HANDLE"
    elif field == "sender_item_id": receipt["items"][0]["payout_item"]["sender_item_id"] = "item-999"
    elif field == "provider_item_id": receipt["items"][0]["payout_item_id"] = ""
    elif field == "unknown_status": receipt["items"][0]["transaction_status"] = "MAYBE_PAID"
    elif field == "status_shape": receipt["items"][0]["transaction_status"] = ["SUCCESS"]
    elif field == "header_status_shape": receipt["batch_header"]["batch_status"] = ["SUCCESS"]
    elif field == "unknown_header_status": receipt["batch_header"]["batch_status"] = "NEW"
    elif field == "denied_success": receipt["batch_header"]["batch_status"] = "DENIED"
    elif field == "canceled_success": receipt["batch_header"]["batch_status"] = "CANCELED"
    elif field == "item_count": receipt["total_items"] = len(receipt["items"]) + 1
    elif field == "wrong_shape": receipt["items"][0] = "not-an-item"


@pytest.mark.parametrize("field", ["batch_id", "sender_batch_id", "missing", "duplicate", "extra", "amount",
                                  "currency", "receiver", "wallet", "recipient_type", "sender_item_id",
                                  "provider_item_id", "unknown_status", "status_shape", "header_status_shape", "unknown_header_status",
                                  "denied_success", "canceled_success", "item_count", "wrong_shape"])
def test_sync_rejects_incomplete_or_mismatched_receipts_atomically(client, provider, db, field):
    draft = _draft(client)
    assert _approve(client, draft["id"]).status_code == 200
    _corrupt(provider.receipt, field)
    response = _post(client, f"batches/{draft['id']}/sync")
    assert response.status_code == 400, response.json
    assert _booking(db)[0] == "no"
    stored = client.get("/api/payouts/admin/batches", headers=ADMIN).json["batches"][0]
    assert stored["items"][0]["status"] == "pending"
    assert stored["items"][0]["provider_status"] == ""


def test_reconciliation_refuses_wrong_env_before_reading_provider(client, provider):
    draft = _draft(client)
    provider.lost_response = True
    _approve(client, draft["id"])
    provider.env = "sandbox"
    response = _post(client, f"batches/{draft['id']}/reconcile", paypal_batch_id="PB-ORIGINAL")
    assert response.status_code == 400
    assert provider.gets == []


@pytest.mark.parametrize("value", ["../other", "PB-1?account=other", "https://other.test/batch", "x" * 65, 123, ""])
def test_reconcile_validates_provider_id_before_get(client, provider, value):
    draft = _draft(client)
    provider.lost_response = True
    _approve(client, draft["id"])
    response = _post(client, f"batches/{draft['id']}/reconcile", paypal_batch_id=value)
    assert response.status_code == 400
    assert provider.gets == []


@pytest.mark.parametrize("later_status", ["REVERSED", "REFUNDED"])
def test_successful_payment_later_reversal_is_held_for_review_without_repay(client, provider, db, later_status):
    draft = _draft(client)
    _approve(client, draft["id"])
    first = _post(client, f"batches/{draft['id']}/sync").json
    paid_at = first["items"][0]["paid_at"]
    assert first["status"] == "closed"
    provider.receipt["items"][0]["transaction_status"] = later_status
    response = _post(client, f"batches/{draft['id']}/sync")
    assert response.status_code == 200
    item = response.json["items"][0]
    assert item["status"] == "review"
    assert item["provider_status"] == later_status
    assert item["paid_at"] == paid_at
    assert _booking(db)[0] == "yes"
    assert _post(client, "batches").status_code == 400
    assert len(provider.posts) == 1


def test_changed_obligation_after_send_does_not_become_paid(client, provider, db):
    draft = _draft(client)
    _approve(client, draft["id"])
    with db.get_session() as session:
        session.query(Creator).one().total_rate = 150
        session.commit()
    response = _post(client, f"batches/{draft['id']}/sync")
    assert response.status_code == 200
    assert response.json["items"][0]["status"] == "review"
    assert response.json["items"][0]["paid_at"]
    assert _booking(db)[0] == "no"
    assert _post(client, "batches").status_code == 400


def test_duplicate_canonical_bookings_are_blocked_without_first_row_choice(client, provider, db):
    with db.get_session() as session:
        original = session.query(Creator).one()
        session.add(Creator(campaign_id=original.campaign_id, username="@ALICE", total_rate=200,
                            posts_owed=1, posts_done=1))
        session.commit()
    queue = client.get("/api/payouts/admin/queue", headers=ADMIN).json
    assert queue["ready"] == []
    assert all(row["booking_issue"] == "ambiguous" for row in queue["not_ready"])
    assert len({row["booking_id"] for row in queue["not_ready"]}) == 2
    response = _post(client, "batches/add-booking", slug="payout-review", username="alice", platform="tiktok")
    assert response.status_code == 400
    assert provider.posts == []


def test_new_alias_after_send_never_marks_two_booking_obligations_paid(client, provider, db):
    draft = _draft(client)
    _approve(client, draft["id"])
    with db.get_session() as session:
        original = session.query(Creator).one()
        session.add(Creator(campaign_id=original.campaign_id, username="@ALICE", total_rate=100,
                            posts_owed=1, posts_done=1))
        session.commit()
    response = _post(client, f"batches/{draft['id']}/sync")
    assert response.status_code == 200
    assert response.json["items"][0]["status"] == "review"
    with db.get_session() as session:
        assert {row.paid for row in session.query(Creator)} == {"no"}


def test_later_item_mismatch_cannot_partially_settle_earlier_items(client, provider, db):
    with db.get_session() as session:
        cid = session.query(Creator).one().campaign_id
        session.add(Creator(campaign_id=cid, username="bob", posts_owed=1, posts_done=1, total_rate=100))
        session.add(CreatorProfile(username="bob", payout_method="paypal",
                                   payout_destination="bob@example.test", payout_confirmed_by_creator=True))
        session.commit()
    draft = _draft(client)
    assert _post(client, f"batches/{draft['id']}/approve", confirm_total="200").status_code == 200
    provider.receipt["items"][1]["payout_item"]["amount"]["value"] = "999.00"
    assert _post(client, f"batches/{draft['id']}/sync").status_code == 400
    with db.get_session() as session:
        assert {row.paid for row in session.query(Creator)} == {"no"}


def test_existing_paid_history_is_never_overwritten_by_later_settlement(client, provider, db):
    draft = _draft(client)
    _approve(client, draft["id"])
    with db.get_session() as session:
        booking = session.query(Creator).one()
        booking.paid, booking.payment_date = "yes", "2026-01-01"
        session.commit()
    response = _post(client, f"batches/{draft['id']}/sync")
    assert response.status_code == 200
    assert response.json["items"][0]["status"] == "review"
    assert _booking(db) == ("yes", 100, "2026-01-01")
