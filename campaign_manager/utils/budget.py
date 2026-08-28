"""Budget and stats calculation helpers."""

from typing import Dict, List

CLIENT_SPEND_MULTIPLIER = 2.0


def to_number(x, default: float = 0.0) -> float:
    """Coerce to float, tolerating non-numeric/legacy values (''/'TBD'/None).
    Sweep #4 fix: calc_budget runs over EVERY campaign on the list/detail hot
    paths, so one malformed budget/total_rate ('' / 'TBD' / 'n/a' in a legacy
    or imported record) used to raise ValueError and 500 the entire dashboard
    list — not just its own card. Coerce defensively instead."""
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return default


# Back-compat: this was `_num` before the campaigns blueprint needed it.
_num = to_number


def calc_budget(meta: Dict, creators: List[Dict]) -> Dict:
    total = to_number(meta.get("budget", 0))
    active = [c for c in creators if c.get("status", "active") != "removed"]
    booked = sum(to_number(c.get("total_rate", 0)) for c in active)
    paid = sum(to_number(c.get("total_rate", 0)) for c in active if str(c.get("paid", "")).lower() == "yes")
    left = total - booked
    pct = round(booked / total * 100) if total > 0 else 0
    return {"total": total, "booked": booked, "paid": paid, "left": left, "pct": pct}


def gross_client_spend(deployed_spend: float) -> float:
    """Convert Campaign Hub's net market deployment amount to client spend."""
    return to_number(deployed_spend) * CLIENT_SPEND_MULTIPLIER


def calc_cpm(deployed_spend: float, total_views: int) -> float | None:
    """Calculate CPM from gross client spend.

    Campaign Hub budget/rate fields represent the 50% deployed-to-market
    amount. Client-facing CPM uses the full amount the client spent.
    """
    views = int(to_number(total_views, 0))
    spend = gross_client_spend(deployed_spend)
    if views > 0 and spend > 0:
        return (spend / views) * 1_000
    return None


def calc_stats(meta: Dict, creators: List[Dict]) -> Dict:
    """Calculate campaign stats from creators and stored stats."""
    active = [c for c in creators if c.get("status", "active") != "removed"]
    live_posts = sum(int(to_number(c.get("posts_done", 0))) for c in active)
    # What we booked: the denominator for delivery. A bare "12 posts" says
    # nothing without knowing whether we paid for 12 or 40.
    posts_expected = sum(int(to_number(c.get("posts_owed", 0))) for c in active)

    stored = meta.get("stats", {})
    total_views = int(to_number(stored.get("total_views", 0)))

    budget_info = calc_budget(meta, creators)
    cpm = calc_cpm(budget_info["booked"], total_views)

    return {
        "live_posts": live_posts,
        "posts_expected": posts_expected,
        "total_views": total_views,
        "cpm": cpm,
    }
