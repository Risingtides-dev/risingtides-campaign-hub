"""Performance windows and rate memory for the Creator Library.

Two ideas drive this module.

**Recency beats history.** A page that pulled 50k a year ago and 3k last
month is a different booking decision, and a lifetime average hides that
completely. Every number is therefore computed over a window, defaulting to
60 days.

**Median beats average.** One viral post drags a mean far above anything the
creator typically delivers. `median` is what to expect; `avg`, `peak` and
`viral_rate` are kept alongside it for when a client wants a swing.

The functions here are pure — they take rows and a date and return numbers,
so the ranking logic can be pinned down by tests without a database.
"""
from __future__ import annotations

import re
import statistics
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# A post counts as "viral" at 100k views. Jake's number: at the volumes
# Rising Tides books, a million is rare enough to be noise, while 100k is
# the line where a post meaningfully moved a sound.
VIRAL_THRESHOLD = 100_000

# Window name -> lookback in days. None means "everything on record".
WINDOWS: Dict[str, Optional[int]] = {
    "w30": 30,
    "w60": 60,
    "w90": 90,
    "wall": None,
}

DEFAULT_WINDOW = "w60"

_VIDEO_ID_RE = re.compile(r"/video/(\d+)")


def _percentile(values: Sequence[int], q: float) -> int:
    """Linear-interpolated percentile. `statistics.quantiles` needs n>=2."""
    ordered = sorted(values)
    if not ordered:
        return 0
    if len(ordered) == 1:
        return int(ordered[0])
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return int(ordered[low] + (ordered[high] - ordered[low]) * (pos - low))


def _cpm(rate: Optional[float], views: int) -> Optional[float]:
    """Cost per thousand views. Undefined — not infinite — at zero views."""
    if not rate or views <= 0:
        return None
    return round(rate / views * 1000, 2)


def dedupe_posts(
    rows: Iterable[Tuple[str, date, int]],
) -> List[Tuple[date, int]]:
    """Collapse rows that describe the same video.

    A creator's post submitted under two campaigns arrives twice, which was
    inflating both post counts and view totals. Keyed on the TikTok video id
    where the URL exposes one, falling back to the raw URL.

    When the same video appears with different view counts — two trackers
    fetched at different times — the larger number wins, since views only
    ever climb and the bigger figure is the later observation.
    """
    best: Dict[str, Tuple[date, int]] = {}
    for url, when, views in rows:
        match = _VIDEO_ID_RE.search(url or "")
        key = match.group(1) if match else (url or "")
        current = best.get(key)
        if current is None or views > current[1]:
            best[key] = (when, views)
    return sorted(best.values(), key=lambda row: row[0], reverse=True)


def _window_stats(
    posts: Sequence[Tuple[date, int]],
    rate: Optional[float],
) -> Optional[Dict]:
    if not posts:
        return None

    views = [v for _, v in posts]
    median = int(statistics.median(views))
    p25 = _percentile(views, 0.25)
    viral = sum(1 for v in views if v >= VIRAL_THRESHOLD)

    return {
        "posts": len(posts),
        "total": sum(views),
        "median": median,
        "avg": int(statistics.mean(views)),
        "p25": p25,
        "peak": max(views),
        "viral_rate": round(viral / len(views) * 100, 1),
        # What the current rate buys at typical performance. This is the
        # number to book on — lifetime CPM flatters a page that has cooled.
        "pcpm": _cpm(rate, median),
        # Same sum against a bottom-quartile post: the downside case.
        "floor": _cpm(rate, p25),
    }


def build_windows(
    posts: Iterable[Tuple[date, int]],
    today: Optional[date] = None,
    rate: Optional[float] = None,
) -> Dict[str, Optional[Dict]]:
    """Summarise (date, views) pairs across every window.

    A window with no posts resolves to None rather than a zeroed dict, so the
    UI can show a dash. A zero would rank the creator as free rather than
    unknown, which is the more dangerous mistake.
    """
    today = today or date.today()
    rows = [(d, int(v or 0)) for d, v in posts if d is not None]

    out: Dict[str, Optional[Dict]] = {}
    for name, days in WINDOWS.items():
        if days is None:
            scoped = rows
        else:
            cutoff = today - timedelta(days=days)
            scoped = [(d, v) for d, v in rows if d >= cutoff]
        out[name] = _window_stats(scoped, rate)
    return out


def with_rate(
    windows: Dict[str, Optional[Dict]],
    rate: Optional[float],
) -> Dict[str, Optional[Dict]]:
    """Attach projected and worst-case CPM to cached windows.

    Kept separate from `build_windows` because the two inputs change on
    completely different clocks: view counts are refreshed by a scheduled
    job walking every tracker, while a rate changes the moment Jake types
    one. Recomputing CPM at read time means an edited rate is reflected
    instantly without waiting for the next stats run.
    """
    out: Dict[str, Optional[Dict]] = {}
    for name, stats in (windows or {}).items():
        if not stats:
            out[name] = None
            continue
        merged = dict(stats)
        merged["pcpm"] = _cpm(rate, int(stats.get("median") or 0))
        merged["floor"] = _cpm(rate, int(stats.get("p25") or 0))
        out[name] = merged
    return out


def _as_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def effective_rate(
    override: Optional[float],
    override_at: Optional[datetime],
    last_rate: Optional[float],
    last_booked_at: Optional[date],
) -> Tuple[Optional[float], str]:
    """Resolve what a creator should cost on the next booking.

    Jake's rule, verbatim: "when i edit a rate save that as their rate for
    adding to campaigns. but if it changes to something else use the most
    recent."

    So a hand-set rate sticks until reality overtakes it — a *newer* booking
    at a different price wins, an older one does not. Ties go to the human,
    who set the rate knowing what they had just booked.

    Returns (rate, source) where source is "override", "booking" or "none",
    so the UI can explain where the number came from.
    """
    has_override = override is not None
    has_booking = last_rate is not None

    if has_override and has_booking:
        set_on = _as_date(override_at)
        booked_on = _as_date(last_booked_at)
        if set_on and booked_on and booked_on > set_on:
            return last_rate, "booking"
        return override, "override"

    if has_override:
        return override, "override"
    if has_booking:
        return last_rate, "booking"
    return None, "none"
