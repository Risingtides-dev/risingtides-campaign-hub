"""security-fix-1112 CH-F1: POST /api/webhooks/notion must not create campaigns
for an unauthenticated caller (an injected row would reach the Worker through
GET /api/campaigns?include_finished=true)."""
from __future__ import annotations

import pytest

SECRET = "test-key-not-real-notion-0000000000"
HEADER = "X-Notion-Webhook-Secret"
BODY = {"artist": "Injected", "song": "Row",
        "tiktok_sound_link": "https://www.tiktok.com/music/injected-1234567890123456789"}


def _worker_sees_injected(client):
    rows = client.get("/api/campaigns?include_finished=true").get_json()
    return any(r.get("slug") == "injected_row" for r in rows)


def test_fails_closed_when_secret_unset(client, db, monkeypatch):
    monkeypatch.delenv("NOTION_WEBHOOK_SECRET", raising=False)
    resp = client.post("/api/webhooks/notion", json=BODY)
    assert resp.status_code == 503
    assert resp.get_json()["code"] == "notion_webhook_unconfigured"
    assert db.get_campaign("injected_row") is None
    assert not _worker_sees_injected(client)


def test_short_secret_fails_closed(client, db, monkeypatch):
    monkeypatch.setenv("NOTION_WEBHOOK_SECRET", "short")
    resp = client.post("/api/webhooks/notion", json=BODY, headers={HEADER: "short"})
    assert resp.status_code == 503
    assert db.get_campaign("injected_row") is None


@pytest.mark.parametrize("headers", [{}, {HEADER: "wrong"}, {HEADER: SECRET + "x"},
                                     {"X-Hub-Write-Key": SECRET}])
def test_missing_or_wrong_secret_is_401(client, db, monkeypatch, headers):
    monkeypatch.setenv("NOTION_WEBHOOK_SECRET", SECRET)
    resp = client.post("/api/webhooks/notion", json=BODY, headers=headers)
    assert resp.status_code == 401
    assert db.get_campaign("injected_row") is None
    assert not _worker_sees_injected(client)


def test_non_ascii_secret_header_is_401_not_500(client, db, monkeypatch):
    monkeypatch.setenv("NOTION_WEBHOOK_SECRET", SECRET)
    resp = client.post("/api/webhooks/notion", json=BODY, headers={HEADER: "é" * 40})
    assert resp.status_code == 401


def test_correct_secret_still_creates(client, db, monkeypatch):
    monkeypatch.setenv("NOTION_WEBHOOK_SECRET", SECRET)
    resp = client.post("/api/webhooks/notion", json=BODY, headers={HEADER: SECRET})
    assert resp.status_code == 201
    assert db.get_campaign("injected_row")["source"] == "notion"
