"""Creator Intelligence — sound-breaking analytics from real matched-video data.

This is NOT generic influencer scoring (follower counts / engagement rate).
It answers the question that actually matters for sound-based UGC campaigns:
**who breaks sounds** — who reliably drives a sound's video to high velocity,
how early in a sound's lifecycle they post, and how that translates to outcomes.

All metrics derive from `matched_videos` (per-post views + upload date +
extracted_sound_id) joined to `campaigns` (sound_id + start_date). No external
calls; pure DB aggregation over data we already scrape.

Three ranking lenses (the caller picks):
  - ceiling:  rewards viral hit-rate — high-odds breakers even at low volume
  - volume:   rewards proven track record at scale + sound diversity
  - balanced: confidence-dampened composite (default), real ceiling wins but
              a tiny lucky sample can't dominate
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from math import sqrt
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from campaign_manager.models import Campaign, Creator, MatchedVideo
from campaign_manager.services.creator_library import normalize_username
from campaign_manager.utils.helpers import build_round_end_by_slug, video_in_round

logger = logging.getLogger(__name__)

# A post is "viral" at/above this view count (the breakout threshold).
VIRAL_THRESHOLD = 500_000
MILLION = 1_000_000
# Minimum tracked posts before a creator qualifies for the leaderboard.
MIN_POSTS = 5

Lens = str  # "ceiling" | "volume" | "balanced"


def _tiktok(column):
    return func.lower(func.coalesce(func.nullif(func.trim(column), ""), "tiktok")) == "tiktok"


@dataclass
class BreakerRow:
    """One creator's sound-breaking scorecard."""
    account: str
    posts: int
    avg_views: int
    median_views: int
    peak_views: int
    viral_rate: float        # % of posts >= VIRAL_THRESHOLD
    millionaires: int        # posts >= 1M
    distinct_sounds: int
    total_views: int
    # the three lens scores (0-100ish), so the UI can re-rank client-side too
    score_ceiling: float
    score_volume: float
    score_balanced: float


def _median(values: List[int]) -> int:
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) // 2


def _score_ceiling(viral_rate: float, avg_views: float) -> float:
    """Viral hit-rate dominant; avg velocity as a minor booster."""
    return round(viral_rate * 0.7 + min(avg_views / 10_000, 100) * 0.3, 1)


def _score_volume(millionaires: int, posts: int, sounds: int) -> float:
    """Proven scale: capped millionaire credit + post volume + sound diversity."""
    return round(min(millionaires * 4, 60) + min(posts / 10.0, 20) + min(sounds / 5.0, 20), 1)


def _score_balanced(viral_rate: float, avg_views: float, posts: int, sounds: int) -> float:
    """Confidence-dampened composite (the default lens).

    The (1 - 1/sqrt(posts)) term shrinks the velocity contribution for small
    samples so a 5-post fluke can't outrank a proven breaker, while a genuinely
    elite low-volume creator still surfaces near the top.
    """
    confidence = 1 - 1.0 / sqrt(posts)
    return round(
        viral_rate * 0.4
        + min(avg_views / 8_000, 100) * 0.3 * confidence
        + min(sounds * 2, 40) * 0.3,
        1,
    )


def _eligible_posts(session: Session, campaigns=None):
    """One round-qualified, deduplicated TikTok cohort per analysis request."""
    if campaigns is None:
        campaigns = session.query(Campaign).all()
    by_id = {camp.id: camp for camp in campaigns}
    round_ends = build_round_end_by_slug(camp.to_meta_dict() for camp in campaigns)
    rows = session.query(MatchedVideo).filter(
        MatchedVideo.dismissed_at.is_(None),
        MatchedVideo.views > 0,
        _tiktok(MatchedVideo.platform),
    ).all()
    unique = {}
    for video in rows:
        camp = by_id.get(video.campaign_id)
        account = normalize_username(video.account)
        if camp is None or not account or not video_in_round(
            video.to_dict(), camp.start_date,
            end_date=round_ends.get(camp.slug), exclude_dismissed=True,
        ):
            continue
        # Historical imports can store one physical post on several campaigns.
        # Keep empty-URL rows separate, and prefer the newest eligible campaign
        # deterministically when legacy undated campaigns overlap.
        identity = (account, video.url) if video.url else (account, video.id)
        previous = unique.get(identity)
        order = (camp.created_at or datetime.min, camp.slug, video.id)
        if previous is None or order > previous[0]:
            unique[identity] = (order, video, camp)
    return [(video, camp) for _, video, camp in unique.values()]


def _sound_id(video, camp):
    return video.extracted_sound_id or video.music_id or camp.sound_id or "unknown"


def breaker_leaderboard(
    session: Session,
    lens: Lens = "balanced",
    limit: Optional[int] = 100,
    min_posts: int = MIN_POSTS,
    *,
    _posts=None,
) -> List[Dict[str, Any]]:
    """Rank normalized TikTok creators over their eligible distinct posts."""
    posts = _eligible_posts(session) if _posts is None else _posts
    buckets = {}
    for video, camp in posts:
        buckets.setdefault(normalize_username(video.account), []).append((video, camp))
    result = []
    for account, rows in buckets.items():
        if len(rows) < max(1, min_posts):
            continue
        views = [int(video.views or 0) for video, _ in rows]
        count = len(views)
        avg_views = sum(views) / count
        viral_rate = round(100.0 * sum(v >= VIRAL_THRESHOLD for v in views) / count, 1)
        sounds = len({_sound_id(video, camp) for video, camp in rows} - {"unknown"})
        millionaires = sum(v >= MILLION for v in views)
        result.append(BreakerRow(
            account=f"@{account}", posts=count, avg_views=round(avg_views),
            median_views=_median(views), peak_views=max(views), viral_rate=viral_rate,
            millionaires=millionaires, distinct_sounds=sounds, total_views=sum(views),
            score_ceiling=_score_ceiling(viral_rate, avg_views),
            score_volume=_score_volume(millionaires, count, sounds),
            score_balanced=_score_balanced(viral_rate, avg_views, count, sounds),
        ))
    score = {"ceiling": "score_ceiling", "volume": "score_volume"}.get(lens, "score_balanced")
    result.sort(key=lambda row: (-getattr(row, score), row.account))
    return [asdict(row) for row in result[:limit]]


def rebook_suggestions(
    session: Session,
    limit: int = 25,
    min_posts: int = MIN_POSTS,
) -> List[Dict[str, Any]]:
    """Surface proven breakers who are UNDER-BOOKED — high sound-breaking
    score but few recent bookings and/or open capacity. The "who should we
    re-book?" list (CAMP-87).

    Pure DB aggregation over matched_videos (performance) + creators
    (booking history). No follower history, no new scrape.
    """
    from datetime import datetime

    # 1. Proven breakers, ranked by balanced score.
    breakers = breaker_leaderboard(session, lens="balanced", limit=200, min_posts=min_posts)
    if not breakers:
        return []

    # 2. Booking history per creator: how many campaigns, posts owed vs done,
    #    and when they were last booked (Campaign.created_at).
    booking_rows = session.query(Creator, Campaign).join(
        Campaign, Campaign.id == Creator.campaign_id,
    ).filter(Creator.status != "removed", _tiktok(Creator.platform)).all()
    booking_by_user = {}
    for creator, camp in booking_rows:
        key = normalize_username(creator.username)
        booking = booking_by_user.setdefault(key, {
            "campaigns": set(), "posts_owed": 0, "posts_done": 0, "last_booked": None,
        })
        booking["campaigns"].add(camp.id)
        booking["posts_owed"] += creator.posts_owed or 0
        booking["posts_done"] += creator.posts_done or 0
        if camp.created_at is not None and (
            booking["last_booked"] is None or camp.created_at > booking["last_booked"]
        ):
            booking["last_booked"] = camp.created_at

    now = datetime.now()
    suggestions: List[Dict[str, Any]] = []
    for b in breakers:
        key = normalize_username(b["account"])
        bk = booking_by_user.get(key)
        campaigns_booked = len(bk["campaigns"]) if bk else 0
        posts_owed = int(bk["posts_owed"]) if bk else 0
        posts_done = int(bk["posts_done"]) if bk else 0
        last_booked = bk["last_booked"] if bk else None
        days_since = (now - last_booked).days if last_booked else None
        # Reliability: did they deliver what they owed? (caps at 1.0)
        repeat_rate = round(min(posts_done / posts_owed, 1.0), 2) if posts_owed else 0.0

        # Under-booked = proven (good breaker score) but light booking footprint
        # or gone cold. Score the OPPORTUNITY: high breaker score, low bookings,
        # long since last booked, reliable when booked.
        breaker_score = b["score_balanced"]
        recency_boost = min((days_since if days_since is not None else 365) / 90.0, 2.0)
        scarcity_boost = 2.0 if campaigns_booked <= 2 else (1.0 if campaigns_booked <= 5 else 0.4)
        opportunity = round(breaker_score * (0.5 + 0.25 * recency_boost + 0.25 * scarcity_boost) * (0.6 + 0.4 * repeat_rate), 1)

        suggestions.append({
            "account": b["account"],
            "breaker_score": breaker_score,
            "viral_rate": b["viral_rate"],
            "avg_views": b["avg_views"],
            "millionaires": b["millionaires"],
            "campaigns_booked": campaigns_booked,
            "posts_owed": posts_owed,
            "posts_done": posts_done,
            "repeat_rate": repeat_rate,
            "days_since_booked": days_since,
            "opportunity_score": opportunity,
        })

    # Rank by opportunity; the best re-book targets float up.
    suggestions.sort(key=lambda s: s["opportunity_score"], reverse=True)
    return suggestions[:limit]


def creator_drilldown(
    session: Session, account: str, with_outcomes: bool = False
) -> Optional[Dict[str, Any]]:
    """Full sound-breaking story for one creator.

    Returns sound-by-sound performance, the velocity distribution, and
    lifecycle timing (how early in each campaign's life they posted —
    early adoption is the gold signal for sound-breakers).

    When `with_outcomes` is set, also pulls per-creator Cobrand outcome data
    (shares + comments — the sound-spread signal labels care about) from the
    campaigns this creator appears in. This is a slower network call, so it's
    opt-in.
    """
    key = normalize_username(account)
    if not key:
        return None
    norm = f"@{key}"

    videos = [(video, camp) for video, camp in _eligible_posts(session)
              if normalize_username(video.account) == key]
    if not videos:
        return None

    all_views = [int(v.views or 0) for v, _ in videos]
    posts = len(all_views)
    viral = sum(1 for x in all_views if x >= VIRAL_THRESHOLD)
    millionaires = sum(1 for x in all_views if x >= MILLION)

    # Per-sound rollup, with lifecycle timing vs the campaign start_date.
    sounds: Dict[tuple, Dict[str, Any]] = {}
    for v, camp in videos:
        sid = _sound_id(v, camp)
        bucket = sounds.setdefault(
            (sid, camp.slug),
            {
                "sound_id": sid,
                "sound_title": v.extracted_song_title or camp.song or "",
                "artist": camp.artist or "",
                "campaign_slug": camp.slug,
                "posts": 0,
                "total_views": 0,
                "peak_views": 0,
                "days_after_start": None,
            },
        )
        bucket["posts"] += 1
        bucket["total_views"] += int(v.views or 0)
        bucket["peak_views"] = max(bucket["peak_views"], int(v.views or 0))
        days = _days_after_start(v.upload_date, camp.start_date)
        if days is not None:
            prev = bucket["days_after_start"]
            bucket["days_after_start"] = days if prev is None else min(prev, days)

    sound_list = sorted(sounds.values(), key=lambda s: s["peak_views"], reverse=True)
    distinct_sounds = len({s["sound_id"] for s in sound_list} - {"unknown"})
    for s in sound_list:
        d = s["days_after_start"]
        # "scout" = posted before the campaign officially started (on the sound
        # early, ahead of the booking) — the strongest sound-breaker signal.
        s["timing"] = (
            "scout" if (d is not None and d < 0)
            else "early" if (d is not None and d <= 5)
            else "late" if (d is not None and d > 14)
            else "mid" if d is not None else "unknown"
        )

    result = {
        "account": norm,
        "posts": posts,
        "avg_views": round(sum(all_views) / posts),
        "median_views": _median(all_views),
        "peak_views": max(all_views),
        "viral_rate": round(100.0 * viral / posts, 1),
        "millionaires": millionaires,
        "distinct_sounds": distinct_sounds,
        "early_adopter_rate": round(
            100.0 * len({s["sound_id"] for s in sound_list if s["sound_id"] != "unknown" and s["timing"] in ("scout", "early")}) / distinct_sounds, 1
        ) if distinct_sounds else 0.0,
        "sounds": sound_list,
        "view_distribution": _distribution(all_views),
        "score_balanced": _score_balanced(
            round(100.0 * viral / posts, 1),
            sum(all_views) / posts,
            posts,
            distinct_sounds,
        ),
        "outcomes": None,
    }

    if with_outcomes:
        result["outcomes"] = _aggregate_outcomes(session, norm)

    return result


def _aggregate_outcomes(session: Session, account: str) -> Optional[Dict[str, Any]]:
    """Sum Cobrand per-creator outcomes (shares/comments) across ALL campaigns
    that expose Cobrand data.

    Important: Cobrand submissions are independent of our scraper's
    matched_videos — a creator can have a tracked Cobrand submission on a
    campaign where our matcher never linked their post. So we check every
    campaign with a share URL (only a handful), not just matched ones.
    Returns None if the creator has no reachable Cobrand submissions.
    """
    from campaign_manager.services.cobrand_outcomes import creator_outcomes

    share_urls = [
        url for (url,) in
        session.query(Campaign.cobrand_share_url)
        .filter(Campaign.cobrand_share_url != "")
        .distinct()
        .all()
    ]

    # CAMP-66: resolve outcomes across all share-url campaigns in parallel.
    # Each creator_outcomes() call hits fetch_submissions() which is now cached
    # per share_url, so warm dossiers are instant; the cold case fans out the
    # ~10 fetches concurrently instead of running them one at a time.
    from concurrent.futures import ThreadPoolExecutor
    def _safe_outcomes(u: str):
        # Per-campaign isolation: the outcome layer is enrichment, so one
        # campaign's malformed Cobrand response must degrade (skip it), never
        # propagate up ex.map() and 500 the whole creator drilldown.
        try:
            return creator_outcomes(u, account)
        except Exception:
            logger.debug("creator_outcomes failed for a share url", exc_info=True)
            return None

    totals: Dict[str, Any] = {"views": 0, "likes": 0, "comments": 0, "shares": 0, "posts": 0, "campaigns": 0}
    follower_count = 0
    avatar_url = ""
    found = False
    with ThreadPoolExecutor(max_workers=min(8, len(share_urls) or 1)) as ex:
        for oc in ex.map(_safe_outcomes, share_urls):
            if not oc:
                continue
            found = True
            totals["campaigns"] += 1
            for k in ("views", "likes", "comments", "shares", "posts"):
                totals[k] += oc.get(k, 0)
            # follower_count is a per-creator attribute, not additive — take the
            # max across campaigns (their peak/most-recent follower count).
            follower_count = max(follower_count, oc.get("follower_count", 0))
            # CAMP-76: first non-empty avatar (PFP) across campaigns.
            if not avatar_url and oc.get("avatar_url"):
                avatar_url = oc["avatar_url"]

    if not found:
        return None

    totals["follower_count"] = follower_count
    totals["avatar_url"] = avatar_url
    # CAMP-86: reach efficiency — shares per 1k followers. The cheap signal
    # the follower number unlocks (how much spread per unit of audience).
    totals["shares_per_1k_followers"] = round(
        totals["shares"] / follower_count * 1000, 1
    ) if follower_count else 0.0

    tv = totals["views"]
    totals["engagement_rate"] = round(
        (totals["likes"] + totals["comments"] + totals["shares"]) / tv * 100, 2
    ) if tv else 0.0
    totals["outcome_score"] = totals["shares"] + totals["comments"]
    return totals


def _days_after_start(upload_date: str, start_date: str) -> Optional[int]:
    """Days between campaign start and this post's upload. None if unparseable."""
    up = _parse_date(upload_date)
    st = _parse_date(start_date)
    if up is None or st is None:
        return None
    return (up - st).days


def _parse_date(s: str) -> Optional[datetime]:
    """Parse the date formats that actually appear in our data.

    Verified against prod (CAMP-65 audit): matched_videos.upload_date is
    YYYYMMDD with no separators (e.g. '20260412' — the dominant format),
    while campaigns.start_date is ISO 'YYYY-MM-DD'. Both must parse correctly
    for the scout/early/mid/late lifecycle buckets to mean anything.
    """
    if not s:
        return None
    s = s.strip()
    # 8-digit YYYYMMDD (the dominant upload_date format) — handle explicitly
    # rather than relying on fromisoformat's basic-format support (3.11+ only).
    if len(s) == 8 and s.isdigit():
        try:
            return datetime.strptime(s, "%Y%m%d")
        except ValueError:
            return None
    # ISO date, optionally with a time component (take the date prefix).
    try:
        return datetime.fromisoformat(s[:10])
    except (ValueError, TypeError):
        pass
    for fmt in ("%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt)
        except (ValueError, TypeError):
            continue
    return None


def _distribution(views: List[int]) -> List[Dict[str, Any]]:
    """Bucket views into log-ish bands for a velocity histogram."""
    bands = [
        ("<50K", 0, 50_000),
        ("50-100K", 50_000, 100_000),
        ("100-250K", 100_000, 250_000),
        ("250-500K", 250_000, 500_000),
        ("500K-1M", 500_000, 1_000_000),
        ("1M+", 1_000_000, float("inf")),
    ]
    out = []
    for label, lo, hi in bands:
        count = sum(1 for v in views if lo <= v < hi)
        out.append({"band": label, "count": count})
    return out


# ============================================================
# SOUND FIT — given a target sound, rank creators most likely to break it.
# ============================================================
# We can't compute audio similarity (no BPM/genre tags). Instead we rank by
# BEHAVIORAL fit: a creator fits a target sound if (a) they're a proven
# breaker in general, boosted when (b) they've already performed on THIS exact
# sound, or (c) on the same ARTIST's other sounds. That's the signal that
# actually predicts "will this creator pop this sound" from data we have.

def list_sounds(session: Session, limit: int = 300) -> List[Dict[str, Any]]:
    """Sounds available to target, tagged with how saturated each one is.

    `post_count` + `freshness` let the picker flag the BOOKING scenario:
    a "fresh" sound (few/no posts yet) is one you're picking creators for
    BEFORE it takes off — fit relies on artist + general-breaker signal, not
    on-sound proof. A "saturated" sound already has broad coverage.
    """
    campaigns = session.query(Campaign).order_by(
        Campaign.created_at.desc(), Campaign.slug,
    ).all()
    rows = [camp for camp in campaigns if camp.sound_id]
    post_counts = {}
    for video, camp in _eligible_posts(session, campaigns):
        sid = _sound_id(video, camp)
        post_counts[sid] = post_counts.get(sid, 0) + 1

    sounds: List[Dict[str, Any]] = []
    for r in rows:
        n = int(post_counts.get(r.sound_id, 0))
        sounds.append({
            "sound_id": r.sound_id,
            "artist": r.artist or "",
            "song": r.song or "",
            "campaign_slug": r.slug,
            "round": r.round or "",
            "start_date": r.start_date or "",
            "post_count": n,
            "freshness": "fresh" if n < 5 else "warm" if n < 40 else "saturated",
        })
    # Fresh sounds first (that's where the picker adds the most value), then by activity.
    return sorted(
        sounds,
        key=lambda s: (0 if s["freshness"] == "fresh" else 1, -s["post_count"]),
    )[:limit]


# How well a post performed on the target sound, as a 0..1 multiplier.
# 500K+ avg on the sound = full boost; scales down linearly below that, so a
# creator who posted the sound but flopped (e.g. 26 views) earns ~nothing.
def _perf_mult(avg_views_on_sound: float) -> float:
    return min(avg_views_on_sound / VIRAL_THRESHOLD, 1.0)


def sound_fit(
    session: Session,
    sound_id: str,
    limit: int = 40,
    campaign_slug: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Rank creators by fit for a specific target sound.

    fit_score = balanced breaker score
                + up to 25, scaled by their VELOCITY on this exact sound
                + up to 12, scaled by their velocity on this artist's sounds

    Scaling the boost by actual performance-on-the-sound (not mere presence)
    is what keeps a saturated sound — where 50+ creators all "posted it" —
    from collapsing to the base ranking. A creator who hit 150K on the sound
    ranks far above one who hit 26 views, even though both "broke" it.
    """
    campaigns = session.query(Campaign).all()
    targets = [camp for camp in campaigns if camp.sound_id == sound_id
               and (campaign_slug is None or camp.slug == campaign_slug)]
    if not targets:
        return None
    target = max(targets, key=lambda camp: (camp.created_at or datetime.min, camp.slug))
    artist = (target.artist or "").strip().lower()
    posts = _eligible_posts(session, campaigns)
    base = {row["account"]: row for row in breaker_leaderboard(
        session, lens="balanced", limit=None, _posts=posts,
    )}
    exact_views = {}
    artist_views = {}
    artist_sound_ids = {camp.sound_id for camp in campaigns
                        if artist and (camp.artist or "").strip().lower() == artist
                        and camp.sound_id and camp.sound_id != sound_id}
    for video, camp in posts:
        account = f"@{normalize_username(video.account)}"
        sid = _sound_id(video, camp)
        if sid == sound_id:
            exact_views.setdefault(account, []).append(video.views)
        elif sid in artist_sound_ids:
            artist_views.setdefault(account, []).append(video.views)
    exact_perf = {account: sum(views) / len(views) for account, views in exact_views.items()}
    artist_perf = {account: sum(views) / len(views) for account, views in artist_views.items()}

    ranked: List[Dict[str, Any]] = []
    for account, row in base.items():
        fit = row["score_balanced"]
        reasons = []
        on_sound = exact_perf.get(account)
        on_artist = artist_perf.get(account)

        if on_sound is not None:
            mult = _perf_mult(on_sound)
            fit += 25 * mult
            # only credit it as a real signal if they actually performed
            if mult >= 0.15:
                reasons.append(f"{fmt_short(on_sound)} avg on this sound")
        if on_artist is not None:
            fit += 12 * _perf_mult(on_artist)
            if _perf_mult(on_artist) >= 0.15:
                reasons.append(f"broke {target.artist}'s sounds")

        ranked.append({
            "account": account,
            "fit_score": round(fit, 1),
            "breaker_score": row["score_balanced"],
            "viral_rate": row["viral_rate"],
            "avg_views": row["avg_views"],
            "millionaires": row["millionaires"],
            "distinct_sounds": row["distinct_sounds"],
            "on_sound_avg": round(on_sound) if on_sound is not None else None,
            "posted_this_sound": on_sound is not None,
            "posted_this_artist": on_artist is not None,
            "reasons": reasons,
        })

    ranked.sort(key=lambda x: x["fit_score"], reverse=True)
    return {
        "sound_id": sound_id,
        "artist": target.artist or "",
        "song": target.song or "",
        "campaign_slug": target.slug,
        "creators": ranked[:limit],
    }


def fmt_short(v: float) -> str:
    """Compact view count: 150609 -> '151K', 1437472 -> '1.4M'."""
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{round(v / 1_000)}K"
    return str(int(v))
