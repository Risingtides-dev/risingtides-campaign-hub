"""Budget and stats calculation helpers."""

from typing import Dict, List

CLIENT_SPEND_MULTIPLIER = 2.0


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


def gross_client_spend(deployed_spend: float) -> float:
    """Convert Campaign Hub's net market deployment amount to client spend."""
    return _num(deployed_spend) * CLIENT_SPEND_MULTIPLIER


def calc_cpm(deployed_spend: float, total_views: int) -> float | None:
    """Calculate CPM from gross client spend.

    Campaign Hub budget/rate fields represent the 50% deployed-to-market
    amount. Client-facing CPM uses the full amount the client spent.
    """
    views = int(_num(total_views, 0))
    spend = gross_client_spend(deployed_spend)
    if views > 0 and spend > 0:
        return (spend / views) * 1_000
    return None


def calc_stats(meta: Dict, creators: List[Dict]) -> Dict:
    """Calculate campaign stats from creators and stored stats."""
    active = [c for c in creators if c.get("status", "active") != "removed"]
    live_posts = sum(int(_num(c.get("posts_done", 0))) for c in active)

    stored = meta.get("stats", {})
    total_views = int(_num(stored.get("total_views", 0)))

    budget_info = calc_budget(meta, creators)
    cpm = calc_cpm(budget_info["booked"], total_views)

    return {
        "live_posts": live_posts,
        "total_views": total_views,
        "cpm": cpm,
    }
