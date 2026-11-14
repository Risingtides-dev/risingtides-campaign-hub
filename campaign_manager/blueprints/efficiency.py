"""Booking efficiency API endpoints — ROI analysis, creator valuation, pricing insights."""
import math
from typing import Optional

from flask import Blueprint, request, jsonify
from werkzeug.exceptions import BadRequest

from campaign_manager import db as _db
from campaign_manager.services.booking_efficiency import (
    generate_efficiency_report,
    calculate_creator_metrics,
    CreatorMetrics,
)

efficiency_bp = Blueprint("efficiency", __name__)


@efficiency_bp.get("/api/efficiency/report")
def get_efficiency_report():
    """Return booking efficiency for campaigns opened in the last 1-3650 days."""
    days = _analysis_days()

    session = _db.get_session()
    try:
        report = generate_efficiency_report(session, days=days)

        # Convert report to dict, handling dataclass conversion
        report_dict = {
            "report_date": report.report_date,
            "analysis_period_days": report.analysis_period_days,
            "total_creators_analyzed": report.total_creators_analyzed,
            "total_campaigns": report.total_campaigns,
            "total_spend": report.total_spend,
            "total_views": report.total_views,
            "total_engagement": report.total_engagement,
            "avg_roi": _num(report.avg_roi, 2),
            "median_roi": _num(report.median_roi, 2),
            "avg_cost_per_view": _num(report.avg_cost_per_view, 4),
            "avg_cost_per_engagement": _num(report.avg_cost_per_engagement, 2),
            "creators_by_tier": report.creators_by_tier,
            "efficiency_index": round(report.efficiency_index, 1),
            "top_performers": [
                _creator_metrics_to_dict(m) for m in report.top_performers
            ],
            "undervalued_deals": [
                _creator_metrics_to_dict(m) for m in report.undervalued_deals
            ],
            "overpriced_creators": [
                _creator_metrics_to_dict(m) for m in report.overpriced_creators
            ],
            "largest_efficiency_gaps": report.largest_efficiency_gaps,
        }

        return jsonify(report_dict)
    finally:
        session.close()


@efficiency_bp.get("/api/efficiency/creator/<username>")
def get_creator_efficiency(username: str):
    """Return ranked creator metrics; platform defaults to TikTok, independently of Instagram."""
    days = _analysis_days()

    session = _db.get_session()
    try:
        metrics = calculate_creator_metrics(session, username, days=days,
                                            platform=request.args.get("platform", "tiktok"))

        if not metrics:
            return jsonify({"error": f"No booking data found for {username}"}), 404

        return jsonify(_creator_metrics_to_dict(metrics))
    finally:
        session.close()


@efficiency_bp.get("/api/efficiency/leaderboard")
def get_creator_leaderboard():
    """Return the same ranked cohort, optionally filtered by tier and sort field."""
    days = _analysis_days()
    tier_filter = request.args.get("tier", None)
    limit = request.args.get("limit", 20, type=int)
    sort_by = request.args.get("sort", "roi_ratio")

    session = _db.get_session()
    try:
        report = generate_efficiency_report(session, days=days)

        # Build leaderboard grouped by tier
        leaderboard = {
            "report_date": report.report_date,
            "analysis_period_days": report.analysis_period_days,
            "elite": [],
            "high_value": [],
            "solid": [],
            "standard": [],
            "undervalued": [],
            "overpriced": [],
        }

        tier_to_list = {tier: leaderboard[tier] for tier in (
            "elite", "high_value", "solid", "standard", "undervalued", "overpriced",
        )}
        all_metrics = list(report.creators)

        # Sort by requested field
        sort_mapping = {
            "roi_ratio": lambda m: m.roi_ratio,
            "cost_per_view": lambda m: m.cost_per_view if m.cost_per_view != float('inf') else float('inf'),
            "engagement_rate": lambda m: m.engagement_rate,
            "avg_post_rate": lambda m: m.avg_post_rate,
        }
        if sort_by not in sort_mapping:
            sort_by = "roi_ratio"
        all_metrics.sort(key=sort_mapping[sort_by], reverse=sort_by in ("roi_ratio", "engagement_rate"))

        # Group by tier
        for creator in all_metrics:
            tier_key = creator.tier.value
            if tier_key in tier_to_list:
                if len(tier_to_list[tier_key]) < limit:
                    if not tier_filter or tier_filter == tier_key:
                        tier_to_list[tier_key].append(_creator_metrics_to_dict(creator))

        return jsonify(leaderboard)
    finally:
        session.close()


@efficiency_bp.get("/api/efficiency/insights")
def get_efficiency_insights():
    """Return measured pricing findings without unsupported future savings forecasts."""
    days = _analysis_days()

    session = _db.get_session()
    try:
        report = generate_efficiency_report(session, days=days)

        key_findings = []
        recommendations = []

        # Use the same disjoint, sign-checked price opportunities as the
        # report. Rank percentile alone never establishes a pricing premium.
        overpriced = report.overpriced_creators
        undervalued = report.undervalued_deals
        if overpriced:
            key_findings.append({
                "category": "pricing_opportunity",
                "severity": "high",
                "finding": f"{len(overpriced)} creators have rates >20% above their ROI cohort average",
                "creators": [_creator_label(m) for m in overpriced],
                "recommendation": "Review rates against similarly performing creators before rebooking",
            })
        if undervalued:
            key_findings.append({
                "category": "undervalued_opportunity",
                "severity": "medium",
                "finding": f"{len(undervalued)} creators have recorded views and rates >20% below their ROI cohort average",
                "creators": [_creator_label(m) for m in undervalued],
                "recommendation": "Review recent delivery and availability before increasing bookings",
            })

        top = report.top_performers[:5]
        top_spend = sum(m.total_spend for m in top)
        pct_of_total = top_spend / report.total_spend * 100 if report.total_spend > 0 else 0
        if top and any(m.total_views > 0 for m in top) and pct_of_total >= 50:
            key_findings.append({
                "category": "elite_concentration",
                "severity": "low",
                "finding": f"Top {len(top)} performers account for {pct_of_total:.1f}% of spend",
                "creators": [_creator_label(m) for m in top],
                "recommendation": "Review delivery dependency before concentrating more bookings",
            })

        # Recorded outcomes do not support the previous fixed 25% uplift and
        # 15% savings predictions. Keep the compatible recommendations list
        # empty until a defensible projection model exists.

        return jsonify(
            {
                "analysis_period_days": report.analysis_period_days,
                "efficiency_index": round(report.efficiency_index, 1),
                "key_findings": key_findings,
                "recommendations": recommendations,
            }
        )
    finally:
        session.close()


def _creator_label(metrics: CreatorMetrics) -> str:
    return (metrics.creator_username if metrics.platform == "tiktok"
            else f"{metrics.creator_username} ({metrics.platform})")


def _analysis_days() -> int:
    """Reject impossible windows before date arithmetic or database work."""
    try:
        days = int(request.args.get("days", "90"))
    except (TypeError, ValueError):
        raise BadRequest("days must be an integer between 1 and 3650")
    if not 1 <= days <= 3650:
        raise BadRequest("days must be an integer between 1 and 3650")
    return days


def _num(value: float, digits: int) -> Optional[float]:
    """Round for JSON output; non-finite values become None (JSON null).

    Creators with spend but zero views/engagement get
    ``float('inf')`` for cost_per_view / cost_per_engagement in
    booking_efficiency.py. Python's json serializer writes that as bare
    ``Infinity`` — which is NOT valid JSON, so the browser's
    ``JSON.parse`` throws and the whole Booking Efficiency tab dies
    with "Unexpected token 'I'". null is the honest wire value ("no
    meaningful unit cost"); the frontend renders it as an em dash.
    """
    if not math.isfinite(value):
        return None
    return round(value, digits)


def _creator_metrics_to_dict(metrics: CreatorMetrics) -> dict:
    """Convert CreatorMetrics dataclass to dict with rounded floats."""
    return {
        "creator_username": metrics.creator_username,
        "total_campaigns": metrics.total_campaigns,
        "total_bookings": metrics.total_bookings,
        "total_spend": _num(metrics.total_spend, 2),
        "total_views": metrics.total_views,
        "total_engagement": metrics.total_engagement,
        "roi_ratio": _num(metrics.roi_ratio, 2),
        "cost_per_view": _num(metrics.cost_per_view, 4),
        "cost_per_engagement": _num(metrics.cost_per_engagement, 2),
        "engagement_rate": _num(metrics.engagement_rate, 4),
        "avg_post_rate": _num(metrics.avg_post_rate, 2),
        "tier": metrics.tier.value,
        "pricing_gap_pct": _num(metrics.pricing_gap_pct, 1),
        "last_booked": metrics.last_booked,
        "platform": metrics.platform,
    }
