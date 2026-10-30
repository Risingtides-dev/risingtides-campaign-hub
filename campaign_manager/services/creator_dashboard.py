"""What a creator sees on their private dashboard (/creator#<token>).

Strict allowlist: only this creator's own bookings and money. Never other
creators, campaign budgets, Cobrand links (they carry auth tokens), CRM
notes, or the booking `notes` column (internal).
"""
from __future__ import annotations

from collections import OrderedDict
from sqlalchemy import func, select

from campaign_manager.models import BookingPaymentMark, Campaign, Creator, CreatorProfile
from campaign_manager.services.payout_profiles import public_view
from campaign_manager.utils.helpers import campaign_title

OPEN_CREATIVE = "Open creative"


def _is_paid(booking: Creator) -> bool:
    return str(booking.paid or "").strip().lower() == "yes"


def _money(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _sounds(campaign: Campaign, platforms: set) -> list[dict]:
    sounds = []
    # TikTok sound for TikTok bookings, or as the only sound we have.
    if campaign.official_sound and ("tiktok" in platforms or not campaign.insta_sound):
        sounds.append({"platform": "tiktok", "url": campaign.official_sound})
    for url in campaign.additional_sounds or []:
        if isinstance(url, str) and url.strip():
            sounds.append({"platform": "tiktok", "url": url.strip()})
    if campaign.insta_sound and "instagram" in platforms:
        sounds.append({"platform": "instagram", "url": campaign.insta_sound})
    return sounds


def _captions(campaign: Campaign) -> list[str]:
    text = campaign.internal_captions or ""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _booking_status(owed: int, done: int, paid: bool, marked_ready: bool) -> str:
    if paid:
        return "paid"
    if marked_ready or (owed and done >= owed):
        return "complete"
    return "in_progress"


def _bookings_for(session, username: str) -> list[tuple[Creator, Campaign]]:
    handle = func.lower(func.trim(Creator.username))
    rows = session.execute(
        select(Creator, Campaign)
        .join(Campaign, Creator.campaign_id == Campaign.id)
        .where(handle.in_([username, f"@{username}"]))
        .where(func.coalesce(Creator.status, "active") != "removed")
        .order_by(Campaign.start_date.desc(), Campaign.id.desc())
    ).all()
    return [(b, c) for b, c in rows]


def _group_by_campaign(rows) -> "OrderedDict[int, dict]":
    """A creator can hold a TikTok and an Instagram booking on one campaign;
    show one card per campaign with the posts and money summed."""
    grouped: "OrderedDict[int, dict]" = OrderedDict()
    for booking, campaign in rows:
        entry = grouped.setdefault(campaign.id, {"campaign": campaign, "bookings": []})
        entry["bookings"].append(booking)
    return grouped


def _card(campaign: Campaign, bookings: list[Creator], marked_ready: bool = False) -> dict:
    owed = sum(int(b.posts_owed or 0) for b in bookings)
    done = sum(int(b.posts_done or 0) for b in bookings)
    paid = all(_is_paid(b) for b in bookings)
    platforms = {(b.platform or "tiktok").lower() for b in bookings}
    brief = (campaign.creator_brief or "").strip()
    return {
        "campaign": campaign_title(campaign.to_meta_dict()),
        "artist": campaign.artist or "",
        "song": campaign.song or "",
        "start_date": campaign.start_date or "",
        "platforms": sorted(platforms),
        "sounds": _sounds(campaign, platforms),
        "brief": brief or OPEN_CREATIVE,
        "open_creative": not brief,
        "captions": _captions(campaign),
        "posts_owed": owed,
        "posts_done": min(done, owed) if owed else done,
        "rate": _money(sum(_money(b.total_rate) for b in bookings)),
        "status": _booking_status(owed, done, paid, marked_ready),
        "active": (campaign.completion_status or "none") != "completed",
    }


def _payments(grouped) -> list[dict]:
    payments = []
    for entry in grouped.values():
        campaign = entry["campaign"]
        for booking in entry["bookings"]:
            if not _is_paid(booking):
                continue
            payments.append({
                "campaign": campaign_title(campaign.to_meta_dict()),
                "amount": _money(booking.total_rate),
                "date": booking.payment_date or "",
                "platform": booking.platform or "tiktok",
            })
    payments.sort(key=lambda p: p["date"] or "", reverse=True)
    return payments


def build_dashboard(session, profile: CreatorProfile) -> dict:
    grouped = _group_by_campaign(_bookings_for(session, profile.username))
    ready_campaigns = set(session.execute(
        select(BookingPaymentMark.campaign_id)
        .where(BookingPaymentMark.username == profile.username)
        .where(BookingPaymentMark.ready_at.isnot(None))
    ).scalars())
    cards = [_card(e["campaign"], e["bookings"], cid in ready_campaigns) for cid, e in grouped.items()]
    current = [c for c in cards if c["active"] or c["status"] != "paid"]
    payments = _payments(grouped)
    return {
        "creator": public_view(profile),
        "current": current,
        "payments": payments,
        "totals": {
            "paid": _money(sum(p["amount"] for p in payments)),
            "campaigns": len(cards),
        },
    }

