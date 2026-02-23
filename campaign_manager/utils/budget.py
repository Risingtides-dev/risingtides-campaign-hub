"""Budget and stats calculation helpers."""

from typing import Dict, List


def calc_budget(meta: Dict, creators: List[Dict]) -> Dict:
    total = float(meta.get("budget", 0))
    active = [c for c in creators if c.get("status", "active") != "removed"]
    booked = sum(float(c.get("total_rate", 0)) for c in active)
    paid = sum(float(c.get("total_rate", 0)) for c in active if str(c.get("paid", "")).lower() == "yes")
    left = total - booked
    pct = round(booked / total * 100) if total > 0 else 0
    return {"total": total, "booked": booked, "paid": paid, "left": left, "pct": pct}


def calc_stats(meta: Dict, creators: List[Dict]) -> Dict:
    """Calculate campaign stats from creators and stored stats."""
    active = [c for c in creators if c.get("status", "active") != "removed"]
    live_posts = sum(int(c.get("posts_done", 0)) for c in active)

    stored = meta.get("stats", {})
    total_views = int(stored.get("total_views", 0))

    budget_info = calc_budget(meta, creators)
    cpm = None
    if total_views > 0 and budget_info["booked"] > 0:
        cpm = (budget_info["booked"] / total_views) * 1_000_000

    return {
        "live_posts": live_posts,
        "total_views": total_views,
        "cpm": cpm,
    }
