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
- FK references in `internal_video_group_attribution` (RTA-13 audit
  side-table) are pre-checked. Any group with one or more attribution
  rows pointing at it is reported and SKIPPED, not deleted. That table
  is durable point-in-time audit history; deleting the group would
  either violate the FK (ON DELETE NO ACTION) or, with a cascade,
  nuke the audit row. Both are wrong here. A follow-up design ticket
  owns the long-term migration path.
- Each live DELETE runs inside its own SAVEPOINT so an unexpected
  constraint violation skips that row instead of aborting the whole
  transaction. Defense-in-depth against FK constraints we don't know
  about yet.

Idempotent — a second run finds nothing new to delete and is a no-op.
If an attribution row is later cleared (or the schema gains a
`replaced_by_group_id` migration path), a re-run picks up the
previously-blocked group automatically.

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

            # Pre-check FK references in the RTA-13 attribution audit
            # table. Any group with attribution rows pointing at it is
            # SKIPPED (see module docstring for the rationale).
            candidate_ids = [r["id"] for r in candidates]
            cur.execute(
                """
                SELECT group_id, COUNT(*) AS n
                FROM internal_video_group_attribution
                WHERE group_id = ANY(%s)
                GROUP BY group_id
                """,
                (candidate_ids,),
            )
            attribution_count = {r["group_id"]: r["n"] for r in cur.fetchall()}

            to_delete = [r for r in candidates if r["id"] not in attribution_count]
            to_skip_fk = [r for r in candidates if r["id"] in attribution_count]

            print(f"Found {len(candidates)} drained booker group(s):")
            print(f"  - to delete:        {len(to_delete)}")
            print(f"  - to skip (FK ref): {len(to_skip_fk)}")
            print()

            for row in to_delete:
                print(f"  + DELETE id={row['id']} slug={row['slug']!r} title={row['title']!r}")
            for row in to_skip_fk:
                n = attribution_count[row["id"]]
                print(
                    f"  - SKIP   id={row['id']} slug={row['slug']!r} title={row['title']!r}: "
                    f"{n} row(s) in internal_video_group_attribution reference this group"
                )

            if args.dry_run:
                print(
                    f"\nDRY RUN: would delete {len(to_delete)} row(s), "
                    f"skip {len(to_skip_fk)} row(s) for FK references. "
                    f"No changes committed.",
                )
                conn.rollback()
                return 0

            # Live run. Each delete runs in its own SAVEPOINT so an
            # unexpected constraint violation skips that row instead of
            # aborting the whole transaction. Per-row re-check of
            # membership count handles a member added between scan and
            # delete (rare race). The DELETE itself filters on
            # kind='booked_by' again — defense in depth.
            deleted = 0
            skipped_race = 0
            skipped_other = []
            print()
            for row in to_delete:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM internal_creator_group_members "
                    "WHERE group_id = %s",
                    (row["id"],),
                )
                if cur.fetchone()["n"] > 0:
                    skipped_race += 1
                    print(
                        f"  ! SKIP id={row['id']} slug={row['slug']!r}: "
                        f"gained a member between scan and delete"
                    )
                    continue

                cur.execute(f"SAVEPOINT sp_{row['id']}")
                try:
                    cur.execute(
                        "DELETE FROM internal_creator_groups "
                        "WHERE id = %s AND kind = 'booked_by'",
                        (row["id"],),
                    )
                    if cur.rowcount == 1:
                        cur.execute(f"RELEASE SAVEPOINT sp_{row['id']}")
                        deleted += 1
                        print(f"  -> DELETED id={row['id']} slug={row['slug']!r}")
                    else:
                        cur.execute(f"ROLLBACK TO SAVEPOINT sp_{row['id']}")
                        skipped_other.append((row, f"rowcount={cur.rowcount}"))
                        print(
                            f"  ! SKIP id={row['id']}: delete returned "
                            f"rowcount={cur.rowcount}"
                        )
                except psycopg2.Error as exc:
                    cur.execute(f"ROLLBACK TO SAVEPOINT sp_{row['id']}")
                    skipped_other.append((row, str(exc).strip()))
                    print(
                        f"  ! SKIP id={row['id']} slug={row['slug']!r}: "
                        f"{type(exc).__name__}: {str(exc).strip()}"
                    )

            conn.commit()
            print(
                f"\nDone: deleted {deleted} row(s); "
                f"skipped {len(to_skip_fk)} for FK refs, "
                f"{skipped_race} for race re-check, "
                f"{len(skipped_other)} for other errors. "
                f"Committed.",
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
