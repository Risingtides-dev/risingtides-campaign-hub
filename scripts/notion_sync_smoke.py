#!/usr/bin/env python3
"""Smoke test: run sync_master_pages (and optionally resolve_memberships)
against the real Notion database.

Pulls every page from Notion's Master Pages DB and mirrors it into
``notion_master_pages``. Writes a row to ``notion_sync_log``. Idempotent;
safe to run multiple times in a row.

With ``--resolve``, chains a second stage that reconciles
``internal_creator_group_members`` against the mirror — same flow the
RTA-10 cron will use. The membership counts are layered onto the same
sync_log row produced by the sync stage.

Required env vars:
    NOTION_API_KEY   — Notion integration token (already on Railway prod)
    DATABASE_URL     — Postgres connection string

Usage:
    DATABASE_URL=... NOTION_API_KEY=... python scripts/notion_sync_smoke.py
    DATABASE_URL=... NOTION_API_KEY=... python scripts/notion_sync_smoke.py --resolve

NOT run as part of CI or the PR — manual verification only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from campaign_manager import db as _db
from campaign_manager.services.notion_sync import (
    resolve_memberships,
    sync_master_pages,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Notion sync (and optionally resolve).")
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="After the sync, also run resolve_memberships and chain it onto "
             "the same sync_log row.",
    )
    args = parser.parse_args()

    if not os.environ.get("NOTION_API_KEY"):
        print("ERROR: NOTION_API_KEY is not set.", file=sys.stderr)
        return 1
    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    _db.init()
    sync_result = sync_master_pages(triggered_by="manual:smoke")

    payload = {
        "sync": {
            "pages_fetched": sync_result.pages_fetched,
            "pages_added": sync_result.pages_added,
            "pages_updated": sync_result.pages_updated,
            "pages_deleted": sync_result.pages_deleted,
            "errors": sync_result.errors,
            "sync_log_id": sync_result.sync_log_id,
        }
    }

    rc = 0 if not sync_result.errors else 2

    if args.resolve:
        # Skip resolve if the sync itself failed to fetch — there's nothing
        # new for the resolver to read in that case.
        if sync_result.pages_fetched == 0 and any(
            e.get("error_kind") == "fetch_failed" for e in sync_result.errors
        ):
            print(json.dumps(payload, indent=2, default=str))
            print("Skipping resolve: sync did not successfully fetch.", file=sys.stderr)
            return rc

        resolve_result = resolve_memberships(
            triggered_by="manual:smoke",
            sync_log_id=sync_result.sync_log_id or None,
        )
        payload["resolve"] = {
            "rows_processed": resolve_result.rows_processed,
            "memberships_added": resolve_result.memberships_added,
            "memberships_removed": resolve_result.memberships_removed,
            "groups_created": resolve_result.groups_created,
            "errors": resolve_result.errors,
            "sync_log_id": resolve_result.sync_log_id,
        }
        # The resolver tolerates per-row issues (no_attribution etc.) so we
        # don't fail the script on them; only a real `resolve_failed` is
        # worth a non-zero exit.
        if any(e.get("error_kind") == "resolve_failed" for e in resolve_result.errors):
            rc = max(rc, 2)

    print(json.dumps(payload, indent=2, default=str))
    return rc


if __name__ == "__main__":
    sys.exit(main())
