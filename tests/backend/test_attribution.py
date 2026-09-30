from datetime import date

from campaign_manager.utils.attribution import calculate_attribution


def test_missing_baseline_and_gaps_and_negative_delta():
    result = calculate_attribution(
        [{"date": "2026-01-10", "value": 10}],
        [{"date": "2026-01-10", "value": 100}, {"date": "2026-01-20", "value": 55}],
        "2026-01-05", "", date(2026, 1, 12),
    )
    assert result["popularity"]["start"] is None
    assert result["streams"]["baseline_daily"] is None
    assert result["streams"]["growth_pct_campaign"] is None
    assert result["streams_history"][1]["daily"] == -4.5
    assert result["popularity"]["end_is_to_date"] is True
    assert result["popularity"]["followup"] is None


def test_phase_boundaries_and_followup_metrics():
    pop = [{"date": "2026-01-01", "value": 10}, {"date": "2026-01-20", "value": 20},
           {"date": "2026-02-01", "value": 18}]
    streams = [{"date": "2025-12-18", "value": 0}, {"date": "2026-01-01", "value": 140},
               {"date": "2026-01-20", "value": 330}, {"date": "2026-02-01", "value": 450}]
    assert calculate_attribution(pop, streams, "", today=date(2026, 1, 1))["phase"] == "no_start"
    assert calculate_attribution(pop, streams, "2026-01-02", today=date(2026, 1, 1))["phase"] == "not_started"
    assert calculate_attribution(pop, streams, "2026-01-01", "2026-01-20", date(2026, 1, 20))["phase"] == "live"
    follow = calculate_attribution(pop, streams, "2026-01-01", "2026-01-20", date(2026, 2, 1))
    assert follow["phase"] == "followup"
    assert follow["popularity"]["change_campaign"] == 10
    assert follow["popularity"]["change_followup"] == -2
    assert follow["streams"]["followup_daily"] == 10.0
    assert follow["streams"]["growth_pct_campaign"] == 135.7
    assert calculate_attribution(pop, streams, "2026-01-01", "2026-01-20", date(2026, 3, 1))["phase"] == "complete"


def test_followup_not_reached_and_future_end():
    history = [{"date": "2026-01-01", "value": 10}, {"date": "2026-01-20", "value": 20}]
    res = calculate_attribution(history, history, "2026-01-01", "2026-02-01", date(2026, 1, 20))
    assert res["popularity"]["end_is_to_date"] is True
    assert res["popularity"]["followup"] is None
    assert res["popularity"]["followup_is_to_date"] is False
