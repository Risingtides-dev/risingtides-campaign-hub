#!/usr/bin/env python3
"""Smoke test: run sync_master_pages against the real Notion database.

Pulls every page from Notion's Master Pages DB and mirrors it into
``notion_master_pages``. Writes a row to ``notion_sync_log``. Idempotent;
safe to run multiple times in a row.

Required env vars:
    NOTION_API_KEY   — Notion integration token (already on Railway prod)
    DATABASE_URL     — Postgres connection string

Usage:
    DATABASE_URL=... NOTION_API_KEY=... python scripts/notion_sync_smoke.py

Or via Railway:
    railway run --service Postgres -- env DATABASE_URL=$DATABASE_PUBLIC_URL \\
        NOTION_API_KEY=... python scripts/notion_sync_smoke.py

NOT run as part of CI or the PR — manual verification only.
"""
from __future__ import annotations

import json
import os
import sys

from campaign_manager import db as _db
from campaign_manager.services.notion_sync import sync_master_pages


def main() -> int:
    if not os.environ.get("NOTION_API_KEY"):
        print("ERROR: NOTION_API_KEY is not set.", file=sys.stderr)
        return 1
    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    _db.init()
    result = sync_master_pages(triggered_by="manual:smoke")

    payload = {
        "pages_fetched": result.pages_fetched,
        "pages_added": result.pages_added,
        "pages_updated": result.pages_updated,
        "pages_deleted": result.pages_deleted,
        "errors": result.errors,
        "sync_log_id": result.sync_log_id,
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0 if not result.errors else 2


if __name__ == "__main__":
    sys.exit(main())
