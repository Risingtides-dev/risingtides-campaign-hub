"""Pure campaign attribution calculations for Chartmetric histories."""
from datetime import date, datetime, timedelta

FOLLOWUP_DAYS = 28


def _day(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def reading(history, day):
    points = sorted(
        (p for p in history if _day(p.get("date")) and _day(p["date"]) <= day),
        key=lambda p: p["date"],
    )
    return points[-1] if points else None


def _value(history, day):
    point = reading(history, day)
    return point["value"] if point else None


def _avg(history, a, b):
    left, right = reading(history, a), reading(history, b)
    if not left or not right:
        return None
    days = (_day(right["date"]) - _day(left["date"])).days
    return round((right["value"] - left["value"]) / days, 1) if days else None


def _pct(numerator, baseline):
    return round(numerator / baseline * 100, 1) if baseline is not None and baseline > 0 else None


def calculate_attribution(popularity, streams, start_date, end_date="", today=None):
    today = today or date.today()
    start = _day(start_date)
    end = _day(end_date)
    follow_end = end + timedelta(days=FOLLOWUP_DAYS) if end else None
    phase = ("no_start" if not start else "not_started" if today < start else
             "live" if not end or today <= end else
             "followup" if today <= follow_end else "complete")
    pop_start = _value(popularity, start) if start else None
    stream_start = _value(streams, start) if start else None
    end_target = end if end and end <= today else today
    pop_end = _value(popularity, end_target)
    stream_end = _value(streams, end_target)
    dates = [_day(p.get("date")) for h in (popularity, streams) for p in h if _day(p.get("date"))]
    data_as_of_day = max(dates) if dates else None
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
    pop_follow_to_date = bool(pop_follow is not None and pop_latest is not None and pop_latest < follow_target)
    stream_follow_to_date = bool(stream_follow is not None and stream_latest is not None and stream_latest < follow_target)
    baseline_daily = _avg(streams, start - timedelta(days=14), start) if start else None
    campaign_daily = _avg(streams, start, end_target) if start else None
    follow_daily = _avg(streams, end, follow_target) if end and follow_target else None
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
    ordered_streams = sorted(streams, key=lambda p: p["date"])
    stream_history = []
    for index, point in enumerate(ordered_streams):
        daily = None
        if index:
            previous = ordered_streams[index - 1]
            gap = (_day(point["date"]) - _day(previous["date"])).days
            if gap:
                daily = round((point["value"] - previous["value"]) / gap, 1)
        stream_history.append({"date": point["date"], "total": point["value"], "daily": daily})
    return {
        "end_date": end_date or "", "followup_days": FOLLOWUP_DAYS,
        "followup_end": follow_end.isoformat() if end else "", "phase": phase,
        "popularity": {"start": pop_start, "end": pop_end, "end_is_to_date": pop_end_to_date,
            "followup": pop_follow, "followup_is_to_date": pop_follow_to_date,
            "change_campaign": pop_end - pop_start if pop_end is not None and pop_start is not None and not same_campaign_reading else None,
            "change_followup": pop_follow - pop_end if pop_follow is not None and pop_end is not None and not same_follow_reading else None},
        "streams": {"start_total": stream_start, "end_total": stream_end, "end_is_to_date": stream_end_to_date,
            "followup_total": stream_follow, "followup_is_to_date": stream_follow_to_date,
            "gained_campaign": stream_end - stream_start if stream_end is not None and stream_start is not None and not same_stream_campaign else None,
            "gained_followup": stream_follow - stream_end if stream_follow is not None and stream_end is not None and not same_stream_follow else None,
            "growth_pct_campaign": _pct(stream_end - stream_start, stream_start) if stream_end is not None and stream_start is not None and not same_stream_campaign else None,
            "baseline_daily": baseline_daily, "campaign_daily": campaign_daily, "followup_daily": follow_daily,
            "lift_pct_campaign": _pct(campaign_daily - baseline_daily, baseline_daily) if campaign_daily is not None and baseline_daily is not None else None,
            "lift_pct_followup": _pct(follow_daily - baseline_daily, baseline_daily) if follow_daily is not None and baseline_daily is not None else None},
        "streams_history": stream_history,
        "data_as_of": data_as_of,
        "followup_day": max(1, min(FOLLOWUP_DAYS, (today - end).days)) if phase == "followup" and end else None,
    }
