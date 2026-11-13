"""Who is ready to be paid, and why.

Rules (decided 2026-10-30):
  - Standard creators: ready once ALL posts are delivered (posts_done >=
    posts_owed). Partial delivery is not paid unless Jake marks the booking
    ready by hand ("unless otherwise specified").
  - Trusted creators (more than 5 delivered campaigns, or a manual
    override): paid up front, so ready as soon as Jake confirms they
    accepted the booking.
  - Already-paid bookings are never ready.

Only ACTIVE campaigns are considered. Finished campaigns carry years of
`paid = no` rows that were often paid outside the Hub; queueing those would
risk paying people twice.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select

from campaign_manager.models import BookingPaymentMark, Campaign, Creator, CreatorProfile
from campaign_manager.services.creator_library import normalize_username

TRUSTED_MIN_CAMPAIGNS = 6  # "over 5 campaigns"
TRUST_OVERRIDES = ("", "trusted", "standard")


def _is_paid(booking: Creator) -> bool:
    return str(booking.paid or "").strip().lower() == "yes"


def _platform(booking: Creator) -> str:
    return (booking.platform or "tiktok").lower()


def delivered_campaign_counts(session) -> dict[str, int]:
    """Distinct campaigns each creator fully delivered, across all history."""
    rows = session.execute(
        select(Creator.username, Creator.campaign_id)
        .where(func.coalesce(Creator.status, "active") != "removed")
        .where(Creator.posts_owed > 0)
        .where(Creator.posts_done >= Creator.posts_owed)
    ).all()
    seen: dict[str, set] = defaultdict(set)
    for username, campaign_id in rows:
        seen[normalize_username(username)].add(campaign_id)
    return {user: len(ids) for user, ids in seen.items()}


def is_trusted(delivered: int, override: str) -> bool:
    if override == "trusted":
        return True
    if override == "standard":
        return False
    return delivered >= TRUSTED_MIN_CAMPAIGNS


def classify(booking: Creator, mark, trusted: bool) -> tuple[str, str]:
    """(state, reason). state: paid | ready | awaiting_confirmation | not_ready."""
    if _is_paid(booking):
        return "paid", "paid"
    if mark is not None and mark.ready_at is not None:
        return "ready", mark.ready_reason or "manual"
    owed, done = int(booking.posts_owed or 0), int(booking.posts_done or 0)
    if owed > 0 and done >= owed:
        return "ready", "posts_complete"
    if trusted:
        return "awaiting_confirmation", "trusted_unconfirmed"
    return "not_ready", "posts_incomplete"


def _destination_issue(profile) -> str:
    if profile is None or not (profile.payout_destination or ""):
        return "missing"
    if profile.payout_change_flagged:
        return "changed"
    if not profile.payout_confirmed_by_creator:
        return "unconfirmed"
    return ""


def _active_bookings(session):
    return session.execute(
        select(Creator, Campaign)
        .join(Campaign, Creator.campaign_id == Campaign.id)
        .where(func.coalesce(Campaign.completion_status, "none") != "completed")
        .where(func.coalesce(Creator.status, "active") != "removed")
        .order_by(Campaign.start_date.asc(), Campaign.id.asc(), Creator.username.asc())
    ).all()


def _marks(session) -> dict[tuple, BookingPaymentMark]:
    return {
        (m.campaign_id, m.username, m.platform): m
        for m in session.execute(select(BookingPaymentMark)).scalars()
    }


def build_queue(session) -> dict:
    from campaign_manager.services.payout_batches import open_items_by_key  # avoid import cycle

    in_batch = open_items_by_key(session)
    delivered = delivered_campaign_counts(session)
    profiles = {p.username: p for p in session.execute(select(CreatorProfile)).scalars()}
    marks = _marks(session)
    groups: dict[str, list] = {"ready": [], "awaiting_confirmation": [], "not_ready": [], "in_batch": []}

    for booking, campaign in _active_bookings(session):
        user = normalize_username(booking.username)
        profile = profiles.get(user)
        override = (profile.trust_override or "") if profile else ""
        trusted = is_trusted(delivered.get(user, 0), override)
        key = (campaign.id, user, _platform(booking))
        state, reason = classify(booking, marks.get(key), trusted)
        if state == "paid":
            continue
        payment = in_batch.get(key)
        if payment is not None:
            # Already in a payment (never offered again — no paying twice).
            if payment["item_status"] == "succeeded":
                continue
            state = "in_batch"
        groups[state].append({
            "slug": campaign.slug,
            "campaign_id": campaign.id,
            "campaign": campaign.title or campaign.slug,
            "start_date": campaign.start_date or "",
            "username": user,
            "handle": (profile.display_username if profile else "") or user,
            "platform": _platform(booking),
            "amount": round(float(booking.total_rate or 0), 2),
            "posts_owed": int(booking.posts_owed or 0),
            "posts_done": int(booking.posts_done or 0),
            "reason": reason,
            "trusted": trusted,
            "trust_override": override,
            "delivered_campaigns": delivered.get(user, 0),
            "method": (profile.payout_method or "") if profile else "",
            "destination": (profile.payout_destination or "") if profile else "",
            "destination_issue": _destination_issue(profile),
            # Old per-booking PayPal field, offered as a one-click "Use this"
            # when the creator has nothing on file yet.
            "booking_destination": (booking.paypal_email or "").strip()
            if _destination_issue(profile) == "missing" else "",
            "payment": payment,
        })

    ready = groups["ready"]
    by_method: dict[str, float] = defaultdict(float)
    for row in ready:
        by_method[row["method"] or "missing"] += row["amount"]
    return {
        **groups,
        "totals": {
            "ready_count": len(ready),
            "ready_amount": round(sum(r["amount"] for r in ready), 2),
            "payable_now": round(sum(r["amount"] for r in ready if not r["destination_issue"]), 2),
            "by_method": {k: round(v, 2) for k, v in sorted(by_method.items())},
        },
        "trusted_min_campaigns": TRUSTED_MIN_CAMPAIGNS,
    }


def find_booking(session, campaign_id: int, username: str, platform: str):
    """The active booking row for (campaign, creator, platform), or None."""
    user, plat = normalize_username(username), (platform or "tiktok").lower()
    handle = func.lower(func.trim(Creator.username))
    return session.execute(
        select(Creator)
        .where(Creator.campaign_id == campaign_id)
        .where(handle.in_([user, f"@{user}"]))
        .where(func.lower(func.coalesce(Creator.platform, "tiktok")) == plat)
        .where(func.coalesce(Creator.status, "active") != "removed")
    ).scalars().first()


def booking_state(session, campaign_id, username: str, platform: str):
    """(booking, campaign, state) re-read fresh — used at batch approval."""
    campaign = session.get(Campaign, campaign_id) if campaign_id else None
    booking = find_booking(session, campaign_id, username, platform) if campaign else None
    if booking is None:
        return None, campaign, "missing"
    user, plat = normalize_username(username), (platform or "tiktok").lower()
    profile = session.get(CreatorProfile, user)
    override = (profile.trust_override or "") if profile else ""
    delivered = delivered_campaign_counts(session).get(user, 0)
    mark = session.execute(
        select(BookingPaymentMark).where(
            BookingPaymentMark.campaign_id == campaign_id,
            BookingPaymentMark.username == user,
            BookingPaymentMark.platform == plat,
        )
    ).scalar_one_or_none()
    state, _ = classify(booking, mark, is_trusted(delivered, override))
    return booking, campaign, state


def set_mark(session, slug: str, username: str, platform: str, action: str, note: str = "") -> bool:
    """action: confirm (trusted accepted booking) | ready (manual) | clear."""
    campaign = session.execute(select(Campaign).where(Campaign.slug == slug)).scalar_one_or_none()
    if campaign is None:
        return False
    user, plat = normalize_username(username), (platform or "tiktok").lower()
    if find_booking(session, campaign.id, user, plat) is None:
        return False

    mark = session.execute(
        select(BookingPaymentMark).where(
            BookingPaymentMark.campaign_id == campaign.id,
            BookingPaymentMark.username == user,
            BookingPaymentMark.platform == plat,
        )
    ).scalar_one_or_none()
    if mark is None:
        mark = BookingPaymentMark(campaign_id=campaign.id, username=user, platform=plat)
        session.add(mark)

    if action == "clear":
        mark.ready_at, mark.ready_reason = None, ""
    else:
        mark.ready_at = datetime.now()
        mark.ready_reason = "trusted_confirmed" if action == "confirm" else "manual"
    mark.note = (note or "")[:500]
    session.commit()
    return True


def set_trust_override(session, username: str, override: str) -> bool:
    if override not in TRUST_OVERRIDES:
        raise ValueError("override must be '', 'trusted' or 'standard'")
    profile = session.get(CreatorProfile, normalize_username(username))
    if profile is None:
        return False
    profile.trust_override = override
    session.commit()
    return True
