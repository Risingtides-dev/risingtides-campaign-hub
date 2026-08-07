"""Booking efficiency API endpoints — ROI analysis, creator valuation, pricing insights."""
import math
from typing import Optional

from flask import Blueprint, request, jsonify
from sqlalchemy.orm import Session

from campaign_manager import db as _db
from campaign_manager.services.booking_efficiency import (
    generate_efficiency_report,
    calculate_creator_metrics,
    CreatorMetrics,
)

efficiency_bp = Blueprint("efficiency", __name__)


@efficiency_bp.get("/api/efficiency/report")
def get_efficiency_report():
    """
    Get comprehensive booking efficiency report.

    Query params:
        - days: Analysis window in days (default 90)

    Returns:
        {
            "report_date": "2026-06-05T...",
            "analysis_period_days": 90,
            "total_creators_analyzed": 45,
            "total_campaigns": 12,
            "total_spend": 125000.0,
            "total_views": 5200000,
            "total_engagement": 320000,
            "avg_roi": 41600.0,
            "median_roi": 38000.0,
            "avg_cost_per_view": 0.024,
            "avg_cost_per_engagement": 0.39,
            "creators_by_tier": {
                "elite": 4,
                "high_value": 9,
                "solid": 11,
                "standard": 11,
                "undervalued": 5,
                "overpriced": 5
            },
            "top_performers": [...],
            "undervalued_deals": [...],
            "overpriced_creators": [...],
            "efficiency_index": 78.5,
            "largest_efficiency_gaps": [...]
        }
    """
    days = request.args.get("days", 90, type=int)

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
    """
    Get efficiency metrics for a single creator.

    Query params:
        - days: Analysis window in days (default 90)

    Returns:
        {
            "creator_username": "influencer123",
            "total_campaigns": 5,
            "total_bookings": 12,
            "total_spend": 8500.0,
            "total_views": 425000,
            "total_engagement": 28000,
            "roi_ratio": 50000.0,
            "cost_per_view": 0.02,
            "cost_per_engagement": 0.304,
            "engagement_rate": 0.066,
            "avg_post_rate": 708.33,
            "tier": "high_value",
            "pricing_gap_pct": -5.2,
            "last_booked": "2026-05-15T...",
            "platform": "tiktok"
        }
    """
    days = request.args.get("days", 90, type=int)

    session = _db.get_session()
    try:
        metrics = calculate_creator_metrics(session, username, days=days)

        if not metrics:
            return jsonify({"error": f"No booking data found for {username}"}), 404

        return jsonify(_creator_metrics_to_dict(metrics))
    finally:
        session.close()


@efficiency_bp.get("/api/efficiency/leaderboard")
def get_creator_leaderboard():
    """
    Get ranked leaderboard of creators by efficiency tier.

    Query params:
        - days: Analysis window in days (default 90)
        - tier: Filter by tier (elite, high_value, solid, standard, undervalued, overpriced)
        - limit: Max creators per tier (default 20)
        - sort: Sort field (roi_ratio, cost_per_view, engagement_rate, avg_post_rate)

    Returns:
        {
            "report_date": "2026-06-05T...",
            "analysis_period_days": 90,
            "elite": [
                {...creator...},
                {...creator...}
            ],
            "high_value": [...],
            "solid": [...],
            "standard": [...],
            "undervalued": [...],
            "overpriced": [...]
        }
    """
    days = request.args.get("days", 90, type=int)
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

        # Group all creators by tier
        all_creators = (
            report.top_performers
            + report.undervalued_deals
            + report.overpriced_creators
        )

        # Add any remaining creators (from original report generation)
        tier_to_list = {
            "elite": leaderboard["elite"],
            "high_value": leaderboard["high_value"],
            "solid": leaderboard["solid"],
            "standard": leaderboard["standard"],
            "undervalued": leaderboard["undervalued"],
            "overpriced": leaderboard["overpriced"],
        }

        # Re-fetch full list for complete leaderboard
        from campaign_manager.services.booking_efficiency import (
            calculate_creator_metrics,
            rank_creators_by_efficiency,
        )
        from campaign_manager.models import Creator, Campaign
        from datetime import datetime, timedelta

        cutoff_date = datetime.now() - timedelta(days=days)
        all_db_creators = session.query(Creator).filter(
            Creator.campaign_id.in_(
                session.query(Campaign.id).filter(Campaign.created_at >= cutoff_date)
            )
        ).all()
        unique_usernames = set(c.username for c in all_db_creators)
        all_metrics = [
            m
            for m in [
                calculate_creator_metrics(session, username, days)
                for username in unique_usernames
            ]
            if m
        ]
        all_metrics = rank_creators_by_efficiency(all_metrics)

        # Sort by requested field
        sort_mapping = {
            "roi_ratio": lambda m: m.roi_ratio,
            "cost_per_view": lambda m: m.cost_per_view if m.cost_per_view != float('inf') else float('inf'),
            "engagement_rate": lambda m: m.engagement_rate,
            "avg_post_rate": lambda m: m.avg_post_rate,
        }
        sort_func = sort_mapping.get(sort_by, sort_mapping["roi_ratio"])
        all_metrics.sort(key=sort_func, reverse=(sort_by == "roi_ratio"))

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
    """
    Get AI-ready insights for booking optimization.

    Query params:
        - days: Analysis window in days (default 90)

    Returns:
        {
            "analysis_period_days": 90,
            "key_findings": [
                {
                    "category": "pricing_opportunity",
                    "severity": "high",
                    "finding": "5 creators are overpriced by >20% vs tier average",
                    "creators": ["user1", "user2", ...],
                    "recommendation": "Renegotiate rates or reallocate budget to similar creators at lower rates"
                },
                ...
            ],
            "recommendations": [
                {
                    "action": "reallocate_budget",
                    "from": ["overpriced_user1"],
                    "to": ["undervalued_user1"],
                    "potential_uplift_views": 250000,
                    "projected_savings": 5000.0
                }
            ]
        }
    """
    days = request.args.get("days", 90, type=int)

    session = _db.get_session()
    try:
        report = generate_efficiency_report(session, days=days)

        key_findings = []
        recommendations = []

        # Finding 1: Pricing misalignment
        high_gap_creators = [
            m
            for m in (
                report.top_performers
                + report.undervalued_deals
                + report.overpriced_creators
            )
            if abs(m.pricing_gap_pct) > 20
        ]
        if high_gap_creators:
            overpriced = [m for m in high_gap_creators if m.pricing_gap_pct > 20]
            if overpriced:
                key_findings.append(
                    {
                        "category": "pricing_opportunity",
                        "severity": "high",
                        "finding": f"{len(overpriced)} creators are overpriced by >20% vs tier average",
                        "creators": [m.creator_username for m in overpriced],
                        "recommendation": "Renegotiate rates or reallocate budget to similar performers at lower rates",
                    }
                )

        # Finding 2: Undervalued opportunities
        if report.undervalued_deals:
            key_findings.append(
                {
                    "category": "undervalued_opportunity",
                    "severity": "medium",
                    "finding": f"{len(report.undervalued_deals)} creators deliver solid ROI at discounted rates",
                    "creators": [m.creator_username for m in report.undervalued_deals],
                    "recommendation": "Increase bookings with these creators before market adjusts pricing",
                }
            )

        # Finding 3: Elite performer concentration
        if report.top_performers:
            top_5_spend = sum(m.total_spend for m in report.top_performers[:5])
            pct_of_total = (top_5_spend / report.total_spend * 100) if report.total_spend > 0 else 0
            key_findings.append(
                {
                    "category": "elite_concentration",
                    "severity": "low",
                    "finding": f"Top 5 elite creators account for {pct_of_total:.1f}% of spend",
                    "creators": [m.creator_username for m in report.top_performers[:5]],
                    "recommendation": "Consider spreading bookings to reduce dependency on single creators",
                }
            )

        # Recommendation: Reallocation strategy
        overpriced = report.overpriced_creators
        undervalued = report.undervalued_deals
        if overpriced and undervalued:
            overpriced_spend = sum(m.total_spend for m in overpriced[:3])
            potential_views = sum(m.total_views for m in undervalued[:3])
            recommendations.append(
                {
                    "action": "reallocate_budget",
                    "from": [m.creator_username for m in overpriced[:3]],
                    "to": [m.creator_username for m in undervalued[:3]],
                    "potential_uplift_views": int(potential_views * 0.25),  # Conservative 25% uplift
                    "projected_savings": round(overpriced_spend * 0.15, 2),  # 15% savings
                }
            )

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
