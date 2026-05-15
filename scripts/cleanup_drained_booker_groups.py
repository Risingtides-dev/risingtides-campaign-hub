#!/usr/bin/env python3
"""cleanup_drained_booker_groups.py — one-shot DB cleanup for RTA-11.

Deletes `internal_creator_groups` rows where `kind='booked_by'` AND the
group has zero memberships in `internal_creator_group_members`. These
are typically legacy short-name booker slugs (e.g. `smathers`, `jake`,
`heather`) that drained after the Poster field on Notion's Master Pages
DB was normalized to full names ("John Smathers", "Jake Balik", etc.)
and the RTA-9 membership resolver re-attached everyone to the
full-name groups.

SAFETY:
- Only deletes groups with `kind='booked_by'`. Label-kind groups
  (`warner`, `atlantic`) and custom-kind groups (`general`) are
  never touched.
- Only deletes groups with zero memberships. The check is re-run
  inside the same transaction as each DELETE, so a membership inserted
  between the candidate scan and the delete window aborts that row's
  delete.
- The DELETE itself filters on `kind='booked_by'` again — a typo or
  race that flipped the kind cannot escape into a label/custom group.

Idempotent — a second run finds nothing to delete and is a no-op.

Usage:
    DATABASE_URL=postgres://... python scripts/cleanup_drained_booker_groups.py --dry-run
    DATABASE_URL=postgres://... python scripts/cleanup_drained_booker_groups.py

Related:
    - scripts/rename_label_slugs.py        (RTA-5, same pattern)
    - scripts/notion_sync_smoke.py         (RTA-8/9, populates the data this drains)
    - campaign_manager/services/notion_sync.py:resolve_memberships
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover
    print("ERROR: psycopg2 not installed. `pip install psycopg2-binary`", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete drained booked_by groups in internal_creator_groups.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres connection string (default: $DATABASE_URL).",
    )
    args = parser.parse_args()

    if not args.database_url:
        print(
            "ERROR: DATABASE_URL not set and --database-url not provided.",
            file=sys.stderr,
        )
        return 1

    conn = psycopg2.connect(args.database_url)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Candidates: kind='booked_by' AND zero memberships.
            cur.execute(
                """
                SELECT g.id, g.slug, g.title
                FROM internal_creator_groups g
                WHERE g.kind = 'booked_by'
                  AND NOT EXISTS (
                      SELECT 1 FROM internal_creator_group_members m
                      WHERE m.group_id = g.id
                  )
                ORDER BY g.slug
                """
            )
            candidates = cur.fetchall()

            if not candidates:
                print("No drained booker groups to delete. Nothing to do.")
                conn.rollback()
                return 0

            print(f"Found {len(candidates)} drained booker group(s):")
            for row in candidates:
                print(f"  - id={row['id']} slug={row['slug']!r} title={row['title']!r}")

            if args.dry_run:
                print(
                    f"\nDRY RUN: would delete {len(candidates)} row(s). "
                    f"No changes committed.",
                )
                conn.rollback()
                return 0

            # Live run. Per-row re-check + kind-locked DELETE so a row
            # that gained a member between the scan and the delete is
            # safely skipped, and a kind mutation (shouldn't happen, but
            # defensive) cannot leak into a label/custom group.
            deleted = 0
            skipped = []
            for row in candidates:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM internal_creator_group_members "
                    "WHERE group_id = %s",
                    (row["id"],),
                )
                if cur.fetchone()["n"] > 0:
                    skipped.append(row)
                    print(
                        f"  ! SKIP id={row['id']} slug={row['slug']!r}: "
                        f"gained a member between scan and delete"
                    )
                    continue

                cur.execute(
                    "DELETE FROM internal_creator_groups "
                    "WHERE id = %s AND kind = 'booked_by'",
                    (row["id"],),
                )
                if cur.rowcount == 1:
                    deleted += 1
                    print(f"  -> DELETED id={row['id']} slug={row['slug']!r}")
                else:
                    skipped.append(row)
                    print(
                        f"  ! SKIP id={row['id']}: delete returned "
                        f"rowcount={cur.rowcount}"
                    )

            conn.commit()
            print(
                f"\nDone: deleted {deleted} row(s), "
                f"skipped {len(skipped)} row(s). Committed.",
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
