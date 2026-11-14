"""Assemble the Creator Library listing.

Three sources have to be reconciled into one row per person:

  * `Creator` rows — the booking history, one per campaign
  * `CreatorProfile` — tags, rate memory, notes, cached tracker stats
  * `Niche` / `CreatorNiche` — the vocabulary

The union matters. A creator scouted but never booked exists only as a
profile, and a creator booked before the Library shipped exists only as
booking rows; both have to appear, and neither can be dropped because the
other source has nothing to say about them.

Everything is built in a handful of queries rather than per creator — the
roster is ~400 people and the page loads all of them at once.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from campaign_manager.models import Creator, CreatorProfile
from campaign_manager.services.creator_library import (
    all_niches_by_creator,
    normalize_username,
)
from campaign_manager.services.creator_library_stats import (
    DEFAULT_WINDOW,
    effective_rate,
    with_rate,
)


def _parse_added(value) -> Optional[date]:
    """`Creator.added_date` is a 'YYYY-MM-DD' string."""
    text = str(value or "")[:10]
    if len(text) != 10:
        return None
    try:
        return date(int(text[:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, TypeError):
        return None


def booking_summary(session) -> Dict[str, Dict]:
    """Roll every booking up per creator, keeping rate history per platform.

    Tracks the *most recent* booking specifically — not an average — because
    that is what the rate memory resolves against. Averaging was the first
    version's bug: 39 of 55 creators had a last rate different from their
    mean, so the average was consistently the wrong number to quote.
    """
    out: Dict[str, Dict] = {}

    rows = session.query(
        Creator.username,
        Creator.per_post_rate,
        Creator.total_rate,
        Creator.posts_owed,
        Creator.posts_done,
        Creator.added_date,
        Creator.paypal_email,
        Creator.platform,
        Creator.status,
    ).order_by(Creator.id).all()

    for row in rows:
        if (row.status or "active") == "removed":
            continue
        username = normalize_username(row.username)
        if not username:
            continue

        entry = out.setdefault(username, {
            "display": (row.username or "").strip().lstrip("@"),
            "campaigns": 0,
            "posts_owed": 0,
            "posts_done": 0,
            "spend": 0.0,
            "last_rate": None,
            "last_booked_at": None,
            "paypal_email": "",
            "platform": row.platform or "tiktok",
            "by_platform": {},
        })

        platform = _platform(row.platform)
        scoped = entry["by_platform"].setdefault(platform, {
            "last_rate": None, "last_booked_at": None,
        })

        entry["campaigns"] += 1
        entry["posts_owed"] += int(row.posts_owed or 0)
        entry["posts_done"] += int(row.posts_done or 0)
        entry["spend"] += float(row.total_rate or 0)

        if row.paypal_email:
            entry["paypal_email"] = row.paypal_email

        # Per-post rate, falling back to dividing the booking when an older
        # row never had one computed.
        rate = float(row.per_post_rate or 0)
        if not rate and row.posts_owed:
            rate = round(float(row.total_rate or 0) / int(row.posts_owed), 2)

        booked_on = _parse_added(row.added_date)
        if rate:
            current = scoped["last_booked_at"]
            # An undated booking only wins if we have nothing dated at all.
            if scoped["last_rate"] is None or (
                booked_on and (current is None or booked_on >= current)
            ):
                scoped["last_rate"] = rate
                scoped["last_booked_at"] = booked_on

    for entry in out.values():
        entry["spend"] = round(entry["spend"], 2)
        # A person-level summary keeps its full history, but rate evidence
        # always comes from one deterministic platform, never mixed rows.
        platform, booking, _ = _rate_context(entry, None, None)
        entry.update(platform=platform, **booking)
    return out


def _platform(value) -> str:
    return str(value or "tiktok").strip().lower() or "tiktok"


def _requested_platform(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    platform = str(value).strip().lower()
    if platform not in {"tiktok", "instagram"}:
        raise ValueError("platform must be tiktok or instagram")
    return platform


def _rate_context(booking: Dict, profile, requested: Optional[str]):
    """Choose one platform and only the history/override belonging to it."""
    histories = booking.get("by_platform", {})
    profile_platform = (str(profile.platform or "").strip().lower() or None) if profile is not None else None
    platform = (requested or profile_platform or
                ("tiktok" if "tiktok" in histories else next(iter(sorted(histories)), "tiktok")))
    return platform, histories.get(platform, {}), profile if profile_platform == platform else None


def build_library(session, window: str = DEFAULT_WINDOW, platform: Optional[str] = None) -> List[Dict]:
    """One row per creator, ranked by projected CPM within `window`.

    Creators with no data for the window sort last rather than first — an
    unknown CPM is not a cheap one. An explicit platform filters the roster
    and rate evidence; historical spend/post/campaign totals remain per person.
    Otherwise prefer the profile's platform, then TikTok history, then another
    historical platform. Profile rates and stats never cross platforms.
    """
    requested = _requested_platform(platform)
    bookings = booking_summary(session)
    profiles = {p.username: p for p in session.query(CreatorProfile).all()}
    tags = all_niches_by_creator(session)

    usernames = set(bookings) | set(profiles)
    out: List[Dict] = []

    for username in usernames:
        booking = bookings.get(username, {})
        profile = profiles.get(username)
        selected_platform, rate_booking, rate_profile = _rate_context(booking, profile, requested)
        if requested and not rate_booking and rate_profile is None:
            continue

        rate, source = effective_rate(
            override=rate_profile.rate_override if rate_profile else None,
            override_at=rate_profile.rate_override_at if rate_profile else None,
            last_rate=rate_booking.get("last_rate"),
            last_booked_at=rate_booking.get("last_booked_at"),
        )

        stats = with_rate(rate_profile.stats if rate_profile else {}, rate)

        display = (
            (profile.display_username if profile else "")
            or booking.get("display")
            or username
        )

        out.append({
            "username": display,
            "key": username,
            "niches": tags.get(username, []),
            "rate": rate,
            "rate_source": source,
            "rate_override": rate_profile.rate_override if rate_profile else None,
            "slow": bool(profile.slow) if profile else False,
            "note": (profile.note or "") if profile else "",
            "paypal_email": (
                (profile.paypal_email if profile else "")
                or booking.get("paypal_email", "")
            ),
            "platform": selected_platform,
            "followers": (rate_profile.followers or 0) if rate_profile else 0,
            "avatar_url": (rate_profile.avatar_url or "") if rate_profile else "",
            "campaigns": booking.get("campaigns", 0),
            "posts_owed": booking.get("posts_owed", 0),
            "posts_done": booking.get("posts_done", 0),
            "spend": booking.get("spend", 0.0),
            "last_booked_at": (
                rate_booking["last_booked_at"].isoformat()
                if rate_booking.get("last_booked_at") else ""
            ),
            # Never booked: show dashes for performance rather than zeros.
            "scouted": booking.get("campaigns", 0) == 0,
            "stats": stats,
            "stats_updated_at": (
                rate_profile.stats_updated_at.isoformat()
                if rate_profile and rate_profile.stats_updated_at else ""
            ),
        })

    def rank(row):
        current = (row["stats"] or {}).get(window) or {}
        pcpm = current.get("pcpm")
        return (0, pcpm) if pcpm is not None else (1, 0)

    out.sort(key=rank)
    return out


def rate_for_booking(session, username: str, platform: Optional[str] = None) -> Dict:
    """What this creator should cost on the next booking.

    Powers the auto-fill when a creator is added to a campaign, and carries
    enough context for the UI to say where the number came from. Rate and
    last-booking evidence always belong to the returned platform.
    """
    user = normalize_username(username)
    requested = _requested_platform(platform)
    booking = booking_summary(session).get(user, {})
    profile = session.get(CreatorProfile, user)
    selected_platform, rate_booking, rate_profile = _rate_context(booking, profile, requested)

    rate, source = effective_rate(
        override=rate_profile.rate_override if rate_profile else None,
        override_at=rate_profile.rate_override_at if rate_profile else None,
        last_rate=rate_booking.get("last_rate"),
        last_booked_at=rate_booking.get("last_booked_at"),
    )

    return {
        "username": user,
        "platform": selected_platform,
        "rate": rate,
        "source": source,
        "last_rate": rate_booking.get("last_rate"),
        "last_booked_at": (
            rate_booking["last_booked_at"].isoformat()
            if rate_booking.get("last_booked_at") else ""
        ),
        "campaigns": booking.get("campaigns", 0),
    }
