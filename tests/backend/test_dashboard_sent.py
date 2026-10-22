"""Campaigns list checkbox: client dashboard handed to the point of contact."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def _create(client, title="Dash Test"):
    return client.post("/api/campaign/create", json={"title": title, "budget": 1000}).get_json()["slug"]


def _summary(client, slug):
    rows = client.get("/api/campaigns?include_finished=true").get_json()
    return next(r for r in rows if r["slug"] == slug)


class TestDashboardSent:
    def test_defaults_to_not_sent(self, client):
        slug = _create(client)
        assert _summary(client, slug)["dashboard_sent_at"] == ""

    def test_check_then_uncheck(self, client):
        slug = _create(client)
        res = client.post(f"/api/campaign/{slug}/dashboard-sent", json={"sent": True})
        assert res.status_code == 200
        sent_at = res.get_json()["dashboard_sent_at"]
        assert sent_at
        assert _summary(client, slug)["dashboard_sent_at"] == sent_at

        res = client.post(f"/api/campaign/{slug}/dashboard-sent", json={"sent": False})
        assert res.get_json()["dashboard_sent_at"] == ""
        assert _summary(client, slug)["dashboard_sent_at"] == ""

    def test_rechecking_keeps_original_date(self, client):
        slug = _create(client)
        first = client.post(f"/api/campaign/{slug}/dashboard-sent", json={"sent": True}).get_json()
        again = client.post(f"/api/campaign/{slug}/dashboard-sent", json={"sent": True}).get_json()
        assert again["dashboard_sent_at"] == first["dashboard_sent_at"]

    def test_survives_ordinary_campaign_edit(self, client):
        slug = _create(client)
        client.post(f"/api/campaign/{slug}/dashboard-sent", json={"sent": True})
        client.post(f"/api/campaign/{slug}/edit", json={"completion_status": "booked"})
        assert _summary(client, slug)["dashboard_sent_at"]

    @pytest.mark.parametrize("body", [{}, {"sent": "yes"}, {"sent": 1}])
    def test_rejects_non_boolean(self, client, body):
        slug = _create(client)
        assert client.post(f"/api/campaign/{slug}/dashboard-sent", json=body).status_code == 400

    def test_unknown_campaign(self, client):
        assert client.post("/api/campaign/nope/dashboard-sent", json={"sent": True}).status_code == 404
