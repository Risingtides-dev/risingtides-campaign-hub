"""Ready-for-payment rules and the admin payment queue."""
from __future__ import annotations

import pytest

from campaign_manager import db as _db
from campaign_manager.blueprints import payouts as payouts_bp_module
from campaign_manager.models import Campaign, Creator, CreatorProfile

ADMIN_KEY = "test-payout-admin-key-0123456789"
ADMIN = {"X-Payout-Admin-Key": ADMIN_KEY}


@pytest.fixture(autouse=True)
def _reset_limiters():
    payouts_bp_module.admin_fail_limiter.reset()
    yield


@pytest.fixture
def admin_app(app):
    app.config.update(PAYOUT_ADMIN_KEY=ADMIN_KEY)
    return app


def _campaign(s, slug, completed=False):
    c = Campaign(slug=slug, title=slug.title(), completion_status="completed" if completed else "none")
    s.add(c)
    s.flush()
    return c


@pytest.fixture
def seeded(db):
    with db.get_session() as s:
        # "vet" fully delivered 6 past campaigns -> trusted automatically.
        for i in range(6):
            past = _campaign(s, f"past{i}", completed=True)
            s.add(Creator(campaign_id=past.id, username="vet", posts_owed=2, posts_done=2, paid="yes"))
        # A stale unpaid row on a finished campaign must never be queued.
        old = _campaign(s, "old", completed=True)
        s.add(Creator(campaign_id=old.id, username="newbie", posts_owed=1, posts_done=1, total_rate=40))

        live = _campaign(s, "live")
        s.add_all([
            Creator(campaign_id=live.id, username="@NewBie", posts_owed=3, posts_done=3, total_rate=150),
            Creator(campaign_id=live.id, username="partial", posts_owed=5, posts_done=3, total_rate=200),
            Creator(campaign_id=live.id, username="vet", posts_owed=4, posts_done=0, total_rate=300),
            Creator(campaign_id=live.id, username="done", posts_owed=2, posts_done=2, total_rate=90, paid="yes"),
            Creator(campaign_id=live.id, username="gone", posts_owed=2, posts_done=2, total_rate=70, status="removed"),
        ])
        s.add_all([
            CreatorProfile(username="newbie", payout_method="paypal", payout_destination="n@gmail.com",
                           payout_confirmed_by_creator=True),
            CreatorProfile(username="vet", payout_method="cashapp", payout_destination="$vet",
                           payout_confirmed_by_creator=True, payout_change_flagged=True),
            CreatorProfile(username="partial"),
        ])
        s.commit()


def _queue(client):
    resp = client.get("/api/payouts/admin/queue", headers=ADMIN)
    assert resp.status_code == 200, resp.json
    return resp.json


def _names(rows):
    return [r["username"] for r in rows]


def test_queue_applies_rules(admin_app, client, seeded):
    q = _queue(client)
    assert _names(q["ready"]) == ["newbie"]
    assert q["ready"][0]["reason"] == "posts_complete"
    assert q["ready"][0]["destination_issue"] == ""
    assert _names(q["awaiting_confirmation"]) == ["vet"]
    assert q["awaiting_confirmation"][0]["trusted"] is True
    assert q["awaiting_confirmation"][0]["delivered_campaigns"] == 6
    assert _names(q["not_ready"]) == ["partial"]
    assert q["totals"]["ready_amount"] == 150.0
    assert q["totals"]["payable_now"] == 150.0


def test_trusted_confirm_makes_ready_and_flags_changed_destination(admin_app, client, seeded):
    resp = client.post("/api/payouts/admin/bookings/mark", headers=ADMIN,
                       json={"slug": "live", "username": "vet", "platform": "tiktok", "action": "confirm"})
    assert resp.status_code == 200
    q = _queue(client)
    vet = next(r for r in q["ready"] if r["username"] == "vet")
    assert vet["reason"] == "trusted_confirmed"
    assert vet["destination_issue"] == "changed"
    assert q["totals"]["ready_amount"] == 450.0
    assert q["totals"]["payable_now"] == 150.0  # vet blocked until the change is reviewed
    assert q["totals"]["by_method"] == {"cashapp": 300.0, "paypal": 150.0}


def test_manual_ready_for_partial_delivery_and_clear(admin_app, client, seeded):
    body = {"slug": "live", "username": "partial", "platform": "tiktok", "action": "ready", "note": "agreed 3/5"}
    assert client.post("/api/payouts/admin/bookings/mark", headers=ADMIN, json=body).status_code == 200
    q = _queue(client)
    partial = next(r for r in q["ready"] if r["username"] == "partial")
    assert partial["reason"] == "manual" and partial["destination_issue"] == "missing"

    body["action"] = "clear"
    client.post("/api/payouts/admin/bookings/mark", headers=ADMIN, json=body)
    assert _names(_queue(client)["not_ready"]) == ["partial"]


def test_marks_survive_save_creators_rewrite(admin_app, client, seeded):
    client.post("/api/payouts/admin/bookings/mark", headers=ADMIN,
                json={"slug": "live", "username": "vet", "platform": "tiktok", "action": "confirm"})
    _db.save_creators("live", _db.get_creators("live"))  # what every Hub edit does
    assert "vet" in _names(_queue(client)["ready"])


def test_trust_override(admin_app, client, seeded):
    resp = client.post("/api/payouts/admin/creators/vet/trust", headers=ADMIN, json={"override": "standard"})
    assert resp.status_code == 200
    q = _queue(client)
    assert "vet" in _names(q["not_ready"]) and not q["awaiting_confirmation"]

    client.post("/api/payouts/admin/creators/partial/trust", headers=ADMIN, json={"override": "trusted"})
    assert "partial" in _names(_queue(client)["awaiting_confirmation"])
    assert client.post("/api/payouts/admin/creators/vet/trust", headers=ADMIN,
                       json={"override": "vip"}).status_code == 400


def test_mark_validates_and_requires_admin(admin_app, client, seeded):
    assert client.post("/api/payouts/admin/bookings/mark", json={}).status_code == 401
    bad = {"slug": "live", "username": "vet", "platform": "tiktok", "action": "pay"}
    assert client.post("/api/payouts/admin/bookings/mark", headers=ADMIN, json=bad).status_code == 400
    missing = {"slug": "live", "username": "nobody", "platform": "tiktok", "action": "ready"}
    assert client.post("/api/payouts/admin/bookings/mark", headers=ADMIN, json=missing).status_code == 404


def test_dashboard_shows_payment_coming_after_trusted_confirm(admin_app, client, seeded, db):
    from campaign_manager.services import payout_profiles as payouts
    with db.get_session() as s:
        token = payouts.issue_token(s, "vet")[0].payout_token
    card = lambda: client.post("/api/creator/dashboard", json={"token": token}).json["current"][0]  # noqa: E731
    assert card()["status"] == "in_progress"
    client.post("/api/payouts/admin/bookings/mark", headers=ADMIN,
                json={"slug": "live", "username": "vet", "platform": "tiktok", "action": "confirm"})
    assert card()["status"] == "complete"


def test_admin_can_set_details_and_queue_offers_booking_email(admin_app, client, seeded, db):
    with db.get_session() as s:
        s.query(Creator).filter_by(username="partial").one().paypal_email = "Partial@Gmail.com"
        s.commit()
    row = next(r for r in _queue(client)["not_ready"] if r["username"] == "partial")
    assert row["destination_issue"] == "missing" and row["booking_destination"] == "Partial@Gmail.com"

    bad = client.post("/api/payouts/admin/creators/partial/destination", headers=ADMIN,
                      json={"method": "paypal", "destination": "nope"})
    assert bad.status_code == 400
    ok = client.post("/api/payouts/admin/creators/partial/destination", headers=ADMIN,
                     json={"method": "paypal", "destination": "Partial@Gmail.com"})
    assert ok.status_code == 200
    row = next(r for r in _queue(client)["not_ready"] if r["username"] == "partial")
    assert (row["method"], row["destination"], row["destination_issue"]) == ("paypal", "partial@gmail.com", "")
    assert row["booking_destination"] == ""

    # Fixing a flagged change by hand clears the flag; history keeps the old value.
    client.post("/api/payouts/admin/creators/vet/destination", headers=ADMIN,
                json={"method": "venmo", "destination": "@vet-real"})
    events = client.get("/api/payouts/admin/creators/vet/events", headers=ADMIN).json["events"]
    assert events[0]["event"] == "admin_set" and events[0]["old_destination"] == "$vet"
    assert client.post("/api/payouts/admin/creators/x/destination", json={}).status_code == 401
