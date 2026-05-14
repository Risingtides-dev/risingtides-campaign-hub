#!/usr/bin/env python3
"""Smoke test: run pull_all_trackers against the live Tides Tracker
public API (RTA-42).

Walks every tracker in ``tracker_names`` and fetches its submissions
from ``GET https://risingtides-tracker.com/api/public/<tracker_id>``.
Writes one ``tides_tracker_sync_log`` row. Idempotent; safe to run
multiple times.

With ``--tracker-id``, fetches just that one tracker (no DB write —
only ``fetch_campaign_submissions`` runs). Useful for poking at a
specific tracker's response shape.

Required env vars:
    DATABASE_URL     — Postgres connection string

Optional:
    TIDES_TRACKER_PUBLIC_BASE_URL — Override the public API base
        (defaults to https://risingtides-tracker.com).

Usage:
    DATABASE_URL=... python scripts/tides_tracker_smoke.py
    DATABASE_URL=... python scripts/tides_tracker_smoke.py --tracker-id <uuid>

NOT run as part of CI or the PR — manual verification only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Match the path-bootstrap pattern used by scripts/backfill_tracker_names.py
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from campaign_manager import db as _db  # noqa: E402
from campaign_manager.services.tides_tracker import (  # noqa: E402
    fetch_campaign_submissions,
    pull_all_trackers,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-run the Tides Tracker public-API pull (RTA-42)."
    )
    parser.add_argument(
        "--tracker-id",
        default="",
        help="Fetch a single tracker by ID (no DB write). Skips the full pull.",
    )
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    _db.init()

    if args.tracker_id:
        # Single-tracker preview — useful for inspecting payload shape.
        result = fetch_campaign_submissions(args.tracker_id)
        payload = {
            "tracker_id": result.tracker_id,
            "ok": result.ok,
            "count": result.count,
            "fetched_at": result.fetched_at,
            "error_kind": result.error_kind,
            "detail": result.detail,
            "status_code": result.status_code,
            "sample_submission": (
                result.submissions[0].to_dict() if result.submissions else None
            ),
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0 if result.ok else 2

    # Full pull across every tracker_names row.
    result = pull_all_trackers(triggered_by="manual:smoke")
    payload = {
        "trackers_total": result.trackers_total,
        "trackers_succeeded": result.trackers_succeeded,
        "trackers_failed": result.trackers_failed,
        "submissions_fetched": result.submissions_fetched,
        "sync_log_id": result.sync_log_id,
        "errors": result.errors,
    }
    print(json.dumps(payload, indent=2, default=str))

    # Non-zero exit when ALL trackers failed (so a wrapper notices). A
    # mixed run (some ok, some failed) is normal — Tides Tracker can
    # return 404 for a deleted campaign — and exits 0.
    if result.trackers_total > 0 and result.trackers_succeeded == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
