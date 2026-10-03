"""Booking efficiency optimization: ROI analysis, creator valuation, pricing insights."""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from campaign_manager.models import Campaign, Creator, MatchedVideo


class CreatorTier(str, Enum):
    """Creator performance tier based on ROI."""
    ELITE = "elite"              # Top 10% by ROI
    HIGH_VALUE = "high_value"    # 10-25% by ROI
    SOLID = "solid"              # 25-50% by ROI
    STANDARD = "standard"        # 50-75% by ROI
    UNDERVALUED = "undervalued"  # 75-90% by ROI (good deals)
    OVERPRICED = "overpriced"    # Bottom 10% by ROI


@dataclass
class CreatorMetrics:
    """Performance metrics for a single creator across their bookings."""
    creator_username: str
    total_campaigns: int
    total_bookings: int  # posts_owed across all campaigns
    total_spend: float
    total_views: int
    total_engagement: int  # likes only — MatchedVideo has no comments column

    # Calculated metrics
    roi_ratio: float  # views per dollar
    cost_per_view: float
    cost_per_engagement: float
    engagement_rate: float  # engagement / views
    avg_post_rate: float  # spend per post_owed

    # Valuation
    tier: CreatorTier
    pricing_gap_pct: float  # % above/below cohort average (positive = expensive)

    # Context
    last_booked: Optional[str]
    platform: str


@dataclass
class BookingEfficiencyReport:
    """Comprehensive booking efficiency analysis."""
    report_date: str
    analysis_period_days: int

    # Summary stats
    total_creators_analyzed: int
    total_campaigns: int
    total_spend: float
    total_views: int
    total_engagement: int

    # Aggregate metrics
    avg_roi: float  # avg views per dollar across all creators
    median_roi: float
    avg_cost_per_view: float
    avg_cost_per_engagement: float

    # Creator breakdown
    creators_by_tier: Dict[str, int]  # tier -> count
    top_performers: List[CreatorMetrics]
    undervalued_deals: List[CreatorMetrics]
    overpriced_creators: List[CreatorMetrics]

    # Insights
    efficiency_index: float  # 0-100 scale, higher = better ROI distribution
    largest_efficiency_gaps: List[Dict[str, Any]]  # creators with biggest price vs performance mismatches


def calculate_creator_metrics(
    session: Session,
    creator_username: str,
    days: int = 90,
) -> Optional[CreatorMetrics]:
    """
    Calculate comprehensive metrics for a single creator.

    Args:
        session: SQLAlchemy session
        creator_username: Creator's username
        days: Analysis window (default 90 days)

    Returns:
        CreatorMetrics or None if no campaigns found
    """
    cutoff_date = datetime.now() - timedelta(days=days)

    # Get all creator bookings in analysis window
    creators = session.query(Creator).filter(
        Creator.username == creator_username,
        Creator.campaign_id.in_(
            session.query(Campaign.id).filter(Campaign.created_at >= cutoff_date)
        )
    ).all()

    if not creators:
        return None

    # Aggregate metrics
    total_campaigns = len(set(c.campaign_id for c in creators))
    total_bookings = sum(c.posts_owed for c in creators)
    total_spend = sum(c.total_rate for c in creators)

    if total_spend == 0:
        return None

    # CAMP-85: attribute only THIS creator's posts, not every video across
    # their campaigns. The account is stored '@handle'; username is bare.
    # Without this filter a creator on a 50-creator campaign was credited with
    # all 51 creators' views — verified ~12x inflation for @theelliebarker
    # (5544 videos attributed vs 462 actually theirs), corrupting the tier
    # rankings this page drives budget decisions from.
    campaign_ids = [c.campaign_id for c in creators]
    norm = creator_username.lstrip("@").lower()
    videos = session.query(MatchedVideo).filter(
        and_(
            MatchedVideo.campaign_id.in_(campaign_ids),
            MatchedVideo.first_seen_at >= cutoff_date,
            func.lower(func.replace(MatchedVideo.account, "@", "")) == norm,
            MatchedVideo.dismissed_at.is_(None),  # exclude false-positive matches
        )
    ).all()

    total_views = sum(v.views for v in videos)
    # Engagement is likes-only: MatchedVideo has no comments column.
    total_engagement = sum(v.likes for v in videos)

    # No fabricated fallback (was: len(videos) * 50000). If a creator's matched
    # posts have 0 recorded views, report 0 — inventing 50k/post produced
    # phantom ROI and polluted the over/undervalued tiers.

    # Calculate derived metrics
    roi_ratio = total_views / total_spend if total_spend > 0 else 0
    cost_per_view = total_spend / total_views if total_views > 0 else float('inf')
    cost_per_engagement = total_spend / total_engagement if total_engagement > 0 else float('inf')
    engagement_rate = total_engagement / total_views if total_views > 0 else 0
    avg_post_rate = total_spend / total_bookings if total_bookings > 0 else 0

    # Get last booking date
    last_creator = max(creators, key=lambda c: c.campaign.created_at if c.campaign else datetime.min)
    last_booked = last_creator.campaign.created_at.isoformat() if last_creator.campaign else None

    # Determine platform (use most common)
    platform = max(set(c.platform for c in creators)) or "tiktok"

    return CreatorMetrics(
        creator_username=creator_username,
        total_campaigns=total_campaigns,
        total_bookings=total_bookings,
        total_spend=total_spend,
        total_views=total_views,
        total_engagement=total_engagement,
        roi_ratio=roi_ratio,
        cost_per_view=cost_per_view,
        cost_per_engagement=cost_per_engagement,
        engagement_rate=engagement_rate,
        avg_post_rate=avg_post_rate,
        tier=CreatorTier.SOLID,  # Will be recalculated during ranking
        pricing_gap_pct=0.0,  # Will be recalculated
        last_booked=last_booked,
        platform=platform,
    )


def rank_creators_by_efficiency(
    metrics_list: List[CreatorMetrics],
) -> List[CreatorMetrics]:
    """
    Rank creators by ROI and assign efficiency tiers.
    Calculate pricing gaps relative to tier averages.
    """
    if not metrics_list:
        return []

    # Sort by ROI (views per dollar)
    sorted_metrics = sorted(metrics_list, key=lambda m: m.roi_ratio, reverse=True)

    # Assign tiers by rank percentile. Each cutoff is the END index (exclusive)
    # of that tier's band, so the loop reads "idx < cutoff[T] => tier T".
    #
    # Review fix (CAMP-85): the old boundaries used ELITE=0 + int(n*0.1).
    # ELITE=0 meant `idx < 0` was NEVER true, so NOBODY was ever labeled ELITE;
    # and int(n*0.1)=0 for n<10 collapsed HIGH_VALUE too, dropping the top
    # performer straight to OVERPRICED. On a page that drives budget decisions,
    # the best creator could be flagged "overpriced." Now: cumulative cutoffs
    # via round(), each at least 1 past ELITE, so with >=1 creator the top one
    # is ELITE and tiers never invert.
    n = len(sorted_metrics)

    def _cut(pct: float) -> int:
        return min(n, max(1, round(n * pct)))

    elite_end = _cut(0.10)
    high_end = _cut(0.25)
    solid_end = _cut(0.50)
    standard_end = _cut(0.75)
    undervalued_end = _cut(0.90)

    # Assign tier to each creator (sorted best-first).
    result = []
    for idx, metrics in enumerate(sorted_metrics):
        if idx < elite_end:
            metrics.tier = CreatorTier.ELITE
        elif idx < high_end:
            metrics.tier = CreatorTier.HIGH_VALUE
        elif idx < solid_end:
            metrics.tier = CreatorTier.SOLID
        elif idx < standard_end:
            metrics.tier = CreatorTier.STANDARD
        elif idx < undervalued_end:
            metrics.tier = CreatorTier.UNDERVALUED
        else:
            metrics.tier = CreatorTier.OVERPRICED

        result.append(metrics)

    # Calculate pricing gaps (vs tier average)
    tier_avg_rates = {}
    for tier in CreatorTier:
        tier_creators = [m for m in result if m.tier == tier]
        if tier_creators:
            avg_rate = sum(m.avg_post_rate for m in tier_creators) / len(tier_creators)
            tier_avg_rates[tier] = avg_rate

    # Assign pricing gaps
    for metrics in result:
        tier_avg = tier_avg_rates.get(metrics.tier, metrics.avg_post_rate)
        if tier_avg > 0:
            metrics.pricing_gap_pct = ((metrics.avg_post_rate - tier_avg) / tier_avg) * 100
        else:
            metrics.pricing_gap_pct = 0.0

    return result


def generate_efficiency_report(
    session: Session,
    days: int = 90,
) -> BookingEfficiencyReport:
    """
    Generate comprehensive booking efficiency report.

    Args:
        session: SQLAlchemy session
        days: Analysis window (default 90 days)

    Returns:
        BookingEfficiencyReport with ranked creators and insights
    """
    cutoff_date = datetime.now() - timedelta(days=days)

    # Get all unique creators in analysis window
    all_creators = session.query(Creator).filter(
        Creator.campaign_id.in_(
            session.query(Campaign.id).filter(Campaign.created_at >= cutoff_date)
        )
    ).all()

    unique_usernames = set(c.username for c in all_creators)

    # Calculate metrics for each creator
    all_metrics = []
    for username in unique_usernames:
        metrics = calculate_creator_metrics(session, username, days)
        if metrics:
            all_metrics.append(metrics)

    # Rank and tier
    ranked = rank_creators_by_efficiency(all_metrics)

    # Aggregate stats
    total_spend = sum(m.total_spend for m in ranked)
    total_views = sum(m.total_views for m in ranked)
    total_engagement = sum(m.total_engagement for m in ranked)

    avg_roi = sum(m.roi_ratio for m in ranked) / len(ranked) if ranked else 0
    sorted_rois = sorted([m.roi_ratio for m in ranked])
    median_roi = sorted_rois[len(sorted_rois) // 2] if sorted_rois else 0

    # Averages over the finite entries only — `if ranked` alone isn't enough:
    # when EVERY creator has inf unit cost (spend but zero tracked views,
    # e.g. a fresh window before any scrape), the filtered list is empty and
    # the old expression raised ZeroDivisionError.
    finite_cpv = [m.cost_per_view for m in ranked if m.cost_per_view != float('inf')]
    finite_cpe = [m.cost_per_engagement for m in ranked if m.cost_per_engagement != float('inf')]
    avg_cost_per_view = sum(finite_cpv) / len(finite_cpv) if finite_cpv else 0
    avg_cost_per_engagement = sum(finite_cpe) / len(finite_cpe) if finite_cpe else 0

    # Tier distribution
    creators_by_tier = {}
    for tier in CreatorTier:
        count = len([m for m in ranked if m.tier == tier])
        creators_by_tier[tier.value] = count

    # Top performers (elite + high value)
    top_performers = [m for m in ranked if m.tier in (CreatorTier.ELITE, CreatorTier.HIGH_VALUE)][:10]

    # Undervalued deals (high tier performance at low cost)
    undervalued = [m for m in ranked if m.tier == CreatorTier.UNDERVALUED][:10]

    # Overpriced (low tier performance at high cost)
    overpriced = [m for m in ranked if m.tier == CreatorTier.OVERPRICED][:10]

    # Efficiency index (0-100, higher = better)
    # Measures how well pricing aligns with performance
    pricing_gaps = [abs(m.pricing_gap_pct) for m in ranked]
    avg_gap = sum(pricing_gaps) / len(pricing_gaps) if pricing_gaps else 0
    efficiency_index = max(0, 100 - (avg_gap / 2))  # Penalize misalignment

    # Largest efficiency gaps
    sorted_by_gap = sorted(ranked, key=lambda m: abs(m.pricing_gap_pct), reverse=True)
    largest_gaps = [
        {
            "username": m.creator_username,
            "tier": m.tier.value,
            "pricing_gap_pct": round(m.pricing_gap_pct, 1),
            "avg_post_rate": round(m.avg_post_rate, 2),
            "roi_ratio": round(m.roi_ratio, 2),
        }
        for m in sorted_by_gap[:10]
    ]

    return BookingEfficiencyReport(
        report_date=datetime.now().isoformat(),
        analysis_period_days=days,
        total_creators_analyzed=len(ranked),
        total_campaigns=len(session.query(Campaign).filter(Campaign.created_at >= cutoff_date).all()),
        total_spend=total_spend,
        total_views=total_views,
        total_engagement=total_engagement,
        avg_roi=avg_roi,
        median_roi=median_roi,
        avg_cost_per_view=avg_cost_per_view,
        avg_cost_per_engagement=avg_cost_per_engagement,
        creators_by_tier=creators_by_tier,
        top_performers=top_performers,
        undervalued_deals=undervalued,
        overpriced_creators=overpriced,
        efficiency_index=efficiency_index,
        largest_efficiency_gaps=largest_gaps,
    )
