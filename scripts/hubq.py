#!/usr/bin/env python3
"""Hub DB query helper.

Usage:
    cd ~/Projects/risingtides-campaign-hub && railway run --service Postgres \
        python3 scripts/hubq.py <subcommand> [args]

Subcommands:
    tables                              List all tables
    cols <table>                        List columns + types for a table
    rows <table> [limit]                First N rows of a table
    sql "<query>"                       Run an arbitrary SQL query
    campaign <slug>                     Inspect campaign + creators + matched videos
    matches <slug>                      All matched_videos rows for a campaign (incl dismissed)
    sync <slug>                         Tides tracker sync log entries for a campaign
"""
from __future__ import annotations
import os
import sys
import json
import psycopg2
import psycopg2.extras


def conn():
    return psycopg2.connect(os.environ["DATABASE_PUBLIC_URL"], connect_timeout=15)


def _fmt(rows, cols):
    if not rows:
        print("(no rows)")
        return
    widths = [
        max(len(str(c)), max((len(str(r[i])) for r in rows), default=0))
        for i, c in enumerate(cols)
    ]
    widths = [min(w, 60) for w in widths]
    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    print(header)
    print("-" * len(header))
    for r in rows:
        print(" | ".join(str(r[i])[:60].ljust(widths[i]) for i in range(len(cols))))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd, *args = sys.argv[1:]
    with conn() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if cmd == "tables":
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1")
            for r in cur.fetchall():
                print(r["table_name"])
        elif cmd == "cols":
            cur.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (args[0],),
            )
            rows = cur.fetchall()
            for r in rows:
                print(f"  {r['column_name']:<32} {r['data_type']:<22} {'NULL' if r['is_nullable']=='YES' else 'NOT NULL'}")
        elif cmd == "rows":
            limit = int(args[1]) if len(args) > 1 else 5
            cur.execute(f"SELECT * FROM {args[0]} LIMIT %s", (limit,))
            rows = cur.fetchall()
            for r in rows:
                print(json.dumps(dict(r), default=str, indent=2))
                print()
        elif cmd == "sql":
            cur.execute(args[0])
            try:
                rows = cur.fetchall()
            except psycopg2.ProgrammingError:
                print("OK (no result)")
                return 0
            for r in rows:
                print(json.dumps(dict(r), default=str))
        elif cmd == "campaign":
            slug = args[0]
            cur.execute("SELECT * FROM campaigns WHERE slug=%s", (slug,))
            c_row = cur.fetchone()
            if not c_row:
                print("not found")
                return 1
            print("=== campaign ===")
            for k, v in c_row.items():
                if v in (None, "", [], {}):
                    continue
                print(f"  {k}: {str(v)[:200]}")
            print()
            cur.execute("SELECT * FROM creators WHERE campaign_slug=%s ORDER BY username", (slug,))
            creators = cur.fetchall()
            print(f"=== creators ({len(creators)}) ===")
            print(f"  {'username':<30} {'owed':>5} {'done':>5} {'matched':>7} {'status':<12} {'paid':<10}")
            for cr in creators:
                print(f"  {cr.get('username',''):<30} {cr.get('posts_owed',0) or 0:>5} {cr.get('posts_done',0) or 0:>5} {cr.get('posts_matched',0) or 0:>7} {(cr.get('status') or '')[:12]:<12} {(cr.get('paid') or '')[:10]:<10}")
            print()
            cur.execute(
                "SELECT id, account, url, dismissed_at, dismissed_reason, match_strategy, views, "
                "upload_date, first_seen_at, song, extracted_sound_id "
                "FROM matched_videos WHERE campaign_slug=%s ORDER BY first_seen_at DESC NULLS LAST",
                (slug,),
            )
            mvs = cur.fetchall()
            live = [r for r in mvs if not r.get("dismissed_at")]
            dismissed = [r for r in mvs if r.get("dismissed_at")]
            print(f"=== matched_videos ({len(mvs)} total: {len(live)} live, {len(dismissed)} dismissed) ===")
        elif cmd == "matches":
            slug = args[0]
            cur.execute(
                "SELECT id, account, url, dismissed_at, dismissed_reason, match_strategy, views, "
                "upload_date, first_seen_at, song "
                "FROM matched_videos WHERE campaign_slug=%s ORDER BY dismissed_at NULLS FIRST, first_seen_at DESC NULLS LAST",
                (slug,),
            )
            rows = cur.fetchall()
            for r in rows:
                tag = "DISMISSED" if r.get("dismissed_at") else "live"
                strat = r.get("match_strategy") or "?"
                print(f"  [{tag:9}] {r['account']:<30} {strat:<25} {r.get('views') or 0:>8} {r['url']}")
                if r.get("dismissed_at"):
                    print(f"      reason: {r.get('dismissed_reason')}")
        elif cmd == "sync":
            slug = args[0]
            cur.execute(
                "SELECT * FROM tides_tracker_sync_log WHERE campaign_slug=%s ORDER BY created_at DESC LIMIT 20",
                (slug,),
            )
            rows = cur.fetchall()
            print(f"=== tides_tracker_sync_log ({len(rows)} entries) ===")
            for r in rows:
                print(json.dumps(dict(r), default=str, indent=2))
                print()
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
