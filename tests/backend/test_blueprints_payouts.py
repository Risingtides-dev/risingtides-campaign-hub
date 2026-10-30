"""Creator payout endpoints: token link flow, audit, flags, admin auth."""
from __future__ import annotations

import pytest

from campaign_manager.blueprints import payouts as payouts_bp_module
from campaign_manager.models import CreatorPayoutEvent, CreatorProfile

ADMIN_KEY = "test-payout-admin-key-0123456789"
ADMIN = {"X-Payout-Admin-Key": ADMIN_KEY}


@pytest.fixture(autouse=True)
def _reset_limiters():
    payouts_bp_module.public_limiter.reset()
    payouts_bp_module.admin_fail_limiter.reset()
    yield
    payouts_bp_module.public_limiter.reset()
    payouts_bp_module.admin_fail_limiter.reset()


@pytest.fixture
def admin_app(app):
    app.config.update(PAYOUT_ADMIN_KEY=ADMIN_KEY, PUBLIC_BASE_URL="https://hub.example")
    return app


def _issue(client, *usernames):
    resp = client.post("/api/payouts/admin/links", json={"usernames": list(usernames)}, headers=ADMIN)
    assert resp.status_code == 200, resp.json
    return resp.json["links"]


def _token(link: str) -> str:
    assert "/payout#" in link
    return link.split("#", 1)[1]


def _events(db, username):
    with db.get_session() as s:
        return [e.event for e in s.query(CreatorPayoutEvent)
                .filter_by(username=username).order_by(CreatorPayoutEvent.id)]


# ── admin auth ─────────────────────────────────────────────────────────

def test_admin_disabled_without_key(client):
    resp = client.get("/api/payouts/admin/creators", headers=ADMIN)
    assert resp.status_code == 503


def test_admin_rejects_wrong_key(admin_app, client):
    resp = client.get("/api/payouts/admin/creators", headers={"X-Payout-Admin-Key": "nope"})
    assert resp.status_code == 401


def test_admin_wrong_key_is_rate_limited(admin_app, client):
    codes = [client.get("/api/payouts/admin/creators",
                        headers={"X-Payout-Admin-Key": "nope"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10
    assert codes[-1] == 429


# ── link issuing ───────────────────────────────────────────────────────

def test_links_are_random_stable_and_in_fragment(admin_app, client, db):
    first = _issue(client, "@Alice", "bob")
    assert [l["username"] for l in first] == ["alice", "bob"]
    assert all(l["link"].startswith("https://hub.example/payout#") for l in first)
    tokens = {_token(l["link"]) for l in first}
    assert len(tokens) == 2
    assert all(len(t) >= 40 and "alice" not in t.lower() for t in tokens)
    assert all(l["newly_issued"] for l in first)

    again = _issue(client, "alice")
    assert again[0]["link"] == first[0]["link"]
    assert again[0]["newly_issued"] is False
    assert _events(db, "alice") == ["token_issued"]


def test_rotate_kills_old_link(admin_app, client, db):
    old = _token(_issue(client, "alice")[0]["link"])
    resp = client.post("/api/payouts/admin/creators/alice/rotate-link", headers=ADMIN)
    new = _token(resp.json["link"])
    assert new != old
    assert client.post("/api/payout/lookup", json={"token": old}).status_code == 404
    assert client.post("/api/payout/lookup", json={"token": new}).status_code == 200
    assert _events(db, "alice") == ["token_issued", "token_rotated"]


def test_links_validates_payload(admin_app, client):
    assert client.post("/api/payouts/admin/links", json={}, headers=ADMIN).status_code == 400
    assert client.post("/api/payouts/admin/links", json={"usernames": "x"}, headers=ADMIN).status_code == 400


# ── public creator flow ────────────────────────────────────────────────

@pytest.mark.parametrize("token", [None, "", "short", "a" * 43, "../../etc", 123])
def test_bad_tokens_all_get_identical_404(admin_app, client, token):
    resp = client.post("/api/payout/lookup", json={"token": token})
    assert resp.status_code == 404
    assert resp.json == {"error": payouts_bp_module._INVALID_LINK}


def test_lookup_shows_only_handle_and_masked_destination(admin_app, client, db):
    token = _token(_issue(client, "alice", "bob")[0]["link"])
    with db.get_session() as s:
        p = s.get(CreatorProfile, "alice")
        p.payout_method, p.payout_destination = "paypal", "alice.secret@gmail.com"
        s.commit()

    resp = client.post("/api/payout/lookup", json={"token": token})
    assert resp.status_code == 200
    assert resp.json == {
        "handle": "alice", "method": "paypal",
        "destination_masked": "al•••@gmail.com", "confirmed": False,
    }
    body = resp.get_data(as_text=True)
    assert "alice.secret" not in body and "bob" not in body
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Referrer-Policy"] == "no-referrer"


def test_submit_create_confirm_change_flow(admin_app, client, db):
    token = _token(_issue(client, "alice")[0]["link"])

    r1 = client.post("/api/payout/submit",
                     json={"token": token, "method": "paypal", "destination": "Alice@Gmail.com"})
    assert r1.status_code == 200 and r1.json["result"] == "created"

    r2 = client.post("/api/payout/submit",
                     json={"token": token, "method": "paypal", "destination": "alice@gmail.com"})
    assert r2.json["result"] == "confirmed"

    overview = client.get("/api/payouts/admin/creators", headers=ADMIN).json
    row = next(r for r in overview["creators"] if r["username"] == "alice")
    assert row["flagged"] is False and row["confirmed"] is True

    r3 = client.post("/api/payout/submit",
                     json={"token": token, "method": "cashapp", "destination": "$AliceCash"})
    assert r3.json["result"] == "changed"

    overview = client.get("/api/payouts/admin/creators", headers=ADMIN).json
    assert overview["summary"]["flagged"] == 1
    row = overview["creators"][0]  # flagged rows sort first
    assert row["username"] == "alice" and row["flagged"] is True
    assert (row["method"], row["destination"]) == ("cashapp", "$alicecash")

    events = client.get("/api/payouts/admin/creators/alice/events", headers=ADMIN).json["events"]
    changed = events[0]
    assert changed["event"] == "changed"
    assert (changed["old_method"], changed["old_destination"]) == ("paypal", "alice@gmail.com")
    assert (changed["new_method"], changed["new_destination"]) == ("cashapp", "$alicecash")
    assert "client_ip" not in changed

    assert client.post("/api/payouts/admin/creators/alice/clear-flag", headers=ADMIN).status_code == 200
    overview = client.get("/api/payouts/admin/creators", headers=ADMIN).json
    assert overview["summary"]["flagged"] == 0
    assert _events(db, "alice") == ["token_issued", "created", "confirmed", "changed", "flag_cleared"]


def test_submit_rejects_invalid_destination_without_saving(admin_app, client, db):
    token = _token(_issue(client, "alice")[0]["link"])
    resp = client.post("/api/payout/submit",
                       json={"token": token, "method": "paypal", "destination": "nope"})
    assert resp.status_code == 400
    assert "PayPal" in resp.json["error"]
    with db.get_session() as s:
        assert (s.get(CreatorProfile, "alice").payout_destination or "") == ""
    assert _events(db, "alice") == ["token_issued"]


def test_public_endpoints_are_rate_limited(admin_app, client):
    codes = [client.post("/api/payout/lookup", json={"token": "x"}).status_code for _ in range(31)]
    assert codes[:30] == [404] * 30
    assert codes[-1] == 429


def test_rate_limit_keys_on_rightmost_forwarded_ip(admin_app, client):
    # A spoofed leftmost entry must not let a client dodge the limit.
    for i in range(30):
        client.post("/api/payout/lookup", json={"token": "x"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"})
    resp = client.post("/api/payout/lookup", json={"token": "x"},
                       headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    assert resp.status_code == 429


def test_library_api_never_exposes_payout_fields(admin_app, client, db):
    _issue(client, "alice")
    profile_dict = None
    with db.get_session() as s:
        profile_dict = s.get(CreatorProfile, "alice").to_dict()
    assert not any(k.startswith("payout_") for k in profile_dict)
