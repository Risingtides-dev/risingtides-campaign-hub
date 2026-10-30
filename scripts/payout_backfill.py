#!/usr/bin/env python3
"""payout_backfill.py — carry clean legacy payment destinations onto creator_profiles.

Rule: fill `creator_profiles.payout_destination` ONLY when a creator has
exactly one distinct value across ALL campaign rows and it parses cleanly
(email -> PayPal, $cashtag -> Cash App). Conflicted, unparseable and blank
creators are left empty — their payout link fixes them. Never guesses.

Backfilled values are marked NOT confirmed by the creator.

Dry run is the default and is read-only (READ ONLY transaction, no boot
migrations). It writes the full diff — which contains payment destinations,
i.e. PII — to a local CSV and prints only counts.

Usage (from the Hub repo, so Railway injects the DB URL):
    railway run --service Postgres python3 scripts/payout_backfill.py
    railway run --service Postgres python3 scripts/payout_backfill.py --apply

--apply only works after the Round 1 deploy has added the payout columns.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from campaign_manager.services.payout_backfill import plan_backfill  # noqa: E402

DEFAULT_OUT_DIR = Path.home() / "Desktop/Development/creator-payout-system/data"


def _engine():
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL") or ""
    if not url:
        sys.exit("No DATABASE_PUBLIC_URL / DATABASE_URL. Run via `railway run --service Postgres`.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url)


def _has_payout_columns(conn) -> bool:
    cols = {c["name"] for c in inspect(conn).get_columns("creator_profiles")}
    return {"payout_destination", "payout_method"} <= cols


def _load(conn):
    rows = conn.execute(text("SELECT username, paypal_email FROM creators")).all()
    if _has_payout_columns(conn):
        prof = conn.execute(text(
            "SELECT username, COALESCE(payout_destination, '') FROM creator_profiles"
        )).all()
    else:
        prof = [(u, "") for (u,) in conn.execute(text("SELECT username FROM creator_profiles")).all()]
    return [(r[0], r[1]) for r in rows], {u: d for u, d in prof}


def _write_diff(plan, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"backfill_diff_{datetime.now():%Y-%m-%d_%H%M}.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["creator", "action", "method", "destination", "detail"])
        for user, dest in sorted(plan.to_fill.items()):
            w.writerow([user, "FILL", dest.method, dest.destination, ""])
        for user, values in sorted(plan.conflicted.items()):
            w.writerow([user, "SKIP_CONFLICTED", "", "", " | ".join(values)])
        for user, raw in sorted(plan.unparseable.items()):
            w.writerow([user, "SKIP_UNPARSEABLE", "", "", raw])
        for user in plan.already_set:
            w.writerow([user, "SKIP_ALREADY_SET", "", "", ""])
        for user in plan.no_profile:
            w.writerow([user, "SKIP_NO_PROFILE", "", "", ""])
        for user in plan.no_destination:
            w.writerow([user, "NEEDS_LINK", "", "", ""])
    path.chmod(0o600)
    return path


def _apply(conn, plan) -> int:
    filled = 0
    now = datetime.now()
    for user, dest in sorted(plan.to_fill.items()):
        result = conn.execute(text(
            "UPDATE creator_profiles SET payout_method = :m, payout_destination = :d, "
            "payout_updated_at = :now, payout_confirmed_by_creator = FALSE "
            "WHERE username = :u AND COALESCE(payout_destination, '') = ''"
        ), {"m": dest.method, "d": dest.destination, "now": now, "u": user})
        if result.rowcount != 1:
            continue  # filled concurrently (e.g. creator used their link) — leave it
        conn.execute(text(
            "INSERT INTO creator_payout_events "
            "(username, event, source, old_method, old_destination, new_method, "
            " new_destination, client_ip, created_at) "
            "VALUES (:u, 'backfilled', 'backfill', '', '', :m, :d, '', :now)"
        ), {"u": user, "m": dest.method, "d": dest.destination, "now": now})
        filled += 1
    return filled


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                    help="where to write the diff CSV (contains PII; keep it local)")
    args = ap.parse_args(argv)

    engine = _engine()
    with engine.connect() as conn:
        if not args.apply and conn.dialect.name == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
        campaign_rows, profiles = _load(conn)
        plan = plan_backfill(campaign_rows, profiles)
        diff_path = _write_diff(plan, args.out_dir)

        print(f"{'APPLY' if args.apply else 'DRY RUN'} — {len(campaign_rows)} campaign rows, "
              f"{len(profiles)} profiles")
        for key, value in plan.summary().items():
            print(f"  {key:>15}: {value}")
        print(f"Full diff (contains payment details — keep local): {diff_path}")

        if not args.apply:
            conn.rollback()
            print("No changes written. Re-run with --apply to fill.")
            return 0
        if not _has_payout_columns(conn):
            sys.exit("Payout columns missing — deploy Round 1 first, then re-run --apply.")
        filled = _apply(conn, plan)
        conn.commit()
        print(f"Filled {filled} creator profiles (marked unconfirmed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
