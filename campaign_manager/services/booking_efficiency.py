"""Booking efficiency optimization: ROI analysis, creator valuation, pricing insights."""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from statistics import median

from sqlalchemy.orm import Session

from campaign_manager.models import Campaign, Creator, MatchedVideo
from campaign_manager.services.creator_library import normalize_username
from campaign_manager.utils.helpers import build_round_end_by_slug, video_in_round


class CreatorTier(str, Enum):
    """Creator performance tier based on ROI."""
    ELITE = "elite"              # Top 10% by ROI
    HIGH_VALUE = "high_value"    # 10-25% by ROI
    SOLID = "solid"              # 25-50% by ROI
    STANDARD = "standard"        # 50-75% by ROI
    UNDERVALUED = "undervalued"  # Legacy wire name: 75-90% by ROI
    OVERPRICED = "overpriced"    # Legacy wire name: bottom 10% by ROI


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
    # Full ranked cohort shared by report, leaderboard, single-creator and insights.
    creators: List[CreatorMetrics] = field(default_factory=list)


def _platform(value: str) -> str:
    return str(value or "tiktok").strip().lower() or "tiktok"


def calculate_cohort_metrics(session: Session, days: int = 90) -> List[CreatorMetrics]:
    """Paid bookings on campaigns created in the last ``days`` days.

    Outcomes are the campaign's eligible stored posts, regardless of when a
    scraper first observed them. ``first_seen_at`` is an ingestion timestamp,
    not a booking or publication date. All campaigns (including completed or
    older successors) participate in the round ownership calculation.
    """
    cutoff_date = datetime.now() - timedelta(days=days)
    campaigns = session.query(Campaign).all()
    by_id = {campaign.id: campaign for campaign in campaigns}
    round_ends = build_round_end_by_slug(c.to_meta_dict() for c in campaigns)
    creators = session.query(Creator).join(Campaign).filter(
        Campaign.created_at >= cutoff_date,
    ).all()
    if not creators:
        return []

    bookings = {}
    for creator in creators:
        identity = (normalize_username(creator.username), _platform(creator.platform))
        if identity[0]:
            bookings.setdefault(identity, []).append(creator)

    campaign_ids = {creator.campaign_id for creator in creators}
    videos_by_booking = {}
    videos = session.query(MatchedVideo).filter(
        MatchedVideo.campaign_id.in_(campaign_ids),
        MatchedVideo.dismissed_at.is_(None),
    ).all()
    for video in videos:
        campaign = by_id[video.campaign_id]
        if not video_in_round(video.to_dict(), campaign.start_date,
                              end_date=round_ends.get(campaign.slug), exclude_dismissed=True):
            continue
        key = (normalize_username(video.account), _platform(video.platform), video.campaign_id)
        videos_by_booking.setdefault(key, []).append(video)

    result = []
    for (username, platform), rows in sorted(bookings.items()):
        total_spend = sum(row.total_rate or 0 for row in rows)
        if total_spend <= 0:
            continue
        total_bookings = sum(row.posts_owed or 0 for row in rows)
        owned_campaigns = {row.campaign_id for row in rows}
        # One query result per stored post, even when legacy booking aliases
        # normalize to the same creator on the same campaign.
        posts = [video for campaign_id in owned_campaigns
                 for video in videos_by_booking.get((username, platform, campaign_id), [])]
        total_views = sum(video.views or 0 for video in posts)
        total_engagement = sum(video.likes or 0 for video in posts)
        last_booked = max((by_id[campaign_id].created_at for campaign_id in owned_campaigns
                           if by_id[campaign_id].created_at is not None), default=None)
        result.append(CreatorMetrics(
            creator_username=username,
            total_campaigns=len(owned_campaigns),
            total_bookings=total_bookings,
            total_spend=total_spend,
            total_views=total_views,
            total_engagement=total_engagement,
            roi_ratio=total_views / total_spend,
            cost_per_view=total_spend / total_views if total_views > 0 else float("inf"),
            cost_per_engagement=total_spend / total_engagement if total_engagement > 0 else float("inf"),
            engagement_rate=total_engagement / total_views if total_views > 0 else 0,
            avg_post_rate=total_spend / total_bookings if total_bookings > 0 else 0,
            tier=CreatorTier.SOLID,
            pricing_gap_pct=0.0,
            last_booked=last_booked.isoformat() if last_booked is not None else None,
            platform=platform,
        ))
    return result


def calculate_creator_metrics(
    session: Session,
    creator_username: str,
    days: int = 90,
    platform: str = "tiktok",
) -> Optional[CreatorMetrics]:
    """Find a normalized, platform-specific creator in the ranked cohort."""
    identity = (normalize_username(creator_username), _platform(platform))
    ranked = rank_creators_by_efficiency(calculate_cohort_metrics(session, days))
    return next((row for row in ranked
                 if (row.creator_username, row.platform) == identity), None)


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

    # Compare rates only within the same platform and ROI band. A TikTok
    # booking and an Instagram booking are different rate markets.
    rates_by_cohort = {}
    for metrics in result:
        if metrics.total_bookings > 0:
            rates_by_cohort.setdefault((metrics.tier, metrics.platform), []).append(metrics.avg_post_rate)
    for metrics in result:
        cohort_rates = rates_by_cohort.get((metrics.tier, metrics.platform), [])
        cohort_average = sum(cohort_rates) / len(cohort_rates) if cohort_rates else 0
        metrics.pricing_gap_pct = (
            (metrics.avg_post_rate - cohort_average) / cohort_average * 100
            if cohort_average > 0 and metrics.total_bookings > 0 else 0.0
        )

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

    # Compute once so every reader uses the same identities and attribution.
    ranked = rank_creators_by_efficiency(calculate_cohort_metrics(session, days))

    # Aggregate stats
    total_spend = sum(m.total_spend for m in ranked)
    total_views = sum(m.total_views for m in ranked)
    total_engagement = sum(m.total_engagement for m in ranked)

    avg_roi = sum(m.roi_ratio for m in ranked) / len(ranked) if ranked else 0
    median_roi = median(m.roi_ratio for m in ranked) if ranked else 0

    # Averages over the finite entries only — `if ranked` alone isn't enough:
    # when EVERY creator has inf unit cost (spend but zero tracked views,
    # e.g. a fresh window before any scrape), the filtered list is empty and
    # the old expression raised ZeroDivisionError.
    finite_cpv = [m.cost_per_view for m in ranked if m.cost_per_view != float('inf')]
    finite_cpe = [m.cost_per_engagement for m in ranked if m.cost_per_engagement != float('inf')]
    no_unit_cost = float("inf") if ranked else 0
    avg_cost_per_view = sum(finite_cpv) / len(finite_cpv) if finite_cpv else no_unit_cost
    avg_cost_per_engagement = sum(finite_cpe) / len(finite_cpe) if finite_cpe else no_unit_cost

    # Tier distribution
    creators_by_tier = {}
    for tier in CreatorTier:
        count = len([m for m in ranked if m.tier == tier])
        creators_by_tier[tier.value] = count

    # Top performers (elite + high value)
    top_performers = [m for m in ranked if m.tier in (CreatorTier.ELITE, CreatorTier.HIGH_VALUE)][:10]

    # ROI percentile labels alone do not prove a discount or premium. A
    # pricing opportunity must have the corresponding measured gap; keep the
    # two lists disjoint and never call zero recorded delivery a proven deal.
    undervalued = [m for m in ranked if m.pricing_gap_pct < -20 and m.total_views > 0][:10]
    overpriced = [m for m in ranked if m.pricing_gap_pct > 20][:10]

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
            "platform": m.platform,
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
        creators=ranked,
    )
