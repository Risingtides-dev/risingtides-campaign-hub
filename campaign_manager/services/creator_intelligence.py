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

from dataclasses import dataclass, asdict
from datetime import datetime
from math import sqrt
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from campaign_manager.models import Campaign, MatchedVideo

# A post is "viral" at/above this view count (the breakout threshold).
VIRAL_THRESHOLD = 500_000
MILLION = 1_000_000
# Minimum tracked posts before a creator qualifies for the leaderboard.
MIN_POSTS = 5

Lens = str  # "ceiling" | "volume" | "balanced"


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


def breaker_leaderboard(
    session: Session,
    lens: Lens = "balanced",
    limit: int = 100,
    min_posts: int = MIN_POSTS,
) -> List[Dict[str, Any]]:
    """Rank creators by sound-breaking ability across all tracked posts.

    Returns a list of BreakerRow dicts, sorted by the chosen lens score desc.
    """
    # Aggregate per account in SQL for the cheap stats; pull per-post views for
    # median (cheap at this scale — ~10k rows total).
    rows = (
        session.query(
            MatchedVideo.account.label("account"),
            func.count().label("posts"),
            func.coalesce(func.avg(MatchedVideo.views), 0).label("avg_views"),
            func.max(MatchedVideo.views).label("peak_views"),
            func.sum(MatchedVideo.views).label("total_views"),
            func.count(func.distinct(MatchedVideo.extracted_sound_id)).label("distinct_sounds"),
            func.sum(
                case((MatchedVideo.views >= VIRAL_THRESHOLD, 1), else_=0)
            ).label("viral_posts"),
            func.sum(
                case((MatchedVideo.views >= MILLION, 1), else_=0)
            ).label("millionaires"),
        )
        .filter(MatchedVideo.dismissed_at.is_(None))
        .filter(MatchedVideo.views > 0)
        .filter(MatchedVideo.account != "")
        .group_by(MatchedVideo.account)
        .having(func.count() >= min_posts)
        .all()
    )

    # Per-account median needs the raw views; fetch once and bucket.
    medians = _account_medians(session, min_posts)

    result: List[BreakerRow] = []
    for r in rows:
        posts = int(r.posts)
        avg_views = float(r.avg_views or 0)
        viral_rate = round(100.0 * int(r.viral_posts) / posts, 1) if posts else 0.0
        sounds = int(r.distinct_sounds or 0)
        millionaires = int(r.millionaires or 0)
        result.append(
            BreakerRow(
                account=r.account,
                posts=posts,
                avg_views=round(avg_views),
                median_views=medians.get(r.account, 0),
                peak_views=int(r.peak_views or 0),
                viral_rate=viral_rate,
                millionaires=millionaires,
                distinct_sounds=sounds,
                total_views=int(r.total_views or 0),
                score_ceiling=_score_ceiling(viral_rate, avg_views),
                score_volume=_score_volume(millionaires, posts, sounds),
                score_balanced=_score_balanced(viral_rate, avg_views, posts, sounds),
            )
        )

    key = {
        "ceiling": lambda x: x.score_ceiling,
        "volume": lambda x: x.score_volume,
        "balanced": lambda x: x.score_balanced,
    }.get(lens, lambda x: x.score_balanced)

    result.sort(key=key, reverse=True)
    return [asdict(row) for row in result[:limit]]


def _account_medians(session: Session, min_posts: int) -> Dict[str, int]:
    """Compute per-account median views (small dataset, done in Python)."""
    rows = (
        session.query(MatchedVideo.account, MatchedVideo.views)
        .filter(MatchedVideo.dismissed_at.is_(None))
        .filter(MatchedVideo.views > 0)
        .filter(MatchedVideo.account != "")
        .all()
    )
    buckets: Dict[str, List[int]] = {}
    for account, views in rows:
        buckets.setdefault(account, []).append(int(views or 0))
    return {
        acct: _median(vals)
        for acct, vals in buckets.items()
        if len(vals) >= min_posts
    }


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
    norm = account if account.startswith("@") else f"@{account}"

    videos = (
        session.query(MatchedVideo, Campaign)
        .join(Campaign, MatchedVideo.campaign_id == Campaign.id)
        .filter(MatchedVideo.account == norm)
        .filter(MatchedVideo.dismissed_at.is_(None))
        .filter(MatchedVideo.views > 0)
        .all()
    )
    if not videos:
        return None

    all_views = [int(v.views or 0) for v, _ in videos]
    posts = len(all_views)
    viral = sum(1 for x in all_views if x >= VIRAL_THRESHOLD)
    millionaires = sum(1 for x in all_views if x >= MILLION)

    # Per-sound rollup, with lifecycle timing vs the campaign start_date.
    sounds: Dict[str, Dict[str, Any]] = {}
    for v, camp in videos:
        sid = v.extracted_sound_id or camp.sound_id or "unknown"
        bucket = sounds.setdefault(
            sid,
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
        "distinct_sounds": len(sounds),
        "early_adopter_rate": round(
            100.0 * sum(1 for s in sound_list if s["timing"] in ("scout", "early")) / len(sound_list), 1
        ) if sound_list else 0.0,
        "sounds": sound_list,
        "view_distribution": _distribution(all_views),
        "score_balanced": _score_balanced(
            round(100.0 * viral / posts, 1),
            sum(all_views) / posts,
            posts,
            len(sounds),
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
    totals: Dict[str, Any] = {"views": 0, "likes": 0, "comments": 0, "shares": 0, "posts": 0, "campaigns": 0}
    found = False
    with ThreadPoolExecutor(max_workers=min(8, len(share_urls) or 1)) as ex:
        for oc in ex.map(lambda u: creator_outcomes(u, account), share_urls):
            if not oc:
                continue
            found = True
            totals["campaigns"] += 1
            for k in ("views", "likes", "comments", "shares", "posts"):
                totals[k] += oc.get(k, 0)

    if not found:
        return None

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
    rows = (
        session.query(
            Campaign.sound_id.label("sound_id"),
            Campaign.artist.label("artist"),
            Campaign.song.label("song"),
            Campaign.slug.label("slug"),
        )
        .filter(Campaign.sound_id != "")
        .all()
    )

    # Per-sound matched-post counts (how broadly the sound has been posted).
    post_counts = dict(
        session.query(MatchedVideo.extracted_sound_id, func.count())
        .filter(MatchedVideo.extracted_sound_id != "")
        .filter(MatchedVideo.dismissed_at.is_(None))
        .filter(MatchedVideo.views > 0)
        .group_by(MatchedVideo.extracted_sound_id)
        .all()
    )

    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if r.sound_id in seen:
            continue
        n = int(post_counts.get(r.sound_id, 0))
        seen[r.sound_id] = {
            "sound_id": r.sound_id,
            "artist": r.artist or "",
            "song": r.song or "",
            "campaign_slug": r.slug,
            "post_count": n,
            "freshness": "fresh" if n < 5 else "warm" if n < 40 else "saturated",
        }
    # Fresh sounds first (that's where the picker adds the most value), then by activity.
    return sorted(
        seen.values(),
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
    target = (
        session.query(Campaign)
        .filter(Campaign.sound_id == sound_id)
        .first()
    )
    if target is None:
        return None
    artist = (target.artist or "").strip().lower()

    # General breaker scores (the base ability).
    base = {r["account"]: r for r in breaker_leaderboard(session, lens="balanced", limit=1000)}

    # Per-creator AVG VIEWS on this exact sound (not just presence).
    exact_perf: Dict[str, float] = {
        a: float(avg or 0)
        for a, avg in session.query(
            MatchedVideo.account, func.avg(MatchedVideo.views)
        )
        .filter(MatchedVideo.extracted_sound_id == sound_id)
        .filter(MatchedVideo.dismissed_at.is_(None))
        .filter(MatchedVideo.views > 0)
        .group_by(MatchedVideo.account)
        .all()
    }

    # Per-creator avg views across this artist's OTHER sounds.
    artist_perf: Dict[str, float] = {}
    if artist:
        artist_sound_ids = {
            sid for (sid,) in session.query(Campaign.sound_id)
            .filter(func.lower(Campaign.artist) == artist)
            .filter(Campaign.sound_id != "")
            .filter(Campaign.sound_id != sound_id)
            .all()
        }
        if artist_sound_ids:
            artist_perf = {
                a: float(avg or 0)
                for a, avg in session.query(
                    MatchedVideo.account, func.avg(MatchedVideo.views)
                )
                .filter(MatchedVideo.extracted_sound_id.in_(artist_sound_ids))
                .filter(MatchedVideo.dismissed_at.is_(None))
                .filter(MatchedVideo.views > 0)
                .group_by(MatchedVideo.account)
                .all()
            }

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
