"""Budget and stats calculation helpers."""

from typing import Dict, List


def _num(x, default: float = 0.0) -> float:
    """Coerce to float, tolerating non-numeric/legacy values (''/'TBD'/None).
    Sweep #4 fix: calc_budget runs over EVERY campaign on the list/detail hot
    paths, so one malformed budget/total_rate ('' / 'TBD' / 'n/a' in a legacy
    or imported record) used to raise ValueError and 500 the entire dashboard
    list — not just its own card. Coerce defensively instead."""
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return default


def calc_budget(meta: Dict, creators: List[Dict]) -> Dict:
    total = _num(meta.get("budget", 0))
    active = [c for c in creators if c.get("status", "active") != "removed"]
    booked = sum(_num(c.get("total_rate", 0)) for c in active)
    paid = sum(_num(c.get("total_rate", 0)) for c in active if str(c.get("paid", "")).lower() == "yes")
    left = total - booked
    pct = round(booked / total * 100) if total > 0 else 0
    return {"total": total, "booked": booked, "paid": paid, "left": left, "pct": pct}


def calc_stats(meta: Dict, creators: List[Dict]) -> Dict:
    """Calculate campaign stats from creators and stored stats."""
    active = [c for c in creators if c.get("status", "active") != "removed"]
    live_posts = sum(int(_num(c.get("posts_done", 0))) for c in active)

    stored = meta.get("stats", {})
    total_views = int(_num(stored.get("total_views", 0)))

    budget_info = calc_budget(meta, creators)
    cpm = None
    if total_views > 0 and budget_info["booked"] > 0:
        cpm = (budget_info["booked"] / total_views) * 1_000

    return {
        "live_posts": live_posts,
        "total_views": total_views,
        "cpm": cpm,
    }
