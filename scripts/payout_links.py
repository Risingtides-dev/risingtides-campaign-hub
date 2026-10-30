#!/usr/bin/env python3
"""payout_links.py — print per-creator payout links + DM text, in Jake's voice.

Issues a token for any creator that doesn't have one yet; re-running prints
the same link (use --rotate to kill a possibly-leaked link and issue a new one).

DM wording comes from the `payout.link` template in the scrape skill's
dm_templates.json, so it can be edited with no code change.

Usage (from the Hub repo, after the Round 1 deploy):
    railway run --service Postgres python3 scripts/payout_links.py truckquotes45 rrottinaway
    railway run --service Postgres python3 scripts/payout_links.py \\
        --csv ~/Desktop/Development/creator-payout-system/data/creators_with_no_destination.csv

Output is tab-separated: handle, link, DM text. Links are bearer
credentials — paste them into the creator's DM only.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from campaign_manager.services import payout_profiles as payouts  # noqa: E402

TEMPLATES = Path.home() / ".claude/skills/rising-tides-scrape/state/dm_templates.json"
DEFAULT_TEMPLATE = (
    "hey twin drop your payment info here so i can get you paid as soon as "
    "your posts are up 🙂\n{link}"
)
DEFAULT_BASE = os.environ.get("PUBLIC_BASE_URL", "https://campaignhub.risingtidesviral.com")


def _template() -> str:
    try:
        return json.loads(TEMPLATES.read_text())["payout"]["link"]
    except (OSError, KeyError, TypeError, ValueError):
        return DEFAULT_TEMPLATE


def _session():
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL") or ""
    if not url:
        sys.exit("No DATABASE_PUBLIC_URL / DATABASE_URL. Run via `railway run --service Postgres`.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return sessionmaker(bind=create_engine(url))()


def _usernames(args) -> list[str]:
    names = list(args.usernames)
    if args.csv:
        with open(Path(args.csv).expanduser(), newline="") as fh:
            names += [row[args.column] for row in csv.DictReader(fh) if row.get(args.column)]
    seen, out = set(), []
    for n in names:
        key = n.strip().lstrip("@").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(n.strip())
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("usernames", nargs="*")
    ap.add_argument("--csv", help="CSV with a creator column")
    ap.add_argument("--column", default="creator")
    ap.add_argument("--rotate", action="store_true", help="replace existing links (old ones stop working)")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    args = ap.parse_args(argv)

    names = _usernames(args)
    if not names:
        ap.error("give usernames or --csv")

    template = _template()
    session = _session()
    try:
        for name in names:
            profile, _ = payouts.issue_token(session, name, rotate=args.rotate)
            link = payouts.build_link(args.base_url, profile.payout_token)
            dm = template.format(link=link, handle=profile.display_username or profile.username)
            print("\t".join([f"@{profile.username}", link, dm.replace("\n", "\\n")]))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
