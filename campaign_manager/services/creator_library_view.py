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
    """Roll every booking up per creator.

    Tracks the *most recent* booking specifically — not an average — because
    that is what the rate memory resolves against. Averaging was the first
    version's bug: 39 of 55 creators had a last rate different from their
    mean, so the average was consistently the wrong number to quote.

    `per_platform_rates` maps each platform the creator has been booked on to
    their most recent (rate, date) on that platform. The main `platform` and
    `last_rate` fields always describe the same booking (the most recently
    dated one), so they are always mutually consistent.
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
    ).all()

    for row in rows:
        if (row.status or "active") == "removed":
            continue
        username = normalize_username(row.username)
        if not username:
            continue

        platform = row.platform or "tiktok"

        entry = out.setdefault(username, {
            "display": (row.username or "").strip().lstrip("@"),
            "campaigns": 0,
            "posts_owed": 0,
            "posts_done": 0,
            "spend": 0.0,
            "last_rate": None,
            "last_booked_at": None,
            "paypal_email": "",
            "platform": platform,
            "per_platform_rates": {},
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
            # Track the most recent rate per platform — isolates TikTok from
            # Instagram so a booking wizard asking for a platform-specific rate
            # never gets a price from a different one.
            per_plat = entry["per_platform_rates"]
            cur_rate, cur_date = per_plat.get(platform, (None, None))
            # An undated booking only wins if we have nothing dated at all.
            if cur_rate is None or (
                booked_on and (cur_date is None or booked_on >= cur_date)
            ):
                per_plat[platform] = (rate, booked_on)

            # The main last_rate and platform always move together so they
            # describe the same booking. An undated booking only wins if we
            # have nothing dated at all.
            current = entry["last_booked_at"]
            if entry["last_rate"] is None or (
                booked_on and (current is None or booked_on >= current)
            ):
                entry["last_rate"] = rate
                entry["last_booked_at"] = booked_on
                entry["platform"] = platform

    for entry in out.values():
        entry["spend"] = round(entry["spend"], 2)
    return out


def build_library(session, window: str = DEFAULT_WINDOW) -> List[Dict]:
    """One row per creator, ranked by projected CPM within `window`.

    Creators with no data for the window sort last rather than first — an
    unknown CPM is not a cheap one.
    """
    bookings = booking_summary(session)
    profiles = {p.username: p for p in session.query(CreatorProfile).all()}
    tags = all_niches_by_creator(session)

    usernames = set(bookings) | set(profiles)
    out: List[Dict] = []

    for username in usernames:
        booking = bookings.get(username, {})
        profile = profiles.get(username)

        rate, source = effective_rate(
            override=profile.rate_override if profile else None,
            override_at=profile.rate_override_at if profile else None,
            last_rate=booking.get("last_rate"),
            last_booked_at=booking.get("last_booked_at"),
        )

        stats = with_rate(profile.stats if profile else {}, rate)
        current = stats.get(window)

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
            "rate_override": profile.rate_override if profile else None,
            "slow": bool(profile.slow) if profile else False,
            "note": (profile.note or "") if profile else "",
            "paypal_email": (
                (profile.paypal_email if profile else "")
                or booking.get("paypal_email", "")
            ),
            "platform": (
                booking.get("platform")
                or (profile.platform if profile else "tiktok")
            ),
            "followers": (profile.followers or 0) if profile else 0,
            "avatar_url": (profile.avatar_url or "") if profile else "",
            "campaigns": booking.get("campaigns", 0),
            "posts_owed": booking.get("posts_owed", 0),
            "posts_done": booking.get("posts_done", 0),
            "spend": booking.get("spend", 0.0),
            "last_booked_at": (
                booking["last_booked_at"].isoformat()
                if booking.get("last_booked_at") else ""
            ),
            # Never booked: show dashes for performance rather than zeros.
            "scouted": booking.get("campaigns", 0) == 0,
            "stats": stats,
            "stats_updated_at": (
                profile.stats_updated_at.isoformat()
                if profile and profile.stats_updated_at else ""
            ),
        })

    def rank(row):
        current = (row["stats"] or {}).get(window) or {}
        pcpm = current.get("pcpm")
        return (0, pcpm) if pcpm is not None else (1, 0)

    out.sort(key=rank)
    return out


def rate_for_booking(
    session, username: str, platform: Optional[str] = None
) -> Dict:
    """What this creator should cost on the next booking.

    Powers the auto-fill when a creator is added to a campaign, and carries
    enough context for the UI to say where the number came from.

    When `platform` is given, `last_rate` is sourced only from that platform's
    booking history. A TikTok booking will never quote an Instagram price.
    When no bookings exist for the requested platform, `last_rate` is None and
    the profile override (if any) still applies.
    """
    user = normalize_username(username)
    booking = booking_summary(session).get(user, {})
    profile = session.get(CreatorProfile, user)

    last_rate = booking.get("last_rate")
    last_booked_at = booking.get("last_booked_at")

    if platform:
        plat_key = platform.strip().lower()
        per_platform = booking.get("per_platform_rates", {})
        if plat_key in per_platform:
            last_rate, last_booked_at = per_platform[plat_key]
        elif booking:
            # Creator has bookings but none on this platform.
            last_rate = None
            last_booked_at = None

    rate, source = effective_rate(
        override=profile.rate_override if profile else None,
        override_at=profile.rate_override_at if profile else None,
        last_rate=last_rate,
        last_booked_at=last_booked_at,
    )

    return {
        "username": user,
        "rate": rate,
        "source": source,
        "last_rate": last_rate,
        "last_booked_at": (
            last_booked_at.isoformat() if last_booked_at else ""
        ),
        "platform": platform or booking.get("platform"),
        "campaigns": booking.get("campaigns", 0),
    }
