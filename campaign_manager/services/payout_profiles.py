"""Creator payout destinations: token links, creator submissions, audit.

The token is a bearer credential: whoever holds the link can set where a
creator gets paid. So:
  - tokens are 256-bit random, never derived from the username;
  - every change writes a CreatorPayoutEvent with the old value kept;
  - replacing an EXISTING destination raises `payout_change_flagged`, which
    the Hub's Payouts page surfaces until Jake clears it.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from campaign_manager.models import CreatorPayoutEvent, CreatorProfile
from campaign_manager.services.creator_library import (
    get_or_create_profile,
    normalize_username,
)
from campaign_manager.services.payout_validation import (
    mask_destination,
    normalize_destination,
)

TOKEN_BYTES = 32  # token_urlsafe(32) -> 43 chars
_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def build_link(base_url: str, token: str) -> str:
    # Token rides in the fragment: browsers never send it to the server, so
    # it can't land in access logs, proxies or Referer headers.
    return f"{base_url.rstrip('/')}/creator#{token}"


def find_by_token(session, token, *, for_update: bool = False) -> Optional[CreatorProfile]:
    """`for_update` row-locks the profile so two concurrent submissions
    can't both see the same "old" value (and skip the change flag)."""
    value = str(token or "")
    if not _TOKEN_SHAPE.match(value):
        return None
    stmt = select(CreatorProfile).where(CreatorProfile.payout_token == value)
    if for_update:
        stmt = stmt.with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def _record(session, username, event, source, *, old=("", ""), new=("", ""), client_ip=""):
    session.add(CreatorPayoutEvent(
        username=username,
        event=event,
        source=source,
        old_method=old[0] or "",
        old_destination=old[1] or "",
        new_method=new[0] or "",
        new_destination=new[1] or "",
        client_ip=(client_ip or "")[:64],
        created_at=datetime.now(),
    ))


def public_view(profile: CreatorProfile) -> dict:
    """What the creator-facing page may show: their handle, masked details."""
    destination = profile.payout_destination or ""
    return {
        "handle": profile.display_username or profile.username,
        "method": (profile.payout_method or "") if destination else "",
        "destination_masked": mask_destination(destination),
        "confirmed": bool(profile.payout_confirmed_by_creator) and bool(destination),
    }


def submit_destination(session, profile, method, destination, client_ip="") -> str:
    """Apply a creator's submission. Returns created | changed | confirmed.

    Raises PayoutValidationError (message safe for the creator) on bad input.
    """
    new = normalize_destination(method, destination)
    old = (profile.payout_method or "", profile.payout_destination or "")

    if not old[1]:
        event = "created"
    elif old == (new.method, new.destination):
        event = "confirmed"
    else:
        event = "changed"
        profile.payout_change_flagged = True

    profile.payout_method = new.method
    profile.payout_destination = new.destination
    profile.payout_confirmed_by_creator = True
    profile.payout_updated_at = datetime.now()
    _record(session, profile.username, event, "creator_link",
            old=old, new=tuple(new), client_ip=client_ip)
    session.commit()
    return event


def admin_set_destination(session, username: str, method, destination) -> str:
    """Jake enters/fixes details in the Hub. He has verified them, so they
    count as confirmed and clear any change flag. Old value kept in the log.
    Raises PayoutValidationError on bad input."""
    new = normalize_destination(method, destination)
    profile = get_or_create_profile(session, username, commit=False)
    old = (profile.payout_method or "", profile.payout_destination or "")
    profile.payout_method = new.method
    profile.payout_destination = new.destination
    profile.payout_confirmed_by_creator = True
    profile.payout_change_flagged = False
    profile.payout_updated_at = datetime.now()
    _record(session, profile.username, "admin_set", "admin", old=old, new=tuple(new))
    session.commit()
    return profile.username


def issue_token(session, username: str, *, rotate: bool = False) -> tuple[CreatorProfile, bool]:
    """Ensure this creator has a link token. Returns (profile, newly_issued).

    `rotate=True` replaces an existing token, killing the old link — use it
    when a link may have leaked.
    """
    profile = get_or_create_profile(session, username, commit=False)
    if profile.payout_token and not rotate:
        return profile, False
    event = "token_rotated" if profile.payout_token else "token_issued"
    profile.payout_token = generate_token()
    _record(session, profile.username, event, "admin")
    session.commit()
    return profile, True


def clear_flag(session, username: str) -> bool:
    profile = session.get(CreatorProfile, normalize_username(username))
    if profile is None:
        return False
    if profile.payout_change_flagged:
        profile.payout_change_flagged = False
        _record(session, profile.username, "flag_cleared", "admin")
        session.commit()
    return True


def admin_row(profile: CreatorProfile) -> dict:
    return {
        "username": profile.username,
        "handle": profile.display_username or profile.username,
        "method": profile.payout_method or "",
        "destination": profile.payout_destination or "",
        "confirmed": bool(profile.payout_confirmed_by_creator),
        "flagged": bool(profile.payout_change_flagged),
        "has_link": bool(profile.payout_token),
        "updated_at": (
            profile.payout_updated_at.isoformat() if profile.payout_updated_at else ""
        ),
    }


def admin_overview(session) -> dict:
    profiles = session.execute(select(CreatorProfile)).scalars().all()
    rows = sorted(
        (admin_row(p) for p in profiles),
        key=lambda r: (not r["flagged"], r["updated_at"] == "", r["handle"].lower()),
    )
    return {
        "creators": rows,
        "summary": {
            "total": len(rows),
            "confirmed": sum(r["confirmed"] for r in rows),
            "unconfirmed_on_file": sum(bool(r["destination"]) and not r["confirmed"] for r in rows),
            "missing": sum(not r["destination"] for r in rows),
            "flagged": sum(r["flagged"] for r in rows),
            "links_issued": sum(r["has_link"] for r in rows),
        },
    }


def events_for(session, username: str, limit: int = 50) -> list[dict]:
    rows = session.execute(
        select(CreatorPayoutEvent)
        .where(CreatorPayoutEvent.username == normalize_username(username))
        .order_by(CreatorPayoutEvent.created_at.desc(), CreatorPayoutEvent.id.desc())
        .limit(limit)
    ).scalars().all()
    return [r.to_dict() for r in rows]
