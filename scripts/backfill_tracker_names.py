#!/usr/bin/env python3
"""backfill_tracker_names.py — one-shot backfill for RTA-41.

Every row in ``tracker_campaign_links`` needs a corresponding row in
``tracker_names`` so the Tides Tracker public API integration (RTA-40
epic) can resolve campaigns by display name. The link-creation path
historically wrote to ``tracker_campaign_links`` only, leaving
``tracker_names`` empty for ~45/49 links.

This script reconciles the gap. For each tracker_id present in
``tracker_campaign_links`` but missing from ``tracker_names`` it
inserts a row sourced from:

    1. The live TidesTracker API name (preferred — authoritative).
    2. The linked Campaign Hub campaign's title (fallback).
    3. Skipped with a warning if neither resolves.

Idempotent: rerunning is a no-op once data is consistent. Existing
``tracker_names`` overrides are never modified.

Usage::

    DATABASE_URL=postgres://... \
    TIDESTRACKER_API_URL=https://... \
    TIDESTRACKER_SERVICE_KEY=... \
        python scripts/backfill_tracker_names.py

    # Inspect without writing
    DATABASE_URL=... python scripts/backfill_tracker_names.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List

# Import the app modules. Adding the project root to sys.path mirrors
# how scripts/notion_sync_smoke.py bootstraps.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from campaign_manager import db as _db  # noqa: E402
from campaign_manager.models import (  # noqa: E402
    Campaign,
    TrackerCampaignLink,
    TrackerName,
)


def _load_tracker_name_index() -> Dict[str, str]:
    """Pull {tracker_id: name} from the live TidesTracker API.

    Returns an empty dict if the API is unreachable or unconfigured —
    the script then relies entirely on the Campaign title fallback.
    """
    try:
        from campaign_manager.services.tidestracker import (
            list_tracker_campaigns,
            TidesTrackerError,
        )
    except Exception as e:  # pragma: no cover - import-time config error
        print(f"  ! could not import tidestracker service: {e}", file=sys.stderr)
        return {}

    try:
        rows = list_tracker_campaigns()
    except TidesTrackerError as e:
        print(f"  ! TidesTracker API unavailable ({e}); using campaign-title fallback only.",
              file=sys.stderr)
        return {}

    out: Dict[str, str] = {}
    for r in rows:
        tid = (r.get("id") or "").strip()
        name = (r.get("name") or "").strip()
        if tid and name:
            out[tid] = name
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill missing tracker_names rows from tracker_campaign_links (RTA-41).",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be inserted without writing.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                        help="Postgres connection string (default: $DATABASE_URL).")
    args = parser.parse_args()

    if not args.database_url:
        print("ERROR: DATABASE_URL not set and --database-url not provided.", file=sys.stderr)
        return 1

    # Wire campaign_manager.db to the supplied URL.
    os.environ["DATABASE_URL"] = args.database_url
    _db.init()

    # Pre-load live TidesTracker names so we don't make N HTTP calls.
    tracker_name_index = _load_tracker_name_index()

    inserted: List[str] = []
    skipped_no_source: List[str] = []
    already_present: List[str] = []

    with _db.get_session() as s:
        link_rows = s.query(
            TrackerCampaignLink.tracker_id,
            TrackerCampaignLink.campaign_slug,
        ).all()

        if not link_rows:
            print("No rows in tracker_campaign_links. Nothing to do.")
            return 0

        existing_name_ids = {
            tid for (tid,) in s.query(TrackerName.tracker_id).all()
        }

        for tid, slug in link_rows:
            tid_clean = (tid or "").strip()
            if not tid_clean:
                continue
            if tid_clean in existing_name_ids:
                already_present.append(tid_clean)
                continue

            name = tracker_name_index.get(tid_clean, "").strip()
            if not name and slug:
                c = s.query(Campaign).filter_by(slug=slug).first()
                if c:
                    name = (c.title or c.name or "").strip()

            if not name:
                skipped_no_source.append(tid_clean)
                print(f"  ! skip {tid_clean}: no name in TidesTracker and no campaign title for slug={slug!r}",
                      file=sys.stderr)
                continue

            print(f"  + {tid_clean} -> {name!r}  (linked to campaign {slug!r})")
            if not args.dry_run:
                s.add(TrackerName(tracker_id=tid_clean, display_name=name))
            inserted.append(tid_clean)

        if args.dry_run:
            print(f"\nDRY RUN: would insert {len(inserted)} row(s). "
                  f"{len(already_present)} already had names. "
                  f"{len(skipped_no_source)} unresolvable.")
            s.rollback()
        else:
            s.commit()
            print(f"\nDone: inserted {len(inserted)} row(s). "
                  f"{len(already_present)} already had names. "
                  f"{len(skipped_no_source)} unresolvable (need manual rename or a TidesTracker fetch).")

        # Loud, scannable summary of trackers that need manual attention.
        # Easier to copy into a Linear comment than re-running the script.
        if skipped_no_source:
            print("\nUnresolvable tracker_ids (no TidesTracker name, no campaign title):",
                  file=sys.stderr)
            for tid in skipped_no_source:
                print(f"  - {tid}", file=sys.stderr)

    # Non-zero exit when any link couldn't be resolved so automation
    # wrappers (and the human running this) notice. The resolved rows
    # still committed — this signals "partial success, manual cleanup
    # needed for the list above", not "rollback everything".
    return 0 if not skipped_no_source else 2


if __name__ == "__main__":
    sys.exit(main())
