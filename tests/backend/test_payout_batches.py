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
    env = "sandbox"

    def __init__(self):
        self.created = []
        self.statuses = {}
        self.fail_create = None

    def create_payout(self, sender_batch_id, items):
        if self.fail_create:
            raise self.fail_create
        self.created.append((sender_batch_id, [(i.username, i.method, i.amount) for i in items]))
        return {"batch_header": {"payout_batch_id": "PB-1", "batch_status": "PENDING"}}

    def get_batch(self, _paypal_batch_id):
        return {"items": [
            {"transaction_status": st, "payout_item_id": f"PI-{iid}",
             "payout_item": {"sender_item_id": f"item-{iid}"},
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
    assert sent["status"] == "sent" and sent["paypal_env"] == "sandbox"
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
    assert final["paypal"] == {"connected": True, "env": "sandbox"}


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
    assert _post(client, "/api/payouts/admin/batches").json["id"] == bid  # still the open batch

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
