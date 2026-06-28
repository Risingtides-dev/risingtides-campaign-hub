"""Tests for campaign_manager.utils.budget."""
from __future__ import annotations

from campaign_manager.utils.budget import calc_budget, calc_stats


class TestCalcBudget:
    def test_zero_creators_uses_full_budget(self):
        result = calc_budget({"budget": 1000}, [])
        assert result == {"total": 1000.0, "booked": 0, "paid": 0, "left": 1000.0, "pct": 0}

    def test_sums_active_creator_rates(self):
        creators = [
            {"total_rate": 300, "paid": "no"},
            {"total_rate": 200, "paid": "yes"},
        ]
        result = calc_budget({"budget": 1000}, creators)
        assert result["booked"] == 500
        assert result["paid"] == 200
        assert result["left"] == 500
        assert result["pct"] == 50

    def test_excludes_removed_creators(self):
        creators = [
            {"total_rate": 100, "status": "active"},
            {"total_rate": 999, "status": "removed"},
        ]
        result = calc_budget({"budget": 1000}, creators)
        assert result["booked"] == 100

    def test_handles_paid_case_insensitively(self):
        creators = [
            {"total_rate": 50, "paid": "YES"},
            {"total_rate": 75, "paid": "Yes"},
            {"total_rate": 25, "paid": "no"},
        ]
        result = calc_budget({"budget": 200}, creators)
        assert result["paid"] == 125

    def test_pct_rounds_to_integer(self):
        result = calc_budget({"budget": 300}, [{"total_rate": 100}])
        assert result["pct"] == 33

    def test_pct_is_zero_when_total_is_zero(self):
        result = calc_budget({"budget": 0}, [{"total_rate": 100}])
        assert result["pct"] == 0

    def test_handles_string_budget(self):
        result = calc_budget({"budget": "500"}, [{"total_rate": "100"}])
        assert result["total"] == 500.0
        assert result["booked"] == 100.0

    def test_missing_budget_defaults_to_zero(self):
        result = calc_budget({}, [{"total_rate": 100}])
        assert result["total"] == 0
        assert result["left"] == -100


class TestCalcStats:
    def test_sums_posts_done_for_active_creators(self):
        creators = [
            {"posts_done": 3},
            {"posts_done": 5},
            {"posts_done": 99, "status": "removed"},
        ]
        result = calc_stats({"budget": 1000}, creators)
        assert result["live_posts"] == 8

    def test_pulls_total_views_from_stored_stats(self):
        result = calc_stats({"budget": 0, "stats": {"total_views": 10000}}, [])
        assert result["total_views"] == 10000

    def test_cpm_is_none_when_views_are_zero(self):
        result = calc_stats({"budget": 1000}, [{"total_rate": 500}])
        assert result["cpm"] is None

    def test_cpm_calculated_from_gross_client_spend_and_views(self):
        meta = {"budget": 1000, "stats": {"total_views": 100_000}}
        creators = [{"total_rate": 500}]
        result = calc_stats(meta, creators)
        # Client spend is grossed up from the 50% market deployment value.
        assert result["cpm"] == 10.0

    def test_cpm_is_none_when_no_spend(self):
        meta = {"budget": 1000, "stats": {"total_views": 10000}}
        result = calc_stats(meta, [])
        assert result["cpm"] is None
