"""Plan the one-time payout backfill from legacy campaign rows.

Rule (01-PLAN.md, Deliverable 3): carry a destination over to
`creator_profiles` ONLY when a creator has exactly one distinct value across
ALL their campaign rows, and that value parses cleanly (email or $cashtag).
Anything else is left blank for the creator to fill in via their link.
Never guess.

`plan_backfill` is pure so the dry run is testable without a database.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

from campaign_manager.services.creator_library import normalize_username
from campaign_manager.services.payout_validation import Destination, classify_legacy_value


@dataclass(frozen=True)
class BackfillPlan:
    to_fill: dict = field(default_factory=dict)        # username -> Destination
    conflicted: dict = field(default_factory=dict)     # username -> sorted raw values
    unparseable: dict = field(default_factory=dict)    # username -> raw value
    no_destination: tuple = ()                         # usernames
    already_set: tuple = ()                            # profile already has one
    no_profile: tuple = ()                             # would fill, but no profile row

    def summary(self) -> dict:
        return {
            "to_fill": len(self.to_fill),
            "conflicted": len(self.conflicted),
            "unparseable": len(self.unparseable),
            "no_destination": len(self.no_destination),
            "already_set": len(self.already_set),
            "no_profile": len(self.no_profile),
        }


def _distinct_values(rows: Iterable[tuple]) -> dict[str, set]:
    values: dict[str, set] = defaultdict(set)
    for username, raw in rows:
        user = normalize_username(username)
        if not user:
            continue
        cleaned = str(raw or "").strip().lower()
        values[user]  # every creator gets a key, even with nothing on file
        if cleaned:
            values[user].add(cleaned)
    return values


def plan_backfill(
    campaign_rows: Iterable[tuple],
    profiles: dict[str, Optional[str]],
) -> BackfillPlan:
    """campaign_rows: (username, legacy paypal_email) for EVERY campaign row.
    profiles: normalized username -> current payout_destination ('' if none).
    """
    to_fill, conflicted, unparseable = {}, {}, {}
    no_destination, already_set, no_profile = [], [], []

    for user, values in sorted(_distinct_values(campaign_rows).items()):
        if not values:
            no_destination.append(user)
            continue
        if len(values) > 1:
            conflicted[user] = sorted(values)
            continue
        (raw,) = values
        parsed: Optional[Destination] = classify_legacy_value(raw)
        if parsed is None:
            unparseable[user] = raw
            continue
        if user not in profiles:
            no_profile.append(user)
            continue
        if profiles[user]:
            already_set.append(user)
            continue
        to_fill[user] = parsed

    return BackfillPlan(
        to_fill=to_fill,
        conflicted=conflicted,
        unparseable=unparseable,
        no_destination=tuple(no_destination),
        already_set=tuple(already_set),
        no_profile=tuple(no_profile),
    )
