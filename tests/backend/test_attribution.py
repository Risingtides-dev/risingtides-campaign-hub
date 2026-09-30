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


def test_boundary_baseline_uses_reading_before_fourteen_day_boundary():
    hist = [{"date": "2025-12-15", "value": 0}, {"date": "2026-01-01", "value": 170}]
    res = calculate_attribution(hist, hist, "2026-01-01", today=date(2026, 1, 1))
    assert res["streams"]["baseline_daily"] == 10.0


def test_not_started_has_no_attribution_values_and_nonpositive_baseline_pct_is_null():
    hist = [{"date": "2026-01-01", "value": 10}, {"date": "2026-01-02", "value": 20}]
    res = calculate_attribution(hist, hist, "2026-01-03", "2026-01-10", date(2026, 1, 2))
    assert all(v is None for k, v in res["popularity"].items() if k.startswith("change_") or k in ("start", "end", "followup"))
    assert all(v is None for k, v in res["streams"].items() if k not in ("end_is_to_date", "followup_is_to_date"))
    assert res["popularity"]["end_is_to_date"] is False
    assert res["popularity"]["followup_is_to_date"] is False
    assert res["streams"]["end_is_to_date"] is False
    assert res["streams"]["followup_is_to_date"] is False
    from campaign_manager.utils.attribution import _pct
    assert _pct(10, 0) is None and _pct(10, -2) is None


def test_complete_phase_has_followup_values_and_data_based_to_date_and_followup_day():
    hist = [{"date": "2025-12-18", "value": 0}, {"date": "2026-01-01", "value": 140},
            {"date": "2026-01-20", "value": 330}, {"date": "2026-02-17", "value": 610}]
    res = calculate_attribution(hist, hist, "2026-01-01", "2026-01-20", date(2026, 3, 1))
    assert res["phase"] == "complete"
    assert res["streams"]["followup_total"] == 610
    assert res["followup_end"] == "2026-02-17"
    assert res["followup_day"] is None
    assert res["streams"]["followup_is_to_date"] is False


def test_same_reading_changes_are_null():
    hist = [{"date": "2026-01-01", "value": 10}]
    res = calculate_attribution(hist, hist, "2026-01-01", "2026-01-02", date(2026, 1, 2))
    assert res["popularity"]["change_campaign"] is None
    assert res["streams"]["gained_campaign"] is None
    assert res["streams"]["gained_followup"] is None


def test_series_flags_follow_each_series_and_exact_followup_values():
    pop = [{"date": "2026-01-01", "value": 10}, {"date": "2026-01-08", "value": 15}]
    streams = [{"date": "2025-12-18", "value": 0}, {"date": "2026-01-01", "value": 100}, {"date": "2026-01-08", "value": 90}, {"date": "2026-01-18", "value": 110}]
    res = calculate_attribution(pop, streams, "2026-01-01", "2026-01-10", date(2026, 1, 18))
    assert res["phase"] == "followup" and res["followup_day"] == 8
    assert res["popularity"]["end_is_to_date"] is True
    assert res["streams"]["end_is_to_date"] is False
    assert res["popularity"]["followup_is_to_date"] is True
    assert res["streams"]["followup_is_to_date"] is True
    assert res["streams"]["gained_campaign"] == -10
    assert res["streams"]["gained_followup"] == 20
    assert res["streams"]["growth_pct_campaign"] == -10.0
    assert res["streams"]["lift_pct_campaign"] == -119.7
    assert res["streams"]["lift_pct_followup"] == -71.8
    assert calculate_attribution(pop, streams, "2026-01-01", "2026-01-10", date(2026, 2, 7))["phase"] == "followup"
    assert calculate_attribution(pop, streams, "2026-01-01", "2026-01-10", date(2026, 2, 8))["phase"] == "complete"


def test_to_date_flags_are_series_specific_and_not_started_values_null():
    pop = [{"date": "2026-01-09", "value": 15}]
    streams = [{"date": "2026-01-08", "value": 120}]
    res = calculate_attribution(pop, streams, "2026-01-01", "2026-01-10", date(2026, 1, 15))
    assert res["data_as_of"] == "2026-01-09"
    assert res["popularity"]["end_is_to_date"] is True
    assert res["streams"]["end_is_to_date"] is True
    future = calculate_attribution(pop, streams, "2026-02-01", "2026-02-10", date(2026, 1, 15))
    assert future["phase"] == "not_started"
    assert future["popularity"]["start"] is None and future["streams"]["start_total"] is None


def test_daily_smooths_repeat_runs_but_boundaries_keep_raw_totals():
    h = [{"date": "2026-09-24", "value": 3191203786}, {"date": "2026-09-25", "value": 3193825920},
         {"date": "2026-09-26", "value": 3193825920}, {"date": "2026-09-27", "value": 3195168217}]
    r = calculate_attribution([], h, "2026-09-25", "2026-09-26", date(2026, 9, 27))
    assert [p["daily"] for p in r["streams_history"]] == [None, 1321477.0, 1321477.0, 1321477.0]
    assert r["streams"]["start_total"] == 3193825920
    assert r["streams"]["end_total"] == 3193825920
    flat = [{"date": f"2026-09-0{i}", "value": v} for i, v in enumerate([90, 100, 100, 100, 110], 1)]
    assert calculate_attribution([], flat, "2026-09-03", "2026-09-05", date(2026, 9, 5))["streams"]["gained_campaign"] == 10


def test_tail_repeat_daily_and_duplicate_dates_and_missing_baseline_followup():
    h = [{"date": "2026-01-01", "value": 90}, {"date": "2026-01-02", "value": 100},
         {"date": "2026-01-03", "value": 100}, {"date": "2026-01-04", "value": 100}]
    r = calculate_attribution(h, h, "2026-01-01", "2026-01-02", date(2026, 1, 3))
    assert r["streams_history"][0]["daily"] is None
    assert [p["daily"] for p in r["streams_history"]] == [None, 10.0, None, None]
    dup = [{"date": "2026-01-01", "value": 10}, {"date": "2026-01-01", "value": 20}]
    assert calculate_attribution(dup, dup, "2026-01-01", today=date(2026, 1, 1))["streams"]["start_total"] == 20
    no_base = calculate_attribution([], [{"date": "2026-01-01", "value": 10}], "2025-12-01", "2025-12-02", date(2026, 1, 1))
    assert no_base["streams"]["lift_pct_followup"] is None


def test_followup_to_date_flags_open_window_and_exact_close_boundary():
    h = [{"date": "2026-01-01", "value": 10}, {"date": "2026-01-10", "value": 20}]
    assert calculate_attribution(h, h, "2026-01-01", "2026-01-10", date(2026, 2, 7))["streams"]["followup_is_to_date"] is True
    exact = [{"date": "2026-02-07", "value": 30}]
    assert calculate_attribution(exact, exact, "2026-01-01", "2026-01-10", date(2026, 3, 1))["streams"]["followup_is_to_date"] is False
    assert calculate_attribution(h, h, "2026-01-01", "2026-01-10", date(2026, 1, 10))["streams"]["followup_total"] is None
    assert calculate_attribution(h, h, "2026-01-01", "2026-01-10", date(2026, 1, 11))["followup_day"] == 1
    assert calculate_attribution(h, h, "2026-01-01", "2026-01-10", date(2026, 1, 11))["end_date"] == "2026-01-10"
