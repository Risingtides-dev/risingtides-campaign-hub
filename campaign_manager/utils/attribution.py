"""Pure campaign attribution calculations for Chartmetric histories."""
from datetime import date, datetime, timedelta
from statistics import mean, median
from zoneinfo import ZoneInfo

FOLLOWUP_DAYS = 28


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


def calculate_attribution(popularity, streams, start_date, end_date="", today=None, ugc=None, completion_status=None):
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
    def adjust_recounts(history):
        ordered = _dedupe(history)
        increments = [ordered[i]["value"] - ordered[i-1]["value"] for i in range(1, len(ordered))]
        offsets = [0] * len(ordered)
        recount_indices, found, unusual = set(), [], []
        for i, inc in enumerate(increments, 1):
            previous = ordered[i-1]["value"]
            is_recount = inc < 0 and abs(inc) > previous * .01
            candidate = False
            if inc > 0:
                prior = increments[max(0, i - 15):i - 1]
                later = increments[i:i + 3]
                baseline = median(prior) if prior else 0
                if baseline == 0 and prior:
                    baseline = mean(prior)
                candidate = len(prior) >= 5 and (baseline == 0 or inc > 20 * baseline)
                candidate = candidate and len(later) == 3 and median(later) < inc / 20
                is_recount = candidate and previous > 0 and inc >= previous * .10
                if candidate and not is_recount:
                    unusual.append({"date": ordered[i]["date"], "change": inc})
            if is_recount:
                recount_indices.add(i)
                for k in range(i, len(ordered)):
                    offsets[k] += inc
                found.append({"date": ordered[i]["date"], "change": inc})
        adjusted = [{**p, "value": p["value"] - offsets[i]} for i, p in enumerate(ordered)]
        return adjusted, found, recount_indices, unusual
    streams_adj, streams_recounts, streams_recount_indices, streams_unusual = adjust_recounts(streams)
    ugc_adj, ugc_recounts, ugc_recount_indices, ugc_unusual = adjust_recounts(ugc)
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
    return {
        "end_date": end_date or "", "followup_days": FOLLOWUP_DAYS,
        "followup_end": follow_end.isoformat() if end else "", "phase": phase,
        "popularity": {**block(popularity, pop_start, pop_end, pop_follow, pop_end_to_date, pop_follow_to_date),
            "followup": pop_follow, "followup_is_to_date": pop_follow_to_date,
            "change_campaign": pop_end - pop_start if pop_end is not None and pop_start is not None and not same_campaign_reading else None,
            "change_followup": pop_follow - pop_end if pop_follow is not None and pop_end is not None and not same_follow_reading else None},
        "streams": {**block(streams_adj, _value(streams_adj, start) if start else None, _value(streams_adj, end_target), _value(streams_adj, follow_target) if follow_target else None, stream_end_to_date, stream_follow_to_date),
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
