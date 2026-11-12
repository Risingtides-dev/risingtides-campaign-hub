"""security-fix-1112 CH2-F1..F4: payout-affecting and abuse routes need the Hub write key.

Every test here uses ``anon_client`` (no X-Hub-Write-Key) and proves the route
refuses BEFORE it touches state or calls an upstream; ``client`` (the
authenticated operator) keeps working — see the existing route tests.
"""
from __future__ import annotations

import pytest

from campaign_manager.models import Campaign, Creator

DENIED = (401, 503)
FAKE_KEY = "test-key-not-real-0000000000000000"


@pytest.fixture
def booked(db):
    with db.get_session() as s:
        camp = Campaign(slug="live", title="Live", completion_status="none")
        s.add(camp)
        s.flush()
        s.add(Creator(campaign_id=camp.id, username="booked", posts_owed=4, posts_done=0,
                      total_rate=100, paypal_email="real@example.test"))
        s.commit()
    return "live"


def _booking(db):
    with db.get_session() as s:
        row = s.query(Creator).filter_by(username="booked").one()
        return (float(row.total_rate), int(row.posts_owed), row.paypal_email, row.paid, row.status)


# ── CH2-F1: payout amount (total_rate) and readiness (posts_owed) ──────────

CREATOR_WRITES = [
    ("/api/campaign/live/creator/add",
     {"username": "attacker", "total_rate": 99999, "posts_owed": 0, "paypal_email": "x@evil.test"}),
    ("/api/campaign/live/creator/booked/edit",
     {"total_rate": 99999, "posts_owed": 0, "paypal_email": "x@evil.test"}),
    ("/api/campaign/live/creator/booked/toggle-paid", {}),
    ("/api/campaign/live/creator/booked/remove", {}),
    ("/api/campaign/live/creator/remove", {"username": "booked"}),
]


@pytest.mark.parametrize("path,body", CREATOR_WRITES)
def test_ch2_f1_creator_writes_refuse_anonymous(anon_client, db, booked, path, body):
    before = _booking(db)
    resp = anon_client.post(path, json=body)
    assert resp.status_code == 401, resp.get_json()
    assert _booking(db) == before
    with db.get_session() as s:
        assert s.query(Creator).filter_by(username="attacker").count() == 0


@pytest.mark.parametrize("path,body", CREATOR_WRITES)
def test_ch2_f1_wrong_key_refused(anon_client, db, booked, path, body):
    resp = anon_client.post(path, json=body, headers={"X-Hub-Write-Key": "wrong-" + FAKE_KEY})
    assert resp.status_code == 401


@pytest.mark.parametrize("path,body", CREATOR_WRITES)
def test_ch2_f1_fails_closed_without_configured_key(anon_client, db, booked, monkeypatch, path, body):
    monkeypatch.delenv("HUB_WRITE_KEY", raising=False)
    before = _booking(db)
    resp = anon_client.post(path, json=body, headers={"X-Hub-Write-Key": ""})
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "hub_write_unconfigured"
    assert _booking(db) == before


def test_ch2_f1_short_key_fails_closed(anon_client, db, booked, monkeypatch):
    monkeypatch.setenv("HUB_WRITE_KEY", "short")
    resp = anon_client.post("/api/campaign/live/creator/booked/edit",
                            json={"total_rate": 1, "posts_owed": 1}, headers={"X-Hub-Write-Key": "short"})
    assert resp.status_code == 503


def test_ch2_f1_operator_with_key_can_still_edit(client, db, booked):
    resp = client.post("/api/campaign/live/creator/booked/edit",
                       json={"total_rate": 150, "posts_owed": 3, "paypal_email": "real@example.test"})
    assert resp.status_code == 200
    assert _booking(db)[:2] == (150.0, 3)


def test_ch2_f1_failures_are_rate_limited(anon_client, db, booked):
    codes = [anon_client.post("/api/campaign/live/creator/booked/toggle-paid").status_code
             for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[-1] == 429
    assert _booking(db)[3] == "no"


# ── CH2-F2: every unauthenticated writer of a booking/memory PayPal email ───

PAYPAL_WRITES = [
    ("POST", "/api/migrate/paypal-bulk", {"paypal_memory": {"booked": "x@evil.test"}}),
    ("POST", "/api/migrate/inbox-bulk", {"items": [{"id": "i1", "creators": []}]}),
    ("POST", "/api/migrate/internal", {"creators": ["someone"]}),
    ("POST", "/api/inbox", {"campaign_slug": "live",
                            "creators": [{"username": "booked", "paypal_email": "x@evil.test"}]}),
    ("POST", "/api/inbox/i1/approve", {"campaign_slug": "live",
                                       "creators": [{"username": "new1", "paypal_email": "x@evil.test"}]}),
    ("POST", "/api/inbox/i1/dismiss", {}),
    ("POST", "/api/library/creators", {"username": "booked2", "paypal_email": "x@evil.test"}),
    ("PATCH", "/api/library/creators/booked", {"paypal_email": "x@evil.test"}),
]


@pytest.mark.parametrize("method,path,body", PAYPAL_WRITES)
def test_ch2_f2_paypal_writers_refuse_anonymous(anon_client, db, booked, method, path, body):
    resp = anon_client.open(path, method=method, json=body)
    assert resp.status_code == 401, (path, resp.get_json())
    assert db.get_paypal("booked") in ("", None)
    assert _booking(db)[2] == "real@example.test"


# ── CH2-F3: Content Lab proxy must not lend its key to anonymous callers ───

LAB_WRITES = [
    ("PUT", "/api/sound-assignments/pages/page-1/playlist", {"sound_ids": []}),
    ("POST", "/api/sound-assignments/pages/page-1/playlist/songs", {"sound_id": "s"}),
    ("DELETE", "/api/sound-assignments/pages/page-1/playlist/songs/s", None),
    ("DELETE", "/api/sound-assignments/pages/page-1/playlist", None),
    ("POST", "/api/sound-assignments/sync", None),
    ("POST", "/api/sound-assignments/send/poster-1", None),
    ("POST", "/api/sound-assignments/send-all", None),
]


@pytest.mark.parametrize("method,path,body", LAB_WRITES)
def test_ch2_f3_lab_writes_refuse_anonymous_and_never_forward(app, anon_client, monkeypatch, method, path, body):
    import requests

    app.config.update(CONTENT_LAB_URL="https://content-lab.invalid",
                      CONTENT_LAB_HUB_API_KEY="test-key-not-real-lab-000000000000")
    forwarded = []
    monkeypatch.setattr(requests, "request", lambda *a, **k: forwarded.append((a, k)))
    resp = anon_client.open(path, method=method, json=body)
    assert resp.status_code == 401
    assert forwarded == []


# ── CH2-F4: outreach send/confirm, network roster and ManyChat replies ─────

OUTREACH_WRITES = [
    ("POST", "/api/campaign/live/outreach/send", {"message_template": "send your PayPal to x@evil.test"}),
    ("POST", "/api/campaign/live/outreach/add", {"creators": [{"username": "booked"}]}),
    ("POST", "/api/campaign/live/outreach/remove", {"username": "booked"}),
    ("POST", "/api/campaign/live/outreach/confirm", {"username": "booked"}),
    ("POST", "/api/network", {"username": "n1", "paypal_email": "x@evil.test"}),
    ("PUT", "/api/network/n1", {"paypal_email": "x@evil.test"}),
    ("DELETE", "/api/network/n1", None),
    ("POST", "/api/manychat/webhook", {"subscriber_id": "1", "text": "hi"}),
]


@pytest.mark.parametrize("method,path,body", OUTREACH_WRITES)
def test_ch2_f4_outreach_writes_refuse_anonymous(app, anon_client, db, booked, monkeypatch, method, path, body):
    import requests

    app.config.update(MANYCHAT_API_KEY="test-key-not-real-manychat-0000000")
    sent = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: sent.append((a, k)))
    resp = anon_client.open(path, method=method, json=body)
    assert resp.status_code == 401
    assert sent == []
