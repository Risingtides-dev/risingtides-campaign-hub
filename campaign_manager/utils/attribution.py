"""Pure campaign attribution calculations for Chartmetric histories."""
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

FOLLOWUP_DAYS = 28
# Thresholds distinguish systemic steps from normal growth at campaign scale.
UGC_RECOUNT_ABS_FLOOR = 10_000
STREAMS_RECOUNT_ABS_FLOOR = 1_000_000


def _day(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def reading(history, day):
    history = _dedupe(history)
    points = sorted(
        (p for p in history if _day(p.get("date")) and _day(p["date"]) <= day),
        key=lambda p: p["date"],
    )
    return points[-1] if points else None


def _value(history, day):
    point = reading(history, day)
    return point["value"] if point else None


def _dedupe(history):
    by_date = {}
    for point in history:
        if _day(point.get("date")):
            by_date[point["date"]] = point
    return [by_date[k] for k in sorted(by_date)]


def _avg(history, a, b):
    left, right = reading(history, a), reading(history, b)
    if not left or not right:
        return None
    days = (_day(right["date"]) - _day(left["date"])).days
    return round((right["value"] - left["value"]) / days, 1) if days else None


def _pct(numerator, baseline):
    return round(numerator / baseline * 100, 1) if baseline is not None and baseline > 0 else None


def calculate_attribution(popularity, streams, start_date, end_date="", today=None, ugc=None, completion_status=None, overrides=None):
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    start = _day(start_date)
    end = _day(end_date)
    follow_end = end + timedelta(days=FOLLOWUP_DAYS) if end else None
    phase = ("finished_no_end" if completion_status == "completed" and not end else
             "no_start" if not start else "not_started" if today < start else
             "live" if not end or today <= end else
             "followup" if today <= follow_end else "complete")
    pop_start = _value(popularity, start) if start else None
    stream_start = _value(streams, start) if start else None
    end_target = end if end and end <= today else today
    pop_end = _value(popularity, end_target)
    stream_end = _value(streams, end_target)
    popularity, streams, ugc = _dedupe(popularity), _dedupe(streams), _dedupe(ugc or [])
    dates = [_day(p.get("date")) for h in (popularity, streams, ugc) for p in h]
    dates = [d for d in dates if d]
    def latest_day(history):
        found = [_day(p.get("date")) for p in history if _day(p.get("date"))]
        return max(found) if found else None
    pop_latest, stream_latest = latest_day(popularity), latest_day(streams)
    pop_end_to_date = not end or end > today or (pop_latest is not None and pop_latest < end_target)
    stream_end_to_date = not end or end > today or (stream_latest is not None and stream_latest < end_target)
    follow_ready = bool(end and today > end)
    follow_target = min(follow_end, today) if follow_ready else None
    pop_follow = _value(popularity, follow_target) if follow_target else None
    stream_follow = _value(streams, follow_target) if follow_target else None
    in_followup = phase == "followup"
    pop_follow_to_date = bool(in_followup or (follow_target and (pop_latest is None or pop_latest < follow_target)))
    stream_follow_to_date = bool(in_followup or (follow_target and (stream_latest is None or stream_latest < follow_target)))
    def adjust_recounts(history, absolute_floor, overrides=None):
        ordered = _dedupe(history)
        # Detection uses change points: each changed total is measured from the
        # last date at the preceding distinct total (stall days are included).
        collapsed = []
        for index, point in enumerate(ordered):
            if not collapsed or point["value"] != collapsed[-1]["value"]:
                collapsed.append({**point, "raw_index": index, "last_date": point["date"]})
            else:
                # Keep the first date as the event date, but use the final
                # repeated reading as the start of the following step.
                collapsed[-1]["last_date"] = point["date"]
                collapsed[-1]["last_raw_index"] = index
        increments = [collapsed[i]["value"] - collapsed[i-1]["value"] for i in range(1, len(collapsed))]
        gaps = [(_day(collapsed[i]["date"]) - _day(collapsed[i-1]["last_date"])).days for i in range(1, len(collapsed))]
        offsets = [0] * len(ordered)
        recount_indices, found, unusual = set(), [], []
        manually_included_pair_dates = set()
        overrides = overrides or {}
        for j, inc in enumerate(increments):
            raw_i = collapsed[j+1]["raw_index"]
            if collapsed[j+1]["date"] in manually_included_pair_dates:
                continue
            step_rate = abs(inc) / gaps[j] if gaps[j] else 0
            prior_rates = [abs(increments[k]) / gaps[k] for k in range(max(0, j-14), j)
                           if collapsed[k+1]["raw_index"] not in recount_indices and gaps[k] > 0]
            pace = max(1, median(prior_rates)) if len(prior_rates) >= 5 else None
            action = overrides.get(collapsed[j+1]["date"], "auto")
            blocked = action == "include"
            later = list(range(j+1, min(len(increments), j+4)))
            after_rate = (sum(abs(increments[k]) for k in later) / sum(gaps[k] for k in later)
                          if len(later) == 3 and sum(gaps[k] for k in later) else None)
            early = j < 5
            candidate = (step_rate >= 20 * pace) if pace is not None else (early and abs(inc) >= absolute_floor and abs(inc) >= .10 * abs(collapsed[j]["value"]))
            if early:
                auto_recount = (abs(inc) >= absolute_floor and abs(inc) >= .10 * abs(collapsed[j]["value"])
                                and after_rate is not None and after_rate < step_rate / 40)
            else:
                auto_recount = (pace is not None and step_rate >= 50 * pace and after_rate is not None
                                and after_rate < step_rate / 40 and abs(inc) >= absolute_floor)
            # A short opposite-sign rollback pair is treated as one glitch when
            # the independent forward confirmation cannot see past its recovery.
            paired = (j+1 < len(increments) and inc * increments[j+1] < 0
                      and abs(abs(inc)-abs(increments[j+1])) <= max(100, abs(inc)*.05))
            pair_action = overrides.get(collapsed[j+2]["date"], "auto") if j+1 < len(increments) else "auto"
            if action in ("auto", "include") and pair_action in ("auto", "include") and not auto_recount and paired and pace is not None and step_rate >= 50*pace and abs(inc) >= absolute_floor:
                post = list(range(j+2, min(len(increments), j+5)))
                if len(post)==3 and sum(gaps[k] for k in post):
                    quiet = sum(abs(increments[k]) for k in post)/sum(gaps[k] for k in post) < step_rate/40
                    if quiet and abs(increments[j+1]) >= absolute_floor:
                        if action == "include" or pair_action == "include":
                            pair_raw = collapsed[j+2]["raw_index"]
                            choice_date = ordered[raw_i]["date"] if action == "include" else ordered[pair_raw]["date"]
                            unusual.extend(({"date": ordered[raw_i]["date"], "change": inc, "source": "manual", "with": ordered[pair_raw]["date"], "choice_date": choice_date},
                                            {"date": ordered[pair_raw]["date"], "change": increments[j+1], "source": "manual", "with": ordered[raw_i]["date"], "choice_date": choice_date}))
                            manually_included_pair_dates.add(ordered[pair_raw]["date"])
                            continue
                        auto_recount = True
                        pair_raw = collapsed[j+2]["raw_index"]
                        recount_indices.update((raw_i, pair_raw))
                        for k in range(raw_i, len(ordered)): offsets[k] += inc
                        for k in range(pair_raw, len(ordered)): offsets[k] += increments[j+1]
                        found.extend(({"date": ordered[raw_i]["date"], "change": inc, "source": "auto"},
                                      {"date": ordered[pair_raw]["date"], "change": increments[j+1], "source": "auto"}))
            if blocked:
                auto_recount = False
            is_recount = action == "exclude" or (action == "auto" and auto_recount)
            if action == "include":
                candidate = True
            if candidate and not is_recount:
                unusual.append({"date": collapsed[j+1]["date"], "change": inc, "source": "manual" if action == "include" else "auto"})
            if is_recount and raw_i not in recount_indices:
                recount_indices.add(raw_i)
                for k in range(raw_i, len(ordered)): offsets[k] += inc
                found.append({"date": collapsed[j+1]["date"], "change": inc, "source": "manual" if action == "exclude" else "auto"})
        adjusted = [{**p, "value": p["value"] - offsets[i]} for i, p in enumerate(ordered)]
        return adjusted, found, recount_indices, unusual
    streams_adj, streams_recounts, streams_recount_indices, streams_unusual = adjust_recounts(streams, STREAMS_RECOUNT_ABS_FLOOR, (overrides or {}).get("streams"))
    ugc_adj, ugc_recounts, ugc_recount_indices, ugc_unusual = adjust_recounts(ugc, UGC_RECOUNT_ABS_FLOOR, (overrides or {}).get("ugc"))
    baseline_daily = _avg(streams_adj, start - timedelta(days=14), start) if start else None
    campaign_daily = _avg(streams_adj, start, end_target) if start else None
    follow_daily = _avg(streams_adj, end, follow_target) if end and follow_target else None
    data_as_of = max(dates).isoformat() if dates else ""
    same_campaign_reading = bool(start and end_target and reading(popularity, start) and reading(popularity, end_target) and reading(popularity, start)["date"] == reading(popularity, end_target)["date"])
    same_stream_campaign = bool(start and reading(streams, start) and reading(streams, end_target) and reading(streams, start)["date"] == reading(streams, end_target)["date"])
    same_follow_reading = bool(follow_target and reading(popularity, follow_target) and reading(popularity, end_target) and reading(popularity, follow_target)["date"] == reading(popularity, end_target)["date"])
    same_stream_follow = bool(follow_target and reading(streams, follow_target) and reading(streams, end_target) and reading(streams, follow_target)["date"] == reading(streams, end_target)["date"])
    if phase == "not_started":
        pop_start = stream_start = pop_end = stream_end = pop_follow = stream_follow = None
        baseline_daily = campaign_daily = follow_daily = None
        pop_end_to_date = stream_end_to_date = False
        pop_follow_to_date = stream_follow_to_date = False
    def metric_history(history, recount_indices):
        ordered = _dedupe(history)
        anchors = [0] + [i for i in range(1, len(ordered)) if ordered[i]["value"] != ordered[i - 1]["value"]]
        out = [{"date": p["date"], "total": p["value"], "daily": None} for p in ordered]
        anchors = sorted(set(anchors) | recount_indices)
        for index in recount_indices:
            out[index]["daily"] = None
        for a, b in zip(anchors, anchors[1:]):
            if b in recount_indices:
                continue
            gap = (_day(ordered[b]["date"]) - _day(ordered[a]["date"])).days
            rate = round((ordered[b]["value"] - ordered[a]["value"]) / gap, 1) if gap else None
            for i in range(a + 1, b + 1):
                out[i]["daily"] = rate
                if b - a > 1 and i not in recount_indices and i - 1 not in recount_indices and i + 1 not in recount_indices:
                    out[i]["smoothed"] = True
        return out
    stream_history = metric_history(streams_adj, streams_recount_indices)
    ugc_history = metric_history(ugc_adj, ugc_recount_indices)
    def block(history, start_value, end_value, follow_value, end_to_date, follow_to_date):
        latest = history[-1] if history else None
        start_reading = reading(history, start) if start else None
        end_reading = reading(history, end_target)
        same_start_end = bool(start_reading and end_reading and start_reading["date"] == end_reading["date"])
        now = latest["value"] if latest else None
        if phase == "not_started":
            start_value = end_value = follow_value = now = None
        return {"start": start_value, "end": end_value, "end_is_to_date": end_to_date,
            "followup": follow_value, "followup_is_to_date": follow_to_date,
            "now": now, "now_date": latest["date"] if latest and phase != "not_started" else None,
            "change_since_start": now - start_value if now is not None and start_value is not None and start_reading and latest["date"] != start_reading["date"] else None,
            "change_since_end": now - end_value if now is not None and end_value is not None and end_reading and latest["date"] != end_reading["date"] else None}
    ugc_start, ugc_end = (_value(ugc, start) if start else None), _value(ugc, end_target)
    ugc_follow = _value(ugc, follow_target) if follow_target else None
    ugc_latest = latest_day(ugc)
    ugc_end_td = not end or end > today or (ugc_latest is not None and ugc_latest < end_target)
    ugc_follow_td = bool(in_followup or (follow_target and (ugc_latest is None or ugc_latest < follow_target)))
    ugc_same_campaign = bool(start and reading(ugc, start) and reading(ugc, end_target) and reading(ugc, start)["date"] == reading(ugc, end_target)["date"])
    ugc_same_follow = bool(follow_target and reading(ugc, follow_target) and reading(ugc, end_target) and reading(ugc, follow_target)["date"] == reading(ugc, end_target)["date"])
    ugc_start_adj, ugc_end_adj = (_value(ugc_adj, start) if start else None), _value(ugc_adj, end_target)
    ugc_follow_adj = _value(ugc_adj, follow_target) if follow_target else None
    ugc_baseline_daily = _avg(ugc_adj, start - timedelta(days=14), start) if start else None
    ugc_campaign_daily = _avg(ugc_adj, start, end_target) if start else None
    ugc_follow_daily = _avg(ugc_adj, end, follow_target) if end and follow_target else None
    stale_overrides = []
    for metric, history in (("streams", streams), ("ugc", ugc)):
        current_dates = set()
        prior = object()
        for point in history:
            if point["value"] != prior:
                current_dates.add(point["date"])
                prior = point["value"]
        for day, action in ((overrides or {}).get(metric) or {}).items():
            if day not in current_dates:
                stale_overrides.append({"metric": metric, "date": day, "action": action})
    return {
        "stale_overrides": stale_overrides,
        "end_date": end_date or "", "followup_days": FOLLOWUP_DAYS,
        "followup_end": follow_end.isoformat() if end else "", "phase": phase,
        "popularity": {**block(popularity, pop_start, pop_end, pop_follow, pop_end_to_date, pop_follow_to_date),
            "followup": pop_follow, "followup_is_to_date": pop_follow_to_date,
            "change_campaign": pop_end - pop_start if pop_end is not None and pop_start is not None and not same_campaign_reading else None,
            "change_followup": pop_follow - pop_end if pop_follow is not None and pop_end is not None and not same_follow_reading else None},
        "streams": {**block(streams_adj, _value(streams_adj, start) if start else None, _value(streams_adj, end_target), _value(streams_adj, follow_target) if follow_target else None, stream_end_to_date, stream_follow_to_date),
            "adjusted": phase not in ("not_started", "no_start") and bool(streams_recounts),
            "start": stream_start, "end": stream_end, "followup": stream_follow,
            "now": None if phase == "not_started" else (_value(streams, stream_latest) if stream_latest else None),
            "start_total": stream_start, "end_total": stream_end, "end_is_to_date": stream_end_to_date,
            "followup_total": stream_follow, "followup_is_to_date": stream_follow_to_date,
            "gained_campaign": _value(streams_adj, end_target) - _value(streams_adj, start) if stream_end is not None and stream_start is not None and not same_stream_campaign else None,
            "gained_followup": _value(streams_adj, follow_target) - _value(streams_adj, end_target) if stream_follow is not None and stream_end is not None and not same_stream_follow else None,
            "growth_pct_campaign": _pct(_value(streams_adj, end_target) - _value(streams_adj, start), _value(streams_adj, start)) if stream_end is not None and stream_start is not None and not same_stream_campaign else None,
            "baseline_daily": baseline_daily, "campaign_daily": campaign_daily, "followup_daily": follow_daily,
            "lift_pct_campaign": _pct(campaign_daily - baseline_daily, baseline_daily) if campaign_daily is not None and baseline_daily is not None else None,
            "lift_pct_followup": _pct(follow_daily - baseline_daily, baseline_daily) if follow_daily is not None and baseline_daily is not None else None,
            "recounts": None if phase == "not_started" else streams_recounts,
            "unusual": None if phase == "not_started" else streams_unusual},
        "streams_history": stream_history,
        "ugc": {**block(ugc_adj, _value(ugc_adj, start) if start else None, _value(ugc_adj, end_target), _value(ugc_adj, follow_target) if follow_target else None, ugc_end_td, ugc_follow_td),
            "adjusted": phase not in ("not_started", "no_start") and bool(ugc_recounts),
            "start": None if phase == "not_started" else ugc_start, "end": None if phase == "not_started" else ugc_end,
            "followup": None if phase == "not_started" else ugc_follow,
            "now": None if phase == "not_started" else (_value(ugc, ugc_latest) if ugc_latest else None),
            "start_total": None if phase == "not_started" else ugc_start, "end_total": None if phase == "not_started" else ugc_end,
            "followup_total": None if phase == "not_started" else ugc_follow,
            "gained_campaign": None if phase == "not_started" else (_value(ugc_adj, end_target) - _value(ugc_adj, start) if ugc_end is not None and ugc_start is not None and not ugc_same_campaign else None),
            "gained_followup": None if phase == "not_started" else (ugc_follow_adj - ugc_end_adj if ugc_follow is not None and ugc_end is not None and not ugc_same_follow else None),
            "growth_pct_campaign": None if phase == "not_started" else (_pct(_value(ugc_adj, end_target) - _value(ugc_adj, start), _value(ugc_adj, start)) if ugc_end is not None and ugc_start is not None and not ugc_same_campaign else None),
            "baseline_daily": None if phase == "not_started" else ugc_baseline_daily,
            "campaign_daily": None if phase == "not_started" else ugc_campaign_daily,
            "followup_daily": None if phase == "not_started" else ugc_follow_daily,
            "lift_pct_campaign": None if phase == "not_started" else (_pct(ugc_campaign_daily - ugc_baseline_daily, ugc_baseline_daily) if ugc_campaign_daily is not None and ugc_baseline_daily is not None else None),
            "lift_pct_followup": None if phase == "not_started" else (_pct(ugc_follow_daily - ugc_baseline_daily, ugc_baseline_daily) if ugc_follow_daily is not None and ugc_baseline_daily is not None else None),
            "recounts": None if phase == "not_started" else ugc_recounts,
            "unusual": None if phase == "not_started" else ugc_unusual},
        "ugc_history": ugc_history,
        "data_as_of": data_as_of,
        "followup_day": max(1, min(FOLLOWUP_DAYS, (today - end).days)) if phase == "followup" and end else None,
    }
