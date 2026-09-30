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
        # These early steps are below 10% of the already-large previous total.
        "espresso": ([], [], [
            {"date": "2026-08-02", "change": 51655}, {"date": "2026-09-23", "change": 543105}], []),
        "blinding_lights": ([], [], [
            {"date": "2026-05-23", "change": -2820230}, {"date": "2026-06-16", "change": 51143},
            {"date": "2026-09-23", "change": 271879}], [
            # 06-14: the changed reading date starts the collapsed step; the
            # repeated 06-15 total extends the next step's starting anchor.
            {"date": "2026-06-14", "change": 10656},
                {"date": "2026-06-20", "change": 4917}, {"date": "2026-06-29", "change": 1646},
                {"date": "2026-07-15", "change": 3131},
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
    b = block([10] * 14 + [199, 1, 1, 1])
    assert b["unusual"] == []  # 19.9x is below the inclusive 20x candidate gate.
    b = block([200] * 14 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-16", "change": 10_000}] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == []
    # Above the absolute floor but just below 50× pace: counted as unusual.
    b = block([300] * 14 + [14_999, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == [{"date": "2026-01-16", "change": 14_999}]
    # Next-three condition is strict, and floor equality is included.
    b = block([10] * 14 + [10_000, 250, 250, 250])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == []
    b = block([1] * 14 + [9_999, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == [{"date": "2026-01-16", "change": 9_999}]
    b = block([1] * 14 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-16", "change": 10_000}]
    # Absolute prior increments and max(1, median pace) prevent zero/negative pace fallbacks.
    b = block([-10] * 14 + [500, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == [{"date": "2026-01-16", "change": 500}]
    b = block([0] * 14 + [50, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == []
    b = block([0] * 14 + [20, 1, 1, 1])
    assert b["unusual"] == []  # pace floor 1 makes this exactly a 20x candidate.
    b = block([1] * 4 + [9_999, 1, 1, 1], initial=50_000)
    assert b["recounts"] == [] and b["unusual"] == []  # early steps still need the metric floor.
    # Fewer than five prior increments means no pace candidate; Jan 6 is
    # below the 10% previous-total gate (10K / 100,004).
    b = block([1] * 4 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [] and [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]] == []
    # The same step clears 10% when the previous total is 90K. A sustained
    # tail keeps it unusual instead of meeting the quiet-after recount rule.
    b = block([1] * 4 + [10_000, 250, 250, 250], initial=90_000)
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == []
    assert {"date": "2026-01-06", "change": 10_000} in [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]]
    b = block([1] * 4 + [10_000, 1, 1, 1], initial=99_996)
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-06", "change": 10_000}]
    b = block([1] * 5 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-07", "change": 10_000}]
    # The 14-step window drops the oldest high step; the median over its
    # remaining seven high and seven low rates is 150.5/day, so this recounts.
    b = block([300] * 8 + [1] * 7 + [10_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-17", "change": 10_000}]
    b = block([300] * 8 + [1] * 7 + [7_000, 1, 1, 1])
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == []
    assert {"date": "2026-01-17", "change": 7_000} in [{k:v for k,v in x.items() if k != "source"} for x in b["unusual"]]
    b = block([1_000] * 14 + [1_000_000, 1, 1, 1], "streams", initial=500_000_000)
    assert [{k:v for k,v in x.items() if k != "source"} for x in b["recounts"]] == [{"date": "2026-01-16", "change": 1_000_000}]
    b = block([1_000] * 14 + [999_999, 1, 1, 1], "streams", initial=500_000_000)
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


def test_including_either_leg_of_rollback_pair_counts_both_as_reported():
    h = _history([300] * 14 + [20_000, -20_000, 300, 300, 300, 300], initial=200_000)
    first, second = h[15]["date"], h[16]["date"]
    expected = h[-1]["value"] - h[0]["value"]
    for chosen in (first, second):
        result = calculate_attribution([], [], h[0]["date"], h[-1]["date"], date(2026, 3, 1), ugc=h,
                                       overrides={"ugc": {chosen: "include"}})["ugc"]
        assert result["gained_campaign"] == expected == 5_400
        for day in (first, second):
            assert {"date": day, "change": h[15 if day == first else 16]["value"] - h[14 if day == first else 15]["value"],
                    "source": "manual", "with": (second if day == first else first), "choice_date": chosen} in result["unusual"]


def test_pair_thresholds_and_recount_dates_are_exact():
    # Pair legs must be within 5%, and the second leg must meet its own floor.
    h = _history([100] * 14 + [10_000, -9_500, 100, 100, 100], initial=3_300_000)
    result = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h)["ugc"]
    assert not all(any(x["date"] == h[i]["date"] for x in result["recounts"]) for i in (15, 16))
    h = _history([100] * 14 + [20_000, -18_000, 100, 100, 100], initial=3_300_000)
    result = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h)["ugc"]
    assert not all(any(x["date"] == h[i]["date"] for x in result["recounts"]) for i in (15, 16))
    # An exact one-fortieth tail is not quiet (strict comparison).
    h = _history([100] * 14 + [20_000, -20_000, 500, 500, 500], initial=3_300_000)
    result = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h)["ugc"]
    assert not any(x["date"] in (h[15]["date"], h[16]["date"]) for x in result["recounts"])
    # Recount is dated at the changed reading, even when that total repeats.
    h = _history([300] * 14 + [20_000, 0, 0, 1, 1, 1], initial=200_000)
    whole = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h)
    assert {"date": h[15]["date"], "change": 20_000, "source": "auto"} in whole["ugc"]["recounts"]
    assert whole["ugc_history"][16]["total"] == h[14]["value"]


def test_not_started_adjusted_is_false_and_clean_points_skips_dict_date():
    h = _history([0] * 14 + [20_000, 1, 1, 1])
    result = calculate_attribution([], h, "2027-01-01", today=date(2026, 1, 1), ugc=h)
    assert result["phase"] == "not_started"
    assert result["ugc"]["adjusted"] is False and result["streams"]["adjusted"] is False
    assert result["ugc"]["recounts"] is None
    streams_h = _history([20_000] * 14 + [1_000_000, 1, 1, 1], initial=500_000_000)
    no_start = calculate_attribution([], streams_h, "", today=date(2026, 1, 1))
    assert no_start["phase"] == "no_start"
    assert no_start["streams"]["adjusted"] is False
    no_start_ugc = calculate_attribution([], [], "", today=date(2026, 1, 1), ugc=streams_h)
    assert no_start_ugc["ugc"]["adjusted"] is False
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


def test_candidate_with_only_two_later_readings_is_not_a_recount():
    vals = [100_000 + 1000 * i for i in range(7)]
    vals += [vals[-1] + 100_000, vals[-1] + 101_000, vals[-1] + 102_000]
    h = [{"date": f"2026-07-{i+1:02}", "value": v} for i, v in enumerate(vals)]
    result = calculate_attribution([], [], "2026-07-01", today=date(2026, 7, len(h)), ugc=h)
    assert [{k:v for k,v in x.items() if k != "source"} for x in result["ugc"]["recounts"]] == []
    assert result["ugc"]["now"] == vals[-1]


def test_v6_required_scenario_pins_from_pass11():
    from datetime import timedelta

    def series(increments, initial, gaps=None):
        out = [{"date": "2026-01-01", "value": initial}]
        value, day = initial, date(2026, 1, 1)
        for i, inc in enumerate(increments):
            value += inc
            day += timedelta(days=(gaps[i] if gaps else 1))
            out.append({"date": day.isoformat(), "value": value})
        return out

    def classify(h, metric="ugc"):
        return calculate_attribution([], h if metric == "streams" else [], "2026-01-01",
            today=date.fromisoformat(h[-1]["date"]), ugc=h if metric == "ugc" else [])[metric]

    # Repeated daily totals are a cadence detail. The collapsed rates stay at
    # 1.5K/2K/4K UGC per day and 200K streams per day.
    for daily, cadence in ((1500, 7), (2000, 3), (4000, 3)):
        increments = [daily if (i + 1) % cadence == 0 else 0 for i in range(70)]
        h = series(increments, 1_000_000)
        b = classify(h)
        assert b["recounts"] == []
        assert b["now"] - h[0]["value"] == sum(increments)
    for daily, cadence in ((200_000, 7), (200_000, 3)):
        increments = [daily if (i + 1) % cadence == 0 else 0 for i in range(70)]
        h = series(increments, 100_000_000)
        b = classify(h, "streams")
        assert b["recounts"] == [] and b["now"] - h[0]["value"] == sum(increments)

    # Viral but real growth remains counted despite a quiet three step tail.
    h = series([300] * 14 + [20_000, 0, 2500, 0] + [1700] * 4, 200_000)
    b = classify(h)
    assert b["recounts"] == []
    assert {"date": h[15]["date"], "change": 20_000, "source": "auto"} in b["unusual"]

    # A week-long flat run makes catch-up growth ordinary per-day cadence.
    h = series([300] * 7 + [0] * 7 + [10_500, 0, 1500, 0, 1500, 0], 200_000)
    assert classify(h)["recounts"] == []
    # The step immediately after a stalled run spans from the final flat
    # reading, so a 10K catch-up is a 100x recount rather than an 8-day step.
    h = series([100] * 5 + [0] * 7 + [10_000, 1, 1, 1], 200_000)
    assert classify(h)["recounts"] == [{"date": h[13]["date"], "change": 10_000, "source": "auto"}]

    # F3/F5 sequence pins that prior recount steps are excluded from pace and both
    # signs can be classified as recounts.
    h = series([200] * 14 + [15_000] + [1000] * 4 + [51_655, 1000, 1000, 1000], 200_000)
    assert classify(h)["recounts"] == [{"date": h[20]["date"], "change": 51_655, "source": "auto"}]
    h = series([1000] * 4 + [-2_820_000] + [1000] * 4 + [50_000] + [1000] * 5, 10_000_000)
    assert [(x["date"], x["change"]) for x in classify(h)["recounts"]] == [(h[5]["date"], -2_820_000), (h[10]["date"], 50_000)]

    # The rollback pair is a flat offset in the adjusted series; raw now is intact.
    base = [120, 80, 0, 150, 90, 110, 100, 0, 95, 105, 130, 70, 100, 100]
    h = series(base + [-20_000, 20_050, 100, 100, 100, 100], 3_300_000)
    b = classify(h)
    assert b["gained_campaign"] == 1650
    assert b["now"] == h[-1]["value"]
    h = series(base + [20_000, -20_000, 100, 100, 100, 100], 3_300_000)
    assert classify(h)["gained_campaign"] == 1650

    # Large streams retain their 1M floor and suppress a matched dip/recovery.
    h = series([20_000] * 14 + [-1_500_000, 1_520_000, 20_000, 20_000, 20_000], 500_000_000)
    b = classify(h, "streams")
    assert [x["change"] for x in b["recounts"]] == [-1_500_000, 1_520_000]
    assert b["gained_campaign"] == sum([20_000] * 14 + [20_000, 20_000, 20_000])


def test_manual_overrides_are_applied_after_auto_and_scoped_to_supplied_campaign():
    h = _history([300] * 14 + [20_000, 300, 300, 300], initial=200_000)
    day = h[15]["date"]
    auto = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h)
    included = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h,
        overrides={"ugc": {day: "include"}})["ugc"]
    assert included["recounts"] == []
    assert {"date": day, "change": 20_000, "source": "manual"} in included["unusual"]
    assert {"date": day, "change": 20_000, "source": "auto"} in auto["ugc"]["recounts"]
    excluded = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h,
        overrides={"ugc": {day: "exclude"}})["ugc"]
    assert {"date": day, "change": 20_000, "source": "manual"} in excluded["recounts"]
    assert all(x["date"] != day for x in excluded["unusual"])
    reset = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h,
        overrides={"ugc": {day: "auto"}})["ugc"]
    assert reset["recounts"] == auto["ugc"]["recounts"]


def test_excluded_steps_do_not_raise_the_later_pace_median():
    increments = [1000] * 7 + [100_000] * 7 + [60_000, 1, 1, 1]
    h = _history(increments, initial=10_000_000)
    excluded_dates = {h[i]["date"]: "exclude" for i in range(8, 15)}
    b = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h,
        overrides={"ugc": excluded_dates})["ugc"]
    assert [x["date"] for x in b["recounts"]] == [h[i]["date"] for i in range(8, 16)]


def test_stall_pace_filter_uses_collapsed_steps_raw_indices():
    increments = [1_000, 0] * 7 + [100_000] * 7 + [60_000, 1, 1, 1]
    h = _history(increments, initial=10_000_000)
    overrides = {h[i]["date"]: "exclude" for i in range(15, 22)}
    b = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h,
        overrides={"ugc": overrides})["ugc"]
    assert b["recounts"][-1] == {"date": h[22]["date"], "change": 60_000, "source": "auto"}
    assert b["gained_campaign"] == 7_003


def test_override_constraints_disable_pairing_and_keep_steps_single_classification():
    # Both legs are large opposite steps with a quiet tail. Pin each include
    # independently: it forces that leg to unusual and prevents pair recount.
    h = _history([300] * 14 + [20_000, -20_000, 1, 1, 1], initial=200_000)
    for index in (15, 16):
        day = h[index]["date"]
        result = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h,
            overrides={"ugc": {day: "include"}})["ugc"]
        assert all(x["date"] != day for x in result["recounts"])
        assert any(x["date"] == day and x["change"] == h[index]["value"] - h[index - 1]["value"] and x["source"] == "manual" for x in result["unusual"])
        assert len({x["date"] for x in result["recounts"] + result["unusual"]}) == len(result["recounts"] + result["unusual"])
    single = _history([300] * 14 + [20_000, 300, 300, 300], initial=200_000)
    day = single[15]["date"]
    included = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=single,
        overrides={"ugc": {day: "include"}})["ugc"]
    assert included["recounts"] == []
    assert {"date": day, "change": 20_000, "source": "manual"} in included["unusual"]


def test_stale_overrides_are_reported_and_not_applied():
    h = _history([300] * 14 + [20_000, 300, 300, 300], initial=200_000)
    result = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h,
        overrides={"ugc": {"2026-01-30": "exclude", "2026-03-01": "include"}})
    assert result["stale_overrides"] == [
        {"metric": "ugc", "date": "2026-01-30", "action": "exclude"},
        {"metric": "ugc", "date": "2026-03-01", "action": "include"}]
    assert result["ugc"]["recounts"] == [{"date": "2026-01-16", "change": 20_000, "source": "auto"}]


def test_override_uses_collapsed_step_event_date():
    h = _history([300] * 14 + [20_000, 0, 0, 1, 1, 1], initial=200_000)
    event_day = h[15]["date"]
    result = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h,
        overrides={"ugc": {event_day: "include"}})["ugc"]
    assert result["recounts"] == []
    assert {"date": event_day, "change": 20_000, "source": "manual"} in result["unusual"]


def test_seeded_small_song_monte_carlo_has_zero_false_recounts():
    import math
    import random

    rng = random.Random(11)

    def poisson(lam):
        limit, product, count = math.exp(-lam), 1.0, 0
        while product > limit:
            product *= rng.random()
            count += 1
        return count - 1

    cases = 0
    for lam in (0.2, 0.5, 1, 2, 5):
        for initial, spike in ((100, 10), (150, 20), (300, 25), (1000, 40), (5000, 400), (20000, 2000)):
            for _ in range(10):
                increments = [poisson(lam) for _ in range(14)] + [spike + poisson(lam)] + [poisson(lam) for _ in range(3)]
                h = _history(increments, initial=initial)
                result = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h)
                assert result["ugc"]["recounts"] == []
                cases += 1
    assert cases == 300


def test_pace_uses_median_not_mean():
    # Twelve 100/day steps and two 1,000/day steps have median 100 but mean
    # 228.6. The exact 10K candidate clears 50x the median only.
    h = _history([100] * 12 + [1000] * 2 + [10_000, 1, 1, 1], initial=100_000)
    b = calculate_attribution([], [], "2026-01-01", today=date(2026, 2, 1), ugc=h)["ugc"]
    assert b["recounts"] == [{"date": h[15]["date"], "change": 10_000, "source": "auto"}]


def test_streams_v3_adjusted_fields_keep_raw_totals_and_history_shape():
    h = _history([20_000] * 14 + [1_500_000, 20_000, 20_000, 20_000, 20_000], initial=100_000_000)
    result = calculate_attribution([], h, h[14]["date"], h[-1]["date"], today=date(2026, 1, 20))
    b = result["streams"]
    assert b["adjusted"] is True
    assert b["start_total"] == h[14]["value"] and b["end_total"] == h[-1]["value"]
    assert b["now"] == h[-1]["value"]
    assert b["gained_campaign"] == 80_000
    assert b["growth_pct_campaign"] == pytest.approx(round(80_000 / h[14]["value"] * 100, 1))
    assert b["baseline_daily"] == 20_000.0 and b["campaign_daily"] == 16_000.0
    assert result["streams_history"][-1]["total"] == h[-1]["value"] - 1_500_000
    baseline_h = _history([20_000] * 5 + [1_500_000] + [20_000] * 12, initial=100_000_000)
    baseline_result = calculate_attribution([], baseline_h, baseline_h[14]["date"], baseline_h[-1]["date"],
        today=date(2026, 1, 19))
    assert baseline_result["streams"]["baseline_daily"] == 18_571.4
    clean = _history([20_000] * 18, initial=100_000_000)
    clean_result = calculate_attribution([], clean, clean[14]["date"], clean[-1]["date"], today=date(2026, 1, 19))
    assert clean_result["streams"]["adjusted"] is False


def _series_with_prestart_drop(base, per_day, drop, drop_day=10, days=40):
    """Daily cumulative readings from 2026-01-01 with one large drop before the campaign."""
    points, total = [], base
    for i in range(days):
        if i:
            total += per_day
        if i == drop_day:
            total += drop
        points.append({"date": date(2026, 1, 1 + i).isoformat() if i < 31 else date(2026, 2, i - 30).isoformat(), "value": total})
    return points


def test_growth_pct_divides_by_reported_start_total_when_a_recount_precedes_the_campaign():
    # A -2M (ugc) / -200M (streams) Chartmetric restatement on Jan 11 is excluded as a
    # recount. Growth during the campaign must be measured against the Start total the
    # table shows (as reported), not against the recount-adjusted series.
    ugc = _series_with_prestart_drop(4_000_000, 1_000, -2_000_000)
    streams = _series_with_prestart_drop(400_000_000, 100_000, -200_000_000)
    result = calculate_attribution([], streams, "2026-01-21", "2026-01-31", today=date(2026, 2, 9), ugc=ugc)

    u, s = result["ugc"], result["streams"]
    assert [r["date"] for r in u["recounts"]] == ["2026-01-11"]
    assert [r["date"] for r in s["recounts"]] == ["2026-01-11"]
    assert u["start_total"] == 2_020_000 and u["gained_campaign"] == 10_000
    assert u["growth_pct_campaign"] == 0.5  # 10,000 / 2,020,000; the adjusted base would give 0.2
    assert s["start_total"] == 202_000_000 and s["gained_campaign"] == 1_000_000
    assert s["growth_pct_campaign"] == 0.5  # 1M / 202M; the adjusted base would give 0.2
