"""Smoke tests: confirm the test infrastructure boots."""
from __future__ import annotations


def test_health_endpoint_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "db_active" in body


def test_database_fixture_creates_tables(db):
    """Sanity check: the test DB session is wired up and tables exist."""
    assert db.is_active()
    # Empty list -- no campaigns yet, but the query should not error.
    assert db.list_campaigns() == []
