"""Batch payouts end to end with a fake PayPal (no network, no money)."""
from __future__ import annotations

import pytest

from campaign_manager import db as _db
from campaign_manager.blueprints import payouts as payouts_bp_module
from campaign_manager.models import Campaign, Creator, CreatorProfile, PayoutItem
from campaign_manager.services.paypal_payouts import PayPalConfig, PayPalError, PayPalPayouts, _item_payload

ADMIN_KEY = "test-payout-admin-key-0123456789"
ADMIN = {"X-Payout-Admin-Key": ADMIN_KEY}


class FakePayPal:
    def __init__(self, env="live"):
        self.env = env
        self.header = None
        self.created = []
        self.statuses = {}
        self.fail_create = None
        self._sent_items = {}  # item.id -> PayoutItem, for receipt fields

    def create_payout(self, sender_batch_id, items):
        if self.fail_create:
            raise self.fail_create
        self.created.append((sender_batch_id, [(i.username, i.method, i.amount) for i in items]))
        self._sent_items = {i.id: i for i in items}
        return {"batch_header": self.header or {"payout_batch_id": "PB-1", "batch_status": "PENDING"}}

    def _receipt_fields(self, item_id):
        """Return the receipt fields matching what was dispatched, for validation."""
        item = self._sent_items.get(item_id)
        if item is None:
            return {}
        return {
            "receiver": item.destination,
            "recipient_wallet": "Venmo" if item.method == "venmo" else "PayPal",
            "amount": {"value": f"{item.amount:.2f}", "currency": item.currency or "USD"},
        }

    def get_batch(self, _paypal_batch_id):
        return {"items": [
            {"transaction_status": st, "payout_item_id": f"PI-{iid}",
             "payout_item": {"sender_item_id": f"item-{iid}", **self._receipt_fields(iid)},
             **({"errors": {"message": "Receiver is ineligible"}} if st == "FAILED" else {})}
            for iid, st in self.statuses.items()
        ]}


@pytest.fixture(autouse=True)
def _reset_limiters():
    payouts_bp_module.admin_fail_limiter.reset()


@pytest.fixture
def paypal(app):
    fake = FakePayPal()
    app.config.update(PAYOUT_ADMIN_KEY=ADMIN_KEY, PAYPAL_CLIENT_FACTORY=lambda: fake)
    return fake


@pytest.fixture
def seeded(db):
    with db.get_session() as s:
        live = Campaign(slug="live", title="Live Song", completion_status="none")
        s.add(live)
        s.flush()
        s.add_all([
            Creator(campaign_id=live.id, username="pp", posts_owed=2, posts_done=2, total_rate=100),
            Creator(campaign_id=live.id, username="vm", posts_owed=1, posts_done=1, total_rate=50.5),
            Creator(campaign_id=live.id, username="ca", posts_owed=1, posts_done=1, total_rate=75),
            Creator(campaign_id=live.id, username="nodetails", posts_owed=1, posts_done=1, total_rate=60),
        ])
        s.add_all([
            CreatorProfile(username="pp", payout_method="paypal", payout_destination="pp@gmail.com",
                           payout_confirmed_by_creator=True),
            CreatorProfile(username="vm", payout_method="venmo", payout_destination="@vm-user",
                           payout_confirmed_by_creator=True),
            CreatorProfile(username="ca", payout_method="cashapp", payout_destination="$ca",
                           payout_confirmed_by_creator=True),
        ])
        s.commit()


def _post(client, path, **body):
    return client.post(path, headers=ADMIN, json=body)


def _paid(username):
    with _db.get_session() as s:
        row = s.query(Creator).filter_by(username=username).one()
        return row.paid, row.payment_date


def test_full_batch_flow(client, paypal, seeded):
    draft = _post(client, "/api/payouts/admin/batches").json
    assert draft["status"] == "draft"
    lanes = {i["username"]: i["lane"] for i in draft["items"]}
    assert lanes == {"pp": "api", "vm": "api", "ca": "manual"}  # no details -> not included
    assert draft["totals"] == {"api": 150.5, "manual": 75.0, "all": 225.5}

    # Queue no longer offers them; a second "create" returns the same draft.
    queue = client.get("/api/payouts/admin/queue", headers=ADMIN).json
    assert [r["username"] for r in queue["ready"]] == ["nodetails"]
    assert _post(client, "/api/payouts/admin/batches").json["id"] == draft["id"]

    bid = draft["id"]
    assert _post(client, f"/api/payouts/admin/batches/{bid}/approve", confirm_total="150").status_code == 400
    assert paypal.created == []

    sent = _post(client, f"/api/payouts/admin/batches/{bid}/approve", confirm_total="150.50").json
    assert sent["status"] == "sent" and sent["paypal_env"] == "live"
    assert paypal.created == [(paypal.created[0][0], [("pp", "paypal", 100.0), ("vm", "venmo", 50.5)])]
    assert _paid("pp") == ("no", "")  # not paid until PayPal says so

    ids = {i["username"]: i["id"] for i in sent["items"]}
    paypal.statuses = {ids["pp"]: "SUCCESS", ids["vm"]: "FAILED"}
    synced = _post(client, f"/api/payouts/admin/batches/{bid}/sync").json
    by_user = {i["username"]: i for i in synced["items"]}
    assert by_user["pp"]["status"] == "succeeded"
    assert by_user["vm"]["status"] == "failed" and "ineligible" in by_user["vm"]["error"]
    assert _paid("pp")[0] == "yes"
    assert _paid("vm")[0] == "no"

    # Failed Venmo item goes back to the queue for the next batch.
    queue = client.get("/api/payouts/admin/queue", headers=ADMIN).json
    assert sorted(r["username"] for r in queue["ready"]) == ["nodetails", "vm"]

    # Cash App paid by hand, then the batch closes.
    assert _post(client, f"/api/payouts/admin/items/{ids['ca']}/mark-paid").status_code == 200
    assert _paid("ca")[0] == "yes"
    final = client.get("/api/payouts/admin/batches", headers=ADMIN).json
    assert final["batches"][0]["status"] == "closed"
    assert final["paypal"] == {"connected": True, "env": "live"}


def test_destination_change_after_draft_blocks_send(client, paypal, seeded):
    bid = _post(client, "/api/payouts/admin/batches").json["id"]
    with _db.get_session() as s:
        s.get(CreatorProfile, "pp").payout_destination = "attacker@gmail.com"
        s.commit()
    resp = _post(client, f"/api/payouts/admin/batches/{bid}/approve", confirm_total="150.50")
    assert resp.status_code == 400 and "changed" in resp.json["error"]
    assert paypal.created == []


def test_paypal_error_is_retryable_with_same_batch_id(client, paypal, seeded):
    bid = _post(client, "/api/payouts/admin/batches").json["id"]
    paypal.fail_create = PayPalError("Couldn't reach PayPal (Timeout).")
    resp = _post(client, f"/api/payouts/admin/batches/{bid}/approve", confirm_total="150.50")
    assert resp.status_code == 400 and "retry safely" in resp.json["error"]
    blocked = _post(client, "/api/payouts/admin/batches")  # can't add while a send is in flight
    assert blocked.status_code == 400 and "being sent" in blocked.json["error"]

    paypal.fail_create = None
    assert _post(client, f"/api/payouts/admin/batches/{bid}/approve", confirm_total="150.50").json["status"] == "sent"


def test_remove_item_and_cancel(client, paypal, seeded):
    draft = _post(client, "/api/payouts/admin/batches").json
    ca = next(i for i in draft["items"] if i["username"] == "ca")
    assert _post(client, f"/api/payouts/admin/items/{ca['id']}/remove").status_code == 200
    assert _post(client, f"/api/payouts/admin/items/{ca['id']}/mark-paid").status_code == 400
    assert _post(client, f"/api/payouts/admin/batches/{draft['id']}/cancel").status_code == 200
    queue = client.get("/api/payouts/admin/queue", headers=ADMIN).json
    assert sorted(r["username"] for r in queue["ready"]) == ["ca", "nodetails", "pp", "vm"]


def test_manual_item_cannot_be_marked_paid_before_approval(client, paypal, seeded):
    draft = _post(client, "/api/payouts/admin/batches").json
    ca = next(i for i in draft["items"] if i["username"] == "ca")
    assert _post(client, f"/api/payouts/admin/items/{ca['id']}/mark-paid").status_code == 400


def test_batches_require_admin_key(client, paypal):
    assert client.post("/api/payouts/admin/batches").status_code == 401


def test_without_paypal_api_items_cannot_send(app, client, seeded):
    app.config.update(PAYOUT_ADMIN_KEY=ADMIN_KEY, PAYPAL_CLIENT_FACTORY=lambda: None)
    bid = _post(client, "/api/payouts/admin/batches").json["id"]
    resp = _post(client, f"/api/payouts/admin/batches/{bid}/approve", confirm_total="150.50")
    assert resp.status_code == 400 and "isn't connected" in resp.json["error"]


def test_paypal_payload_shapes():
    paypal_item = PayoutItem(id=7, amount=100, currency="USD", method="paypal",
                             destination="a@b.com", campaign_title="Song")
    venmo_item = PayoutItem(id=8, amount=50.5, currency="USD", method="venmo",
                            destination="@vm-user", campaign_title="Song")
    assert _item_payload(paypal_item) == {
        "amount": {"value": "100.00", "currency": "USD"}, "receiver": "a@b.com",
        "sender_item_id": "item-7", "note": "Rising Tides — Song", "recipient_type": "EMAIL",
    }
    v = _item_payload(venmo_item)
    assert (v["recipient_type"], v["recipient_wallet"], v["receiver"]) == ("USER_HANDLE", "Venmo", "@vm-user")


def test_paypal_config_defaults_to_sandbox(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    monkeypatch.delenv("PAYPAL_ENV", raising=False)
    cfg = PayPalConfig.from_env()
    assert cfg.env == "sandbox" and "sandbox" in cfg.base_url
    monkeypatch.setenv("PAYPAL_ENV", "production")
    with pytest.raises(PayPalError):
        PayPalConfig.from_env()


def test_paypal_errors_never_include_secret(monkeypatch):
    import requests

    class Boom:
        def post(self, *a, **k):
            raise requests.ConnectionError("https://id:topsecret@api-m.sandbox.paypal.com failed")

    client = PayPalPayouts(PayPalConfig("id", "topsecret", "sandbox"), session=Boom())
    with pytest.raises(PayPalError) as exc:
        client.get_batch("PB-1")
    assert "topsecret" not in str(exc.value)


def _approve(client, bid, total="150.50"):
    return _post(client, f"/api/payouts/admin/batches/{bid}/approve", confirm_total=total)


def _ready(client):
    return sorted(r["username"] for r in client.get("/api/payouts/admin/queue", headers=ADMIN).json["ready"])


def test_sandbox_success_never_marks_real_bookings_paid(app, client, seeded):
    fake = FakePayPal(env="sandbox")
    app.config.update(PAYOUT_ADMIN_KEY=ADMIN_KEY, PAYPAL_CLIENT_FACTORY=lambda: fake)
    draft = _post(client, "/api/payouts/admin/batches").json
    sent = _approve(client, draft["id"]).json
    fake.statuses = {i["id"]: "SUCCESS" for i in sent["items"] if i["lane"] == "api"}
    synced = _post(client, f"/api/payouts/admin/batches/{draft['id']}/sync").json
    assert {i["status"] for i in synced["items"] if i["lane"] == "api"} == {"sandbox_ok"}
    assert _paid("pp")[0] == "no"
    assert "pp" in _ready(client)  # released back to the queue


def test_sync_refuses_env_mismatch(app, client, paypal, seeded):
    bid = _post(client, "/api/payouts/admin/batches").json["id"]
    _approve(client, bid)
    paypal.env = "sandbox"
    resp = _post(client, f"/api/payouts/admin/batches/{bid}/sync")
    assert resp.status_code == 400 and "live" in resp.json["error"]


def test_rate_change_after_draft_blocks_send(client, paypal, seeded):
    bid = _post(client, "/api/payouts/admin/batches").json["id"]
    with _db.get_session() as s:
        s.query(Creator).filter_by(username="pp").one().total_rate = 5000
        s.commit()
    resp = _approve(client, bid)
    assert resp.status_code == 400 and "rate changed" in resp.json["error"]
    assert paypal.created == []


def test_marked_paid_after_draft_blocks_send(client, paypal, seeded):
    bid = _post(client, "/api/payouts/admin/batches").json["id"]
    with _db.get_session() as s:
        s.query(Creator).filter_by(username="vm").one().paid = "yes"
        s.commit()
    resp = _approve(client, bid)
    assert resp.status_code == 400 and "already marked paid" in resp.json["error"]
    assert paypal.created == []


def test_refunded_goes_to_review_not_requeue(client, paypal, seeded):
    draft = _post(client, "/api/payouts/admin/batches").json
    sent = _approve(client, draft["id"]).json
    pp = next(i["id"] for i in sent["items"] if i["username"] == "pp")
    paypal.statuses = {pp: "REFUNDED"}
    synced = _post(client, f"/api/payouts/admin/batches/{draft['id']}/sync").json
    assert next(i for i in synced["items"] if i["id"] == pp)["status"] == "review"
    assert "pp" not in _ready(client)


def test_open_item_unique_index_blocks_duplicates(db, seeded):
    from sqlalchemy.exc import IntegrityError
    from campaign_manager.models import PayoutBatch
    with db.get_session() as s:
        cid = s.query(Creator).filter_by(username="pp").one().campaign_id
        for n in (1, 2):
            b = PayoutBatch(status="draft", sender_batch_id=f"dup-{n}")
            s.add(b)
            s.flush()
            s.add(PayoutItem(batch_id=b.id, campaign_id=cid, username="pp", platform="tiktok", amount=100,
                             method="paypal", destination="pp@gmail.com", lane="api", status="queued"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_zero_rate_bookings_are_left_out(client, paypal, seeded):
    with _db.get_session() as s:
        s.query(Creator).filter_by(username="vm").one().total_rate = 0
        s.commit()
    draft = _post(client, "/api/payouts/admin/batches").json
    assert "vm" not in [i["username"] for i in draft["items"]]


def test_missing_paypal_batch_id_fails_loudly(client, paypal, seeded):
    bid = _post(client, "/api/payouts/admin/batches").json["id"]
    paypal.header = {"batch_status": "DENIED"}
    resp = _approve(client, bid)
    assert resp.status_code == 400 and "didn't accept" in resp.json["error"]


def test_rename_blocked_while_in_batch(client, paypal, seeded):
    _post(client, "/api/payouts/admin/batches")
    resp = client.post("/api/campaign/live/creator/pp/edit",
                       json={"new_username": "pp2", "posts_owed": 2, "total_rate": 100})
    assert resp.status_code == 409 and "payout batch" in resp.json["error"]


def test_pay_button_adds_one_booking_and_queue_shows_it(client, paypal, seeded):
    body = {"slug": "live", "username": "pp", "platform": "tiktok"}
    batch = _post(client, "/api/payouts/admin/batches/add-booking", **body).json
    assert [i["username"] for i in batch["items"]] == ["pp"]

    queue = client.get("/api/payouts/admin/queue", headers=ADMIN).json
    row = queue["in_batch"][0]
    assert row["username"] == "pp" and row["payment"]["batch_id"] == batch["id"]
    assert "pp" not in _ready(client)

    again = _post(client, "/api/payouts/admin/batches/add-booking", **body)
    assert again.status_code == 400 and "already in a payment" in again.json["error"]

    vm = _post(client, "/api/payouts/admin/batches/add-booking", slug="live", username="vm", platform="tiktok").json
    assert vm["id"] == batch["id"] and len(vm["items"]) == 2

    nod = _post(client, "/api/payouts/admin/batches/add-booking", slug="live", username="nodetails", platform="tiktok")
    assert nod.status_code == 400 and "payment info" in nod.json["error"]


def test_pay_everyone_adds_to_existing_draft(client, paypal, seeded):
    first = _post(client, "/api/payouts/admin/batches/add-booking", slug="live", username="pp", platform="tiktok").json
    everyone = _post(client, "/api/payouts/admin/batches").json
    assert everyone["id"] == first["id"]
    assert sorted(i["username"] for i in everyone["items"]) == ["ca", "pp", "vm"]


# ── Bug 1a: no double dispatch once PayPal accepted the batch ──────────────────

def test_no_double_dispatch_after_successful_post(client, paypal, seeded):
    """Once paypal_batch_id is set, approve must refuse another POST."""
    draft = _post(client, "/api/payouts/admin/batches").json
    bid = draft["id"]
    sent = _approve(client, bid).json
    assert sent["status"] == "sent"
    assert len(paypal.created) == 1

    resp = _approve(client, bid)
    assert resp.status_code == 400
    assert "dispatched" in resp.json["error"]
    # PayPal was NOT called a second time.
    assert len(paypal.created) == 1


# ── Bug 1b: env frozen after first (failed) dispatch ──────────────────────────

def test_env_frozen_after_failed_send_blocks_switch(app, client, seeded):
    """After a network failure mid-send, switching env must be refused."""
    fake_live = FakePayPal(env="live")
    app.config.update(PAYOUT_ADMIN_KEY=ADMIN_KEY, PAYPAL_CLIENT_FACTORY=lambda: fake_live)
    draft = _post(client, "/api/payouts/admin/batches").json
    bid = draft["id"]

    # First attempt fails: batch is now "sending", paypal_env="live", no batch_id.
    fake_live.fail_create = PayPalError("network error")
    _approve(client, bid)
    assert fake_live.created == []

    # Switch the factory to sandbox while the live batch is still in-flight.
    fake_sandbox = FakePayPal(env="sandbox")
    app.config.update(PAYPAL_CLIENT_FACTORY=lambda: fake_sandbox)
    resp = _approve(client, bid)
    assert resp.status_code == 400
    assert "live" in resp.json["error"]
    # Sandbox was never called.
    assert fake_sandbox.created == []

    # Retrying with the original live client succeeds.
    fake_live.fail_create = None
    app.config.update(PAYPAL_CLIENT_FACTORY=lambda: fake_live)
    result = _approve(client, bid)
    assert result.json["status"] == "sent"
    assert len(fake_live.created) == 1


# ── Bug 2: REVERSED after SUCCESS moves item to review ────────────────────────

def test_reversed_after_success_moves_to_review(client, paypal, seeded):
    """A REVERSED status arriving after SUCCESS holds for review; booking stays paid."""
    draft = _post(client, "/api/payouts/admin/batches").json
    bid = draft["id"]
    sent = _approve(client, bid).json
    pp = next(i["id"] for i in sent["items"] if i["username"] == "pp")

    # First sync: PayPal says SUCCESS.
    paypal.statuses = {pp: "SUCCESS"}
    synced1 = _post(client, f"/api/payouts/admin/batches/{bid}/sync").json
    assert next(i for i in synced1["items"] if i["id"] == pp)["status"] == "succeeded"
    assert _paid("pp")[0] == "yes"

    # Second sync: PayPal now says REVERSED.
    paypal.statuses = {pp: "REVERSED"}
    synced2 = _post(client, f"/api/payouts/admin/batches/{bid}/sync").json
    item = next(i for i in synced2["items"] if i["id"] == pp)
    assert item["status"] == "review"
    assert "REVERSED" in item["error"]
    # Historical paid evidence is preserved — booking stays paid.
    assert _paid("pp")[0] == "yes"
    # Not requeued (review is an open status).
    assert "pp" not in _ready(client)


# ── Bug 3: alias ambiguity holds settlement rather than updating multiple rows ─

def test_alias_dedup_holds_on_multiple_matches(db, seeded):
    """If both 'alice' and '@alice' exist on the same campaign/platform, settlement
    sets an error rather than marking both rows paid."""
    from campaign_manager.models import PayoutBatch
    from campaign_manager.services.payout_batches import _mark_booking_paid
    from datetime import datetime

    with db.get_session() as s:
        cid = s.query(Creator).filter_by(username="pp").one().campaign_id
        # Both normalized ('alice') and @-prefixed ('@alice') rows exist.
        s.add(Creator(campaign_id=cid, username="alice", platform="tiktok",
                      posts_owed=1, posts_done=1, total_rate=100, paid="no"))
        s.add(Creator(campaign_id=cid, username="@alice", platform="tiktok",
                      posts_owed=1, posts_done=1, total_rate=100, paid="no"))
        batch = PayoutBatch(status="sent", sender_batch_id="alias-test-batch",
                            paypal_env="live")
        s.add(batch)
        s.flush()
        item = PayoutItem(batch_id=batch.id, campaign_id=cid, username="alice",
                          platform="tiktok", amount=100, currency="USD",
                          method="paypal", destination="alice@example.com",
                          lane="api", status="pending")
        s.add(item)
        s.commit()
        item_id = item.id

    with db.get_session() as s:
        item = s.get(PayoutItem, item_id)
        _mark_booking_paid(s, item, datetime.now())
        # Neither row should be marked paid; item gets an error note.
        assert item.error
        assert "multiple" in item.error
        alices = s.query(Creator).filter(
            Creator.campaign_id == item.campaign_id,
            Creator.platform == "tiktok",
        ).filter(Creator.username.in_(["alice", "@alice"])).all()
        assert all(c.paid != "yes" for c in alices)


# ── Bug 4: rate edit after approval holds settlement for review ────────────────

def test_rate_change_after_send_holds_for_review(client, paypal, seeded):
    """If the booking rate is edited after the batch is approved, sync holds for
    operator review rather than marking a mismatched amount paid."""
    draft = _post(client, "/api/payouts/admin/batches").json
    bid = draft["id"]
    _approve(client, bid)

    # Edit the rate after the payment was sent (item still pending).
    with _db.get_session() as s:
        s.query(Creator).filter_by(username="pp").one().total_rate = 150
        s.commit()

    pp = next(i["id"] for i in _post(client, "/api/payouts/admin/batches").json.get("items", [])
              or client.get("/api/payouts/admin/batches", headers=ADMIN).json["batches"][0]["items"]
              if i["username"] == "pp")
    # Re-fetch pp item id from the sent batch.
    batch_data = client.get("/api/payouts/admin/batches", headers=ADMIN).json["batches"][0]
    pp_id = next(i["id"] for i in batch_data["items"] if i["username"] == "pp")

    paypal.statuses = {pp_id: "SUCCESS"}
    synced = _post(client, f"/api/payouts/admin/batches/{bid}/sync").json
    item = next(i for i in synced["items"] if i["id"] == pp_id)
    assert item["status"] == "review"
    assert "150" in item["error"]
    assert _paid("pp")[0] == "no"
    # Not requeued.
    assert "pp" not in _ready(client)


# ── Receipt mismatch guard: wrong destination/amount/currency never settles ───

def test_mismatched_receipt_no_settlement(client, paypal, seeded):
    """A PayPal receipt with a tampered destination is held for review, not settled."""
    draft = _post(client, "/api/payouts/admin/batches").json
    bid = draft["id"]
    sent = _approve(client, bid).json
    pp_id = next(i["id"] for i in sent["items"] if i["username"] == "pp")

    # Tamper with the receipt's receiver address before the sync lookup.
    original_receipt = paypal._receipt_fields

    def tampered_receipt(item_id):
        fields = original_receipt(item_id)
        if fields:
            fields = {**fields, "receiver": "attacker@evil.com"}
        return fields

    paypal._receipt_fields = tampered_receipt

    paypal.statuses = {pp_id: "SUCCESS"}
    synced = _post(client, f"/api/payouts/admin/batches/{bid}/sync").json
    item = next(i for i in synced["items"] if i["id"] == pp_id)
    assert item["status"] == "review"
    assert "mismatch" in item["error"]
    assert _paid("pp")[0] == "no"
