from datetime import date
import json
from pathlib import Path

import pytest

from campaign_manager.utils.attribution import calculate_attribution


def _raw_fixture_history(block, history):
    """Undo the fixture's prior recount adjustment to recover Chartmetric totals."""
    offsets = {}
    offset = 0
    recounts = {item["date"]: item["change"] for item in block.get("recounts", [])}
    for point in history:
        offset += recounts.get(point["date"], 0)
        offsets[point["date"]] = offset
    return [{"date": p["date"], "value": p["total"] + offsets[p["date"]]} for p in history]


def test_real_popscore_fixture_raw_recount_and_unusual_decisions():
    root = Path(__file__).parents[2] / "frontend/src/components/campaigns/__tests__/fixtures"
    expected = {
        "espresso": ([], [{"date": "2026-07-12", "change": 1728963}, {"date": "2026-07-13", "change": 1691494}, {"date": "2026-07-14", "change": 1538220}, {"date": "2026-07-15", "change": 1649549}, {"date": "2026-07-16", "change": 1626695}], [
            {"date": "2026-08-02", "change": 51655}, {"date": "2026-09-23", "change": 543105}], []),
        "blinding_lights": ([], [{"date": "2026-05-12", "change": 1286267}, {"date": "2026-05-13", "change": 1427594}, {"date": "2026-05-14", "change": 1493529}, {"date": "2026-05-15", "change": 1556964}, {"date": "2026-05-16", "change": 1558772}], [
            {"date": "2026-05-23", "change": -2820230}, {"date": "2026-06-16", "change": 51143},
            {"date": "2026-09-23", "change": 271879}], [
            # 06-15: 10,656 over the collapsed 2-day gap = 5,328/day; v6
            # computes the local 14-step median pace and after-rate on steps.
            {"date": "2026-06-15", "change": 10656},
            {"date": "2026-06-20", "change": 4917}, {"date": "2026-07-15", "change": 3131},
            {"date": "2026-07-17", "change": 1961}, {"date": "2026-09-06", "change": 7647},
            {"date": "2026-09-29", "change": 5272}]),
    }
    for name, (sr, su, ur, uu) in expected.items():
        fixture = json.loads((root / f"popscore_{name}_walk.json").read_text())
        streams = _raw_fixture_history(fixture["streams"], fixture["streams_history"])
        ugc = _raw_fixture_history(fixture["ugc"], fixture["ugc_history"])
        result = calculate_attribution(fixture["history"], streams, fixture["start_date"], fixture["end_date"],
            today=date(2026, 9, 29), ugc=ugc)
        assert [{k:v for k,v in x.items() if k != "source"} for x in result["streams"]["recounts"]] == sr
        assert [{k:v for k,v in x.items() if k != "source"} for x in result["streams"]["unusual"]] == su
        assert [{k:v for k,v in x.items() if k != "source"} for x in result["ugc"]["recounts"]] == ur
        assert [{k:v for k,v in x.items() if k != "source"} for x in result["ugc"]["unusual"]] == uu


def test_plan_records_current_recount_and_chart_contract():
    plan = (Path(__file__).parents[2] / "docs/plans/2026-09-29-campaign-attribution.md").read_text()
    assert ">=50×pace" in plan
    assert "magnitude >= floor" in plan
    assert "and campaign/follow-up deltas use the recount-adjusted" in plan
    assert "14 prior collapsed step rates" in plan and "1/day" in plan
    assert "observed in production" not in plan
    assert "{date, change, source}" in plan
    assert "counted unusual steps" in plan


def _history(increments, initial=100_000, start=date(2026, 1, 1)):
    from datetime import timedelta
    points, value = [{"date": start.isoformat(), "value": initial}], initial
    for i, inc in enumerate(increments, 1):
        value += inc
        points.append({"date": (start + timedelta(days=i)).isoformat(), "value": value})
    return points


def test_recount_decision_boundaries_and_metric_floors():
    def block(increments, metric="ugc", initial=100_000):
        h = _history(increments, initial)
        return calculate_attribution([], h if metric == "streams" else [], "2026-01-01",
            today=date(2026, 2, 1), ugc=h if metric == "ugc" else [])[metric]
    # Positive step is unusual at >=20×; exact 50× with the absolute floor and confirmation recounts.
    b = block([10] * 14 + [200, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == [{"date": "2026-01-16", "change": 200}]
    b = block([200] * 14 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-16", "change": 10_000}] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == []
    # Above the absolute floor but just below 50× pace: counted as unusual.
    b = block([300] * 14 + [14_999, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == [{"date": "2026-01-16", "change": 14_999}]
    # Next-three condition is strict, and floor equality is included.
    b = block([10] * 14 + [10_000, 500, 500, 500])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == []
    b = block([1] * 14 + [9_999, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == [{"date": "2026-01-16", "change": 9_999}]
    b = block([1] * 14 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-16", "change": 10_000}]
    # Absolute prior increments and floor(pace, 1) prevent zero/negative pace fallbacks.
    b = block([-10] * 14 + [500, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == [{"date": "2026-01-16", "change": 500}]
    b = block([0] * 14 + [50, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == []
    # Fewer than five prior increments means no candidate; five are enough.
    b = block([1] * 4 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == [{"date": "2026-01-06", "change": 10_000}]
    b = block([1] * 5 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-07", "change": 10_000}]
    # The collapsed-step lookback is capped at the immediately previous 14 steps.
    b = block([300] * 8 + [1] * 7 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == []
    b = block([20_000] * 14 + [1_000_000, 1, 1, 1], "streams")
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-16", "change": 1_000_000}]
    b = block([20_000] * 14 + [999_999, 1, 1, 1], "streams")
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == []


def test_small_song_steps_count_and_negative_recount_requires_size_floor():
    for incs in ([0] * 14 + [12], [0] * 14 + [20], [0] * 14 + [2],
                 [1] * 14 + [30], [0] * 14 + [-2]):
        h = _history(incs, initial=150)
        b = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h)["ugc"]
        assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == []
    h = _history([0] * 5 + [-10_000, 1, 1, 1], initial=999_999)
    b = calculate_attribution([], [], "2026-01-01", today=date(2026, 1, 3), ugc=h)["ugc"]
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == []  # early step fails the 10% prior-total gate
    h = _history([0] * 5 + [-9_999, 1, 1, 1], initial=1_000_000)
    b = calculate_attribution([], [], "2026-01-01", today=date(2026, 1, 3), ugc=h)["ugc"]
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == []


def test_recount_adjusted_changes_keep_raw_now_and_mark_adjusted():
    h = _history([0] * 14 + [-500_000, 1, 1, 1], initial=1_000_000)
    result = calculate_attribution([], [], "2026-01-01", "2026-01-16", date(2026, 1, 20), ugc=h)
    assert result["ugc"]["now"] == 500_003
    assert result["ugc"]["change_since_start"] == 3
    assert result["ugc"]["change_since_end"] == 3
    assert result["ugc"].get("adjusted") is True


def test_v6_rollback_pairs_both_directions_use_rate_based_confirmation():
    def series(increments, initial):
        return _history(increments, initial=initial)
    # 100/day history, then a paired correction; adjusted gain excludes both legs.
    h = series([100] * 14 + [-20_000, 20_050] + [100] * 3, 3_300_000)
    b = calculate_attribution([], [], "2026-01-01", "2026-01-19", date(2026, 1, 20), ugc=h)["ugc"]
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-16", "change": -20_000}, {"date": "2026-01-17", "change": 20_050}]
    assert b["adjusted"] is True
    assert b["now"] == h[-1]["value"]
    h = series([100] * 14 + [20_000, -20_000] + [100] * 3, 3_300_000)
    b = calculate_attribution([], [], "2026-01-01", "2026-01-19", date(2026, 1, 20), ugc=h)["ugc"]
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-16", "change": 20_000}, {"date": "2026-01-17", "change": -20_000}]
    # Stream floor is 1M; 1.5M down and recovery both qualify.
    h = series([20_000] * 14 + [-1_500_000, 1_500_000] + [20_000] * 3, 500_000_000)
    b = calculate_attribution([], h, "2026-01-01", "2026-01-19", date(2026, 1, 20))["streams"]
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-16", "change": -1_500_000}, {"date": "2026-01-17", "change": 1_500_000}]


def test_not_started_adjusted_is_false_and_clean_points_skips_dict_date():
    h = _history([0] * 14 + [20_000, 1, 1, 1])
    result = calculate_attribution([], [], "2027-01-01", today=date(2026, 1, 1), ugc=h)
    assert result["phase"] == "not_started"
    assert result["ugc"]["adjusted"] is False and result["streams"]["adjusted"] is False
    assert result["ugc"]["recounts"] is None
    from campaign_manager.services.chartmetric import _clean_points
    assert _clean_points([{"timestp": {"x": 1}, "value": 1}, {"timestp": "2026-01-01", "value": 2}]) == [{"date": "2026-01-01", "value": 2}]


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
    res = calculate_attribution(hist, hist, "2026-01-03", "2026-01-10", date(2026, 1, 2), ugc=hist)
    assert all(v is None for k, v in res["popularity"].items() if k.startswith("change_") or k in ("start", "end", "followup"))
    assert all(v is None for k, v in res["streams"].items() if k not in ("end_is_to_date", "followup_is_to_date", "adjusted"))
    assert res["popularity"]["end_is_to_date"] is False
    assert res["popularity"]["followup_is_to_date"] is False
    assert res["streams"]["end_is_to_date"] is False
    assert res["streams"]["followup_is_to_date"] is False
    assert all(v is None for k, v in res["ugc"].items() if k not in ("end_is_to_date", "followup_is_to_date", "adjusted"))
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
    assert [p["daily"] for p in r["streams_history"]] == [None, 2622134.0, 671148.5, 671148.5]
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
    duplicate_result = calculate_attribution(dup, dup, "2026-01-01", today=date(2026, 1, 1))
    assert duplicate_result["streams"]["start_total"] == 20
    assert [p["date"] for p in duplicate_result["streams_history"]].count("2026-01-01") == 1
    no_base = calculate_attribution([], [{"date": "2026-01-01", "value": 10}], "2025-12-01", "2025-12-02", date(2026, 1, 1))
    assert no_base["streams"]["lift_pct_followup"] is None


def test_change_point_smoothing_covers_stalls_without_fake_leading_or_tail_rates():
    def run(values):
        h = [{"date": f"2026-01-{i:02d}", "value": v} for i, v in enumerate(values, 1)]
        return calculate_attribution([], h, "2026-01-01", today=date(2026, 1, len(values)))['streams_history']
    points = run([100, 110, 110, 120, 120, 130])
    assert sum(p["daily"] or 0 for p in points) == 30
    reset = run([100, 110, 110, 105, 105, 120])
    assert reset[3]["daily"] == -2.5
    assert reset[2]["smoothed"] is True and reset[4]["smoothed"] is True
    leading = run([100, 100, 110, 120])
    assert [p["daily"] for p in leading] == [None, 5.0, 5.0, 10.0]
    tail = run([100, 110, 110, 110])
    assert [p["daily"] for p in tail] == [None, 10.0, None, None]
    ordinary = run([100, 170, 360, 400])
    assert [p["daily"] for p in ordinary] == [None, 70.0, 190.0, 40.0]
    assert all("smoothed" not in p for p in ordinary[1:])


def test_followup_to_date_flags_open_window_and_exact_close_boundary():
    h = [{"date": "2026-01-01", "value": 10}, {"date": "2026-01-10", "value": 20}]
    assert calculate_attribution(h, h, "2026-01-01", "2026-01-10", date(2026, 2, 7))["streams"]["followup_is_to_date"] is True
    exact = [{"date": "2026-02-07", "value": 30}]
    assert calculate_attribution(exact, exact, "2026-01-01", "2026-01-10", date(2026, 3, 1))["streams"]["followup_is_to_date"] is False
    assert calculate_attribution(h, h, "2026-01-01", "2026-01-10", date(2026, 1, 10))["streams"]["followup_total"] is None
    assert calculate_attribution(h, h, "2026-01-01", "2026-01-10", date(2026, 1, 11))["followup_day"] == 1
    assert calculate_attribution(h, h, "2026-01-01", "2026-01-10", date(2026, 1, 11))["end_date"] == "2026-01-10"


def test_ugc_has_complete_cumulative_metric_block_and_smoothed_history():
    h = [
        {"date": "2025-12-18", "value": 0}, {"date": "2026-01-01", "value": 28},
        {"date": "2026-01-02", "value": 38}, {"date": "2026-01-03", "value": 38},
        {"date": "2026-01-04", "value": 58}, {"date": "2026-01-12", "value": 74},
    ]
    res = calculate_attribution(h[:-1], h[:-1], "2026-01-01", "2026-01-04", date(2026, 1, 12), ugc=h)
    ugc = res["ugc"]
    assert {"start", "end", "followup", "now", "now_date", "end_is_to_date",
            "followup_is_to_date", "change_since_end", "change_since_start",
            "start_total", "end_total", "followup_total", "gained_campaign",
            "gained_followup", "growth_pct_campaign", "baseline_daily", "campaign_daily",
            "followup_daily", "lift_pct_campaign", "lift_pct_followup"} <= ugc.keys()
    assert ugc["now"] == 74 and ugc["now_date"] == "2026-01-12"
    assert ugc["change_since_end"] == 16 and ugc["change_since_start"] == 46
    assert res["data_as_of"] == "2026-01-12"
    assert res["ugc_history"][3]["smoothed"] is True
    assert [p["date"] for p in res["streams_history"]].count("2026-01-01") == 1


def test_ugc_calculations_use_ugc_series_for_campaign_and_followup():
    streams = [{"date": "2026-01-01", "value": 100}, {"date": "2026-01-15", "value": 240},
               {"date": "2026-01-25", "value": 340}, {"date": "2026-02-08", "value": 480}]
    ugc = [{"date": "2025-12-18", "value": 0}, {"date": "2026-01-01", "value": 50}, {"date": "2026-01-15", "value": 106},
               {"date": "2026-01-25", "value": 156}, {"date": "2026-02-08", "value": 226},
               {"date": "2026-02-22", "value": 296}]
    result = calculate_attribution([], streams, "2026-01-01", "2026-01-25", date(2026, 3, 1), ugc=ugc)
    block = result["ugc"]
    assert block["gained_campaign"] == 106
    assert block["growth_pct_campaign"] == 212
    assert block["baseline_daily"] == 3.6
    assert block["campaign_daily"] == 4.4
    assert block["followup_daily"] == 5.0
    assert block["followup_total"] == 296
    assert block["lift_pct_campaign"] == 22.2
    assert block["lift_pct_followup"] == 38.9
    assert block["end_is_to_date"] is False and block["followup_is_to_date"] is False
    assert block["gained_campaign"] != result["streams"]["gained_campaign"]


def test_recount_steps_adjust_cumulative_history_but_keep_raw_headlines():
    h = [{"date": f"2026-09-{d:02}", "value": 100000 + 1000*(d-20)} for d in range(14, 23)]
    h += [{"date": "2026-09-23", "value": 645105}]
    h += [{"date": f"2026-09-{d:02}", "value": 648105 + 1000*(d-24)} for d in range(24, 27)]
    result = calculate_attribution([], h, "2026-09-20", "2026-09-26", date(2026, 9, 26), ugc=h)
    assert result["ugc"]["end_total"] == 650105
    assert result["ugc"]["now"] == 650105
    assert result["ugc"]["gained_campaign"] == 7000
    assert [{k:v for k,v in x.items() if k != "source"} for x in result["ugc"]["recounts"]] == [{"date": "2026-09-23", "change": 543105}]
    assert result["ugc_history"][-1]["total"] == 107000
    popularity = [{"date": point["date"], "value": point["value"]} for point in h]
    pop_result = calculate_attribution(popularity, h, "2026-09-20", "2026-09-26", date(2026, 9, 26), ugc=h)
    assert pop_result["popularity"]["change_campaign"] == 550105


def test_ordinary_volatile_five_times_day_is_not_recount():
    h = [{"date": "2026-05-20", "value": 100000}, {"date": "2026-05-21", "value": 101000},
         {"date": "2026-05-22", "value": 102000}, {"date": "2026-05-23", "value": 107000},
         {"date": "2026-05-24", "value": 108000}, {"date": "2026-05-25", "value": 109000}]
    assert calculate_attribution([], [], "2026-05-20", today=date(2026, 5, 25), ugc=h)["ugc"]["recounts"] == []


def test_negative_ugc_recount_in_baseline_window_is_adjusted():
    values = [10_000_000, 10_001_000, 10_002_000, 7_181_770, 7_182_770,
              7_183_770, 7_184_770, 7_185_770, 7_186_770, 7_187_770, 7_188_770]
    h = [{"date": "2026-05-10", "value": 9_989_000}]
    h += [{"date": "2026-05-15", "value": 9_993_770}]
    h += [{"date": f"2026-05-{20+i:02d}", "value": value} for i, value in enumerate(values)]
    result = calculate_attribution([], [], "2026-05-24", "2026-05-30", date(2026, 5, 30), ugc=h)
    # Its 2.82M negative step clears v6's pace, floor, and quiet-after gates.
    assert [{k:v for k,v in x.items() if k != "source"} for x in result["ugc"]["recounts"]] == [{"date": "2026-05-23", "change": -2820230}]
    assert result["ugc"]["start_total"] == 7_182_770
    assert result["ugc"]["end_total"] == 7_188_770
    assert result["ugc"]["gained_campaign"] == 6000
    assert result["ugc"]["baseline_daily"] == 1000.0


def test_ugc_one_day_behind_uses_same_reading_guard():
    h = [{"date": "2026-01-01", "value": 50}]
    result = calculate_attribution([], [], "2026-01-02", "2026-01-03", date(2026, 1, 4), ugc=h)
    assert result["ugc"]["gained_campaign"] is None
    assert result["ugc"]["growth_pct_campaign"] is None
    assert result["ugc"]["gained_followup"] is None
    assert result["ugc"]["change_since_start"] is None
    assert result["ugc"]["change_since_end"] is None


def test_both_histories_empty_are_safe_and_to_date_popularity_flag_boundaries():
    empty = calculate_attribution([], [], "2026-01-01", "2026-01-02", date(2026, 1, 10), ugc=[])
    assert empty["popularity"]["now"] is None and empty["streams"]["now"] is None
    assert empty["ugc"]["now"] is None and empty["streams_history"] == empty["ugc_history"] == []
    h = [{"date": "2026-01-01", "value": 1}, {"date": "2026-01-10", "value": 2}]
    at_end = calculate_attribution(h, h, "2026-01-01", "2026-01-10", date(2026, 1, 11))
    assert at_end["popularity"]["followup_is_to_date"] is True
    at_followup_close = calculate_attribution(h + [{"date": "2026-02-07", "value": 3}], h, "2026-01-01", "2026-01-10", date(2026, 2, 8))
    assert at_followup_close["popularity"]["followup_is_to_date"] is False

@pytest.mark.parametrize("surge_days", [3, 5, 8])
def test_sustained_live_edge_surge_is_counted_in_full(surge_days):
    h = [{"date": f"2026-06-{d:02}", "value": 5000 + 10 * (d - 1)} for d in range(1, 8)]
    total = h[-1]["value"]
    for d in range(8, 8 + surge_days):
        total += 200
        h.append({"date": f"2026-06-{d:02}", "value": total})
    result = calculate_attribution([], [], "2026-06-01", today=date(2026, 6, 8 + surge_days - 1), ugc=h)
    assert [{k:v for k,v in x.items() if k != "source"} for x in result["ugc"]["recounts"]] == []
    assert result["ugc"]["gained_campaign"] == total - 5000


def test_positive_recount_candidate_needs_three_later_readings_and_suppresses_neighbor_smoothing():
    vals = [100_000 + 1000 * i for i in range(7)]
    vals += [vals[-1] + 100_000, vals[-1] + 110_000, vals[-1] + 120_000, vals[-1] + 130_000]
    h = [{"date": f"2026-07-{i+1:02}", "value": v} for i, v in enumerate(vals)]
    result = calculate_attribution([], [], "2026-07-01", today=date(2026, 7, len(h)), ugc=h)
    assert [{k:v for k,v in x.items() if k != "source"} for x in result["ugc"]["recounts"]] == []


def test_positive_recount_step_is_null_daily_and_not_smoothed():
    vals = [100_000 + 1000 * i for i in range(7)]
    vals += [vals[-1] + 100_000, vals[-1] + 101_000, vals[-1] + 102_000, vals[-1] + 103_000, vals[-1] + 104_000]
    # Three tiny following increments confirm a one-time recount.
    vals += [vals[-1] + 1000, vals[-1] + 1000, vals[-1] + 1000]
    h = [{"date": f"2026-07-{i+1:02}", "value": v} for i, v in enumerate(vals)]
    result = calculate_attribution([], [], "2026-07-01", today=date(2026, 7, len(h)), ugc=h)
    assert [{k:v for k,v in x.items() if k != "source"} for x in result["ugc"]["recounts"]] == [{"date": "2026-07-08", "change": 100000}]
    points = result["ugc_history"]
    assert points[7]["daily"] is None and "smoothed" not in points[7]
    assert "smoothed" not in points[6] and "smoothed" not in points[8]


def test_candidate_with_only_two_later_readings_is_counted():
    vals = [100_000 + 1000 * i for i in range(7)]
    vals += [vals[-1] + 100_000, vals[-1] + 101_000, vals[-1] + 102_000]
    h = [{"date": f"2026-07-{i+1:02}", "value": v} for i, v in enumerate(vals)]
    result = calculate_attribution([], [], "2026-07-01", today=date(2026, 7, len(h)), ugc=h)
    assert [{k:v for k,v in x.items() if k != "source"} for x in result["ugc"]["recounts"]] == []
    assert result["ugc"]["now"] == vals[-1]
