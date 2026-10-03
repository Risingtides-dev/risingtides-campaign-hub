"""Regression: the efficiency endpoints must emit strictly valid JSON.

A creator with spend but zero tracked views/engagement gets
``float('inf')`` for cost_per_view / cost_per_engagement. Python's json
serializer happily writes that as bare ``Infinity`` — which is NOT valid
JSON, so the browser's JSON.parse threw "Unexpected token 'I'" and the
entire Booking Efficiency tab died. The API now sends null for
non-finite metrics.
"""
from __future__ import annotations

import json

from campaign_manager.models import Campaign, Creator


def _seed_spend_no_views(db, slug="inf-camp", username="ghost_creator"):
    """A booked creator with real spend and zero tracked views."""
    with db.get_session() as s:
        camp = Campaign(slug=slug, title=slug, artist="A", song="S")
        s.add(camp)
        s.commit()
        s.add(Creator(
            campaign_id=camp.id, username=username,
            posts_owed=2, total_rate=500.0,
        ))
        s.commit()


class TestEfficiencyJsonSafe:
    def test_report_has_no_infinity_tokens(self, db, client):
        _seed_spend_no_views(db)
        resp = client.get("/api/efficiency/report")
        assert resp.status_code == 200
        assert b"Infinity" not in resp.data
        assert b"NaN" not in resp.data

    def test_infinite_unit_costs_serialize_as_null(self, db, client):
        _seed_spend_no_views(db)
        resp = client.get("/api/efficiency/report")
        # Strict parse — reject the IEEE constants Python's json tolerates.
        def _no_constants(name):
            raise AssertionError(f"non-JSON constant in response: {name}")
        report = json.loads(resp.data, parse_constant=_no_constants)
        rows = (
            report["top_performers"]
            + report["undervalued_deals"]
            + report["overpriced_creators"]
        )
        ghost = next(r for r in rows if r["creator_username"] == "ghost_creator")
        assert ghost["cost_per_view"] is None
        assert ghost["cost_per_engagement"] is None
        # Finite fields stay numeric.
        assert ghost["total_spend"] == 500.0
        assert ghost["roi_ratio"] == 0

    def test_all_infinite_costs_dont_crash_averages(self, db, client):
        # Every analyzed creator has inf unit costs -> the averaging code
        # used to divide by an empty filtered list (ZeroDivisionError).
        _seed_spend_no_views(db, slug="inf-a", username="ghost_a")
        _seed_spend_no_views(db, slug="inf-b", username="ghost_b")
        resp = client.get("/api/efficiency/report")
        assert resp.status_code == 200
        report = json.loads(resp.data)
        assert report["avg_cost_per_view"] == 0
        assert report["avg_cost_per_engagement"] == 0

    def test_leaderboard_is_json_safe_too(self, db, client):
        _seed_spend_no_views(db)
        resp = client.get("/api/efficiency/leaderboard")
        assert resp.status_code == 200
        assert b"Infinity" not in resp.data
