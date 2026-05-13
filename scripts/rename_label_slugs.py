#!/usr/bin/env python3
"""rename_label_slugs.py — one-shot DB migration for RTA-5.

Renames `internal_creator_groups.slug` values to drop the legacy `_pages`
suffix on label-axis slugs. Notion's `Group` field (slugified) is now the
canonical source of truth for label slugs (RTA-5 / RTA-8).

Renames (idempotent):
    warner_pages       -> warner
    atlantic_pages     -> atlantic
    warner_test_pages  -> warner_test
    seeno_pages        -> seeno

Booker slugs (jake_balik, john_smathers, sam_hudgens, eric_cromartie,
johnny_balik) already match Notion's `Poster` field via slugify() and need
no change.

Usage:
    DATABASE_URL=postgres://... python scripts/rename_label_slugs.py
    DATABASE_URL=postgres://... python scripts/rename_label_slugs.py --dry-run

Safe to run multiple times — rows already renamed are a no-op.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Tuple

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover
    print("ERROR: psycopg2 not installed. `pip install psycopg2-binary`", file=sys.stderr)
    sys.exit(1)


RENAMES: List[Tuple[str, str]] = [
    ("warner_pages", "warner"),
    ("atlantic_pages", "atlantic"),
    ("warner_test_pages", "warner_test"),
    ("seeno_pages", "seeno"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Rename legacy label slugs in internal_creator_groups.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                        help="Postgres connection string (default: $DATABASE_URL).")
    args = parser.parse_args()

    if not args.database_url:
        print("ERROR: DATABASE_URL not set and --database-url not provided.", file=sys.stderr)
        return 1

    conn = psycopg2.connect(args.database_url)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            total_renamed = 0
            for old_slug, new_slug in RENAMES:
                cur.execute(
                    "SELECT id, slug, title FROM internal_creator_groups WHERE slug = %s",
                    (old_slug,),
                )
                rows = cur.fetchall()
                if not rows:
                    print(f"  = no rows with slug={old_slug!r} (already renamed or never existed)")
                    continue

                # Defensive: don't collide if the target already exists.
                cur.execute(
                    "SELECT id FROM internal_creator_groups WHERE slug = %s",
                    (new_slug,),
                )
                if cur.fetchone():
                    print(
                        f"  ! cannot rename {old_slug!r} -> {new_slug!r}: target slug already exists. "
                        f"Manual review required.",
                        file=sys.stderr,
                    )
                    continue

                for row in rows:
                    print(f"  -> id={row['id']} {old_slug!r} -> {new_slug!r}  (title={row['title']!r})")
                    if not args.dry_run:
                        cur.execute(
                            "UPDATE internal_creator_groups SET slug = %s WHERE id = %s",
                            (new_slug, row["id"]),
                        )
                    total_renamed += 1

            if args.dry_run:
                print(f"\nDRY RUN: would rename {total_renamed} row(s). No changes committed.")
                conn.rollback()
            else:
                conn.commit()
                print(f"\nDone: renamed {total_renamed} row(s). Committed.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
