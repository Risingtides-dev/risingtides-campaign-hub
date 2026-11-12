"""security-fix-1112 app-wide write gate: CH-F3 (all writes), CH-F4 (internal
captions fail-closed), CH-F6 (Worker reads stay open), CH-F2/CH2-F7 (PII and
debug reads keyed)."""
from __future__ import annotations

import socket
import subprocess

import pytest

from campaign_manager.models import Campaign
from campaign_manager.utils import hub_auth

FAKE_KEY = "test-key-not-real-0000000000000000"
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Writes that keep their OWN fail-closed authentication instead of the Hub key
# (test-owned list: changing the gate's exemptions must change this test).
EXEMPT_WRITES = {
    "payouts.payout_lookup", "payouts.creator_dashboard", "payouts.payout_submit",  # link token
    "payouts.admin_links", "payouts.admin_rotate", "payouts.admin_clear_flag",
    "payouts.admin_mark_booking", "payouts.admin_set_trust", "payouts.admin_set_destination",
    "payout_batches.create_batch", "payout_batches.add_booking", "payout_batches.approve_batch",
    "payout_batches.cancel_batch", "payout_batches.sync_batch", "payout_batches.remove_item",
    "payout_batches.mark_item_paid",  # PAYOUT_ADMIN_KEY
    "slack_events.slack_events",  # Slack signature
    "webhooks.notion_webhook",  # NOTION_WEBHOOK_SECRET
}


@pytest.fixture(autouse=True)
def _no_outbound(monkeypatch):
    """A gate bug must not turn this test into a live call or a scrape."""
    def refuse(*_a, **_k):
        raise AssertionError("outbound call attempted during gate test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


@pytest.fixture
def seeded(db):
    with db.get_session() as s:
        s.add(Campaign(slug="live", title="Live", completion_status="none"))
        s.commit()


def _mutating_routes(app):
    adapter = app.url_map.bind("localhost")
    for rule in app.url_map.iter_rules():
        methods = sorted((rule.methods or set()) & MUTATING)
        if not methods:
            continue
        values = {}
        for arg in rule.arguments:
            conv = type(rule._converters[arg]).__name__
            values[arg] = 1 if conv == "IntegerConverter" else "x"
        path = adapter.build(rule.endpoint, values, method=methods[0])
        for method in methods:
            yield rule.endpoint, method, path


def test_route_inventory_is_what_the_report_counts(app):
    routes = list(_mutating_routes(app))
    assert len(routes) >= 90
    exempt = {r[0] for r in routes if r[0] in EXEMPT_WRITES}
    assert exempt == EXEMPT_WRITES
    for endpoint, _m, _p in routes:
        assert hub_auth.self_authenticated(endpoint) == (endpoint in EXEMPT_WRITES), endpoint


def test_every_non_exempt_write_refuses_anonymous(app, anon_client, seeded, monkeypatch):
    # Handlers are replaced by a sentinel so an ungated route is reported
    # (status 299) without running its side effects (scrapes, upstream calls).
    def sentinel(*_a, **_k):
        return "HANDLER_RAN", 299

    leaked = []
    for endpoint, method, path in _mutating_routes(app):
        if endpoint in EXEMPT_WRITES:
            continue
        monkeypatch.setitem(app.view_functions, endpoint, sentinel)
        hub_auth.write_fail_limiter.reset()
        resp = anon_client.open(path, method=method, json={})
        if resp.status_code != 401 or (resp.get_json() or {}).get("code") != "unauthorized":
            leaked.append((method, path, resp.status_code))
    assert leaked == []


def test_exempt_writes_still_refuse_anonymous_through_their_own_guard(app, anon_client, seeded):
    leaked = []
    for endpoint, method, path in _mutating_routes(app):
        if endpoint not in EXEMPT_WRITES:
            continue
        # Use the payload that takes each route's most permissive anonymous path.
        payload = ({"type": "url_verification", "challenge": "unsigned-review-challenge"}
                   if endpoint == "slack_events.slack_events" else {})
        resp = anon_client.open(path, method=method, json=payload)
        if resp.status_code < 400:
            leaked.append((method, path, resp.status_code))
    assert leaked == []


def test_gate_fails_closed_when_write_key_unset(anon_client, seeded, monkeypatch):
    monkeypatch.delenv("HUB_WRITE_KEY", raising=False)
    resp = anon_client.post("/api/campaign/create", json={"title": "X"},
                            headers={"X-Hub-Write-Key": FAKE_KEY})
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "hub_write_unconfigured"


def test_gate_rejects_wrong_and_non_ascii_keys(anon_client, seeded):
    for bad in ("wrong", FAKE_KEY + "x", "é" * 34):
        resp = anon_client.post("/api/campaign/live/dashboard-sent", json={"sent": True},
                                headers={"X-Hub-Write-Key": bad})
        assert resp.status_code == 401


def test_operator_with_key_can_write(client, seeded, db):
    resp = client.post("/api/campaign/live/dashboard-sent", json={"sent": True})
    assert resp.status_code == 200


def test_cors_preflight_is_not_gated(anon_client):
    resp = anon_client.open("/api/campaign/create", method="OPTIONS",
                            headers={"Origin": "http://localhost",
                                     "Access-Control-Request-Method": "POST",
                                     "Access-Control-Request-Headers": "content-type,x-hub-write-key"})
    assert resp.status_code == 200


# ── CH-F6: the control-plane Worker's two credential-less reads ────────────

@pytest.mark.parametrize("read_gate", ["", "true"])
@pytest.mark.parametrize("path", ["/api/campaigns?include_finished=true", "/api/campaigns/captions"])
def test_worker_reads_stay_open(anon_client, seeded, monkeypatch, read_gate, path):
    monkeypatch.setenv("HUB_READ_KEY_REQUIRED", read_gate)
    resp = anon_client.get(path, headers={"Accept": "application/json"})
    assert resp.status_code == 200


def test_health_stays_open_with_read_gate(anon_client, monkeypatch):
    monkeypatch.setenv("HUB_READ_KEY_REQUIRED", "true")
    assert anon_client.get("/health").status_code in (200, 503)
    assert anon_client.get("/health").status_code != 401


# ── CH-F2 / CH2-F7: PII and debug reads ────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/paypal/someone", "/api/webhooks/slack/debug",
                                  "/api/campaign/live/cobrand/raw"])
def test_pii_and_debug_reads_always_need_key(anon_client, client, seeded, path):
    assert anon_client.get(path).status_code == 401


def test_paypal_lookup_with_key_still_works(client, seeded):
    assert client.get("/api/paypal/someone").status_code == 200


def test_read_gate_opt_in_covers_campaign_detail(anon_client, client, seeded, monkeypatch):
    assert anon_client.get("/api/campaign/live").status_code == 200  # default: reads unchanged
    monkeypatch.setenv("HUB_READ_KEY_REQUIRED", "true")
    assert anon_client.get("/api/campaign/live").status_code == 401
    assert anon_client.get("/api/creators/someone").status_code == 401
    assert anon_client.get("/api/library/creators").status_code == 401
    assert client.get("/api/campaign/live").status_code == 200


def test_read_gate_leaves_payout_admin_reads_to_payout_key(anon_client, monkeypatch):
    monkeypatch.setenv("HUB_READ_KEY_REQUIRED", "true")
    resp = anon_client.get("/api/payouts/admin/queue")
    assert resp.get_json()["code"] in ("payout_admin_unconfigured", "unauthorized")


# ── CH-F4: internal-captions failed open with HUB_WRITE_KEY unset ──────────

def test_internal_captions_fail_closed_when_key_unset(anon_client, seeded, db, monkeypatch):
    monkeypatch.delenv("HUB_WRITE_KEY", raising=False)
    resp = anon_client.put("/api/campaign/live/internal-captions",
                           json={"internal_captions": "injected", "expected": None})
    assert resp.status_code == 503
    assert db.get_campaign("live").get("internal_captions") is None


def test_internal_captions_short_key_fails_closed(anon_client, seeded, monkeypatch):
    monkeypatch.setenv("HUB_WRITE_KEY", "shared-secret")
    resp = anon_client.put("/api/campaign/live/internal-captions",
                           json={"internal_captions": "x", "expected": None},
                           headers={"X-Hub-Write-Key": "shared-secret"})
    assert resp.status_code == 503
