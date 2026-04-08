#!/usr/bin/env python3
"""internal_groups_cli.py — manage internal creator groups on the Campaign Hub.

Talks to the Campaign Hub REST API (defaults to Railway production). Use it
to create groups, add members, and inspect per-group / per-creator stats
without needing direct DB access.

Usage:
    python scripts/internal_groups_cli.py list
    python scripts/internal_groups_cli.py create-group <slug> "<title>" [--kind booked_by|label|niche|custom] [--sort N]
    python scripts/internal_groups_cli.py show <slug>
    python scripts/internal_groups_cli.py add-members <slug> @user1 @user2 ...
    python scripts/internal_groups_cli.py remove-member <slug> @username
    python scripts/internal_groups_cli.py delete-group <slug>
    python scripts/internal_groups_cli.py stats --group <slug> [--days 30]
    python scripts/internal_groups_cli.py stats --creator @username [--days 30]
    python scripts/internal_groups_cli.py seed                # create the default 7 groups + members

Environment:
    CAMPAIGN_HUB_API  base URL (default: Railway production)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import requests

DEFAULT_BASE = os.environ.get(
    "CAMPAIGN_HUB_API",
    "https://risingtides-campaign-hub-production.up.railway.app",
).rstrip("/")

TIMEOUT = 30


# ---------------------------------------------------------------------------
# Default seed — the 7 groups Jake defined plus their initial members
# ---------------------------------------------------------------------------
SEED_GROUPS: List[Dict[str, Any]] = [
    {
        "slug": "warner_pages",
        "title": "Warner Pages",
        "kind": "label",
        "sort_order": 10,
        "members": ["brew.pilled", "beaujenkins", "codyjames6.7",
                    "drivetoclearmymind001", "gavin.wilder1"],
    },
    {
        "slug": "johnny_balik",
        "title": "Johnny's Pages",
        "kind": "booked_by",
        "sort_order": 20,
        "members": ["notjohnnybalik", "holy.fumble"],
    },
    {
        "slug": "john_smathers",
        "title": "John's Pages",
        "kind": "booked_by",
        "sort_order": 30,
        "members": ["johnsamuelsmathers", "yellowfont.halfspeed"],
    },
    {
        "slug": "sam_hudgens",
        "title": "Sam's Pages",
        "kind": "booked_by",
        "sort_order": 40,
        "members": ["tender.acres", "buck.wilders", "boone.reynolds",
                    "between.the.lines66", "duck.therapy2"],
    },
    {
        "slug": "eric_cromartie",
        "title": "Eric's Pages",
        "kind": "booked_by",
        "sort_order": 50,
        "members": ["ericcromartie", "chafed.satin", "pinkfonthalfspeed"],
    },
    {
        "slug": "jake_balik",
        "title": "Jake's Pages",
        "kind": "booked_by",
        "sort_order": 60,
        "members": ["mr.nobodyknows", "earl.boone1", "dirtroad.drivin",
                    "trailheadtravis"],
    },
    {
        "slug": "general",
        "title": "General",
        "kind": "custom",
        "sort_order": 99,
        "members": [],  # populated dynamically from leftover creators
    },
]

# Creators explicitly assigned above — used to compute the "general" bucket.
_ASSIGNED = {
    u.lower()
    for g in SEED_GROUPS
    for u in g["members"]
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
class ApiError(Exception):
    pass


def _url(base: str, path: str) -> str:
    return f"{base}{path if path.startswith('/') else '/' + path}"


def _request(method: str, base: str, path: str, **kwargs) -> Any:
    try:
        resp = requests.request(method, _url(base, path), timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise ApiError(f"network error: {exc}") from exc
    if resp.status_code >= 500:
        raise ApiError(f"{method} {path} → HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"raw": resp.text}


def api_get(base: str, path: str, **params):
    return _request("GET", base, path, params=params or None)


def api_post(base: str, path: str, body: Dict):
    return _request("POST", base, path, json=body)


def api_patch(base: str, path: str, body: Dict):
    return _request("PATCH", base, path, json=body)


def api_delete(base: str, path: str):
    return _request("DELETE", base, path)


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------
def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _print_groups(groups: List[Dict]):
    if not groups:
        print("(no groups)")
        return
    print(f"{'slug':<20} {'title':<24} {'kind':<12} {'members':>8}")
    print("-" * 70)
    for g in groups:
        print(f"{g.get('slug',''):<20} {g.get('title',''):<24} "
              f"{g.get('kind',''):<12} {g.get('member_count',0):>8}")


def _print_group_detail(group: Dict, members: List[str]):
    print(f"Group: {group.get('title')} [{group.get('slug')}]  kind={group.get('kind')}  id={group.get('id')}")
    print(f"Members ({len(members)}):")
    if not members:
        print("  (none)")
    for m in sorted(members):
        print(f"  @{m}")


def _print_creator_stats(stats: Dict):
    print(f"@{stats.get('username')}  last {stats.get('days')} days")
    print(f"  posts: {_fmt_int(stats.get('total_posts'))}   "
          f"views: {_fmt_int(stats.get('total_views'))}   "
          f"likes: {_fmt_int(stats.get('total_likes'))}")
    by_song = stats.get("posts_by_song") or []
    if by_song:
        print("\n  Top songs:")
        print(f"  {'song':<40} {'artist':<24} {'posts':>6} {'views':>14}")
        for row in by_song[:15]:
            song = (row.get("song") or "")[:40]
            artist = (row.get("artist") or "")[:24]
            print(f"  {song:<40} {artist:<24} {row.get('posts',0):>6} {_fmt_int(row.get('views')):>14}")


def _print_group_stats(stats: Dict):
    g = stats.get("group", {})
    print(f"Group: {g.get('title')} [{g.get('slug')}]  last {stats.get('days')} days")
    print(f"  posts: {_fmt_int(stats.get('total_posts'))}   "
          f"views: {_fmt_int(stats.get('total_views'))}   "
          f"likes: {_fmt_int(stats.get('total_likes'))}")
    creators = stats.get("creators") or []
    if creators:
        print("\n  Creators (sorted by views):")
        print(f"  {'username':<28} {'posts':>6} {'views':>14}")
        for row in creators:
            print(f"  @{row.get('username',''):<27} {row.get('posts',0):>6} {_fmt_int(row.get('views')):>14}")
    top_songs = stats.get("top_songs") or []
    if top_songs:
        print("\n  Top songs in group:")
        print(f"  {'song':<40} {'artist':<24} {'posts':>6} {'views':>14}")
        for row in top_songs:
            song = (row.get("song") or "")[:40]
            artist = (row.get("artist") or "")[:24]
            print(f"  {song:<40} {artist:<24} {row.get('posts',0):>6} {_fmt_int(row.get('views')):>14}")


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------
def cmd_list(args, base):
    _, groups = api_get(base, "/api/internal/groups")
    _print_groups(groups if isinstance(groups, list) else [])


def cmd_create_group(args, base):
    status, resp = api_post(base, "/api/internal/groups", {
        "slug": args.slug,
        "title": args.title,
        "kind": args.kind,
        "sort_order": args.sort,
    })
    if status >= 400:
        print(f"ERROR: {resp.get('error', resp)}", file=sys.stderr)
        return 1
    print(f"Created group: {resp.get('title')} [{resp.get('slug')}] id={resp.get('id')}")
    return 0


def cmd_show(args, base):
    status, group = api_get(base, f"/api/internal/groups/{args.slug}")
    if status >= 400:
        print(f"ERROR: {group.get('error', group)}", file=sys.stderr)
        return 1
    members = group.get("members") or []
    _print_group_detail(group, members)
    return 0


def cmd_add_members(args, base):
    status, resp = api_post(
        base,
        f"/api/internal/groups/{_resolve_group_id(base, args.slug)}/members",
        {"usernames": args.usernames},
    )
    if status >= 400:
        print(f"ERROR: {resp.get('error', resp)}", file=sys.stderr)
        return 1
    added = resp.get("added") or []
    skipped = resp.get("skipped") or []
    print(f"Added {len(added)} member(s) to {args.slug}: {', '.join('@'+a for a in added) or '(none)'}")
    if skipped:
        print(f"Skipped (not in dashboard or already a member): {', '.join('@'+s for s in skipped)}")
    return 0


def cmd_remove_member(args, base):
    gid = _resolve_group_id(base, args.slug)
    status, resp = api_delete(base, f"/api/internal/groups/{gid}/members/{args.username.lstrip('@')}")
    if status >= 400:
        print(f"ERROR: {resp.get('error', resp)}", file=sys.stderr)
        return 1
    print(f"Removed @{args.username.lstrip('@')} from {args.slug}")
    return 0


def cmd_delete_group(args, base):
    gid = _resolve_group_id(base, args.slug)
    status, resp = api_delete(base, f"/api/internal/groups/{gid}")
    if status >= 400:
        print(f"ERROR: {resp.get('error', resp)}", file=sys.stderr)
        return 1
    print(f"Deleted group {args.slug}")
    return 0


def cmd_stats(args, base):
    if args.group:
        status, stats = api_get(base, f"/api/internal/groups/{args.group}/stats", days=args.days)
        if status >= 400:
            print(f"ERROR: {stats.get('error', stats)}", file=sys.stderr)
            return 1
        _print_group_stats(stats)
    elif args.creator:
        uname = args.creator.lstrip("@")
        status, stats = api_get(base, f"/api/internal/creators/{uname}/stats", days=args.days)
        if status >= 400:
            print(f"ERROR: {stats.get('error', stats)}", file=sys.stderr)
            return 1
        _print_creator_stats(stats)
    else:
        print("ERROR: provide either --group <slug> or --creator @username", file=sys.stderr)
        return 1
    return 0


def cmd_seed(args, base):
    """Create the 7 default groups and assign known members.

    Idempotent: existing groups are kept; members are added via the API
    which skips duplicates and unknown usernames.
    """
    # Pull the full creator roster so we can compute the "general" bucket.
    _, creators = api_get(base, "/api/internal/creators")
    all_usernames = [c.get("username", "").lower() for c in creators if isinstance(c, dict)]
    general_members = sorted(u for u in all_usernames if u and u not in _ASSIGNED)

    for group_def in SEED_GROUPS:
        slug = group_def["slug"]
        # Ensure group exists.
        status, resp = api_post(base, "/api/internal/groups", {
            "slug": slug,
            "title": group_def["title"],
            "kind": group_def["kind"],
            "sort_order": group_def["sort_order"],
        })
        if status == 201:
            print(f"  + created group {slug}")
        elif status == 409:
            print(f"  = group {slug} already exists")
        else:
            print(f"  ! failed to create {slug}: {resp}", file=sys.stderr)
            continue

        # Resolve group id after creation.
        gid = _resolve_group_id(base, slug)
        if not gid:
            print(f"  ! could not resolve id for {slug}", file=sys.stderr)
            continue

        members = list(group_def["members"])
        if slug == "general":
            members = general_members

        if not members:
            continue

        status, resp = api_post(
            base,
            f"/api/internal/groups/{gid}/members",
            {"usernames": members},
        )
        added = resp.get("added", []) if isinstance(resp, dict) else []
        skipped = resp.get("skipped", []) if isinstance(resp, dict) else []
        print(f"    → added {len(added)} / skipped {len(skipped)}")

    print("\nSeed complete. Current groups:")
    _, groups = api_get(base, "/api/internal/groups")
    _print_groups(groups if isinstance(groups, list) else [])
    return 0


def _resolve_group_id(base: str, slug: str) -> Optional[int]:
    status, group = api_get(base, f"/api/internal/groups/{slug}")
    if status >= 400 or not isinstance(group, dict):
        return None
    return group.get("id")


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="internal_groups_cli",
        description="Manage internal creator groups on the Campaign Hub.",
    )
    p.add_argument("--base", default=DEFAULT_BASE,
                   help=f"API base URL (default: {DEFAULT_BASE})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list all groups")

    cg = sub.add_parser("create-group", help="create a new group")
    cg.add_argument("slug")
    cg.add_argument("title")
    cg.add_argument("--kind", default="custom",
                    choices=["booked_by", "label", "niche", "custom"])
    cg.add_argument("--sort", type=int, default=0)

    sh = sub.add_parser("show", help="show group detail + members")
    sh.add_argument("slug")

    am = sub.add_parser("add-members", help="add members to a group")
    am.add_argument("slug")
    am.add_argument("usernames", nargs="+")

    rm = sub.add_parser("remove-member", help="remove a member from a group")
    rm.add_argument("slug")
    rm.add_argument("username")

    dg = sub.add_parser("delete-group", help="delete a group")
    dg.add_argument("slug")

    st = sub.add_parser("stats", help="show stats for a group or creator")
    st.add_argument("--group", help="group slug")
    st.add_argument("--creator", help="creator username")
    st.add_argument("--days", type=int, default=30)

    sub.add_parser("seed", help="create default 7 groups and assign members")

    return p


def main() -> int:
    args = build_parser().parse_args()
    base = args.base.rstrip("/")
    try:
        return {
            "list": cmd_list,
            "create-group": cmd_create_group,
            "show": cmd_show,
            "add-members": cmd_add_members,
            "remove-member": cmd_remove_member,
            "delete-group": cmd_delete_group,
            "stats": cmd_stats,
            "seed": cmd_seed,
        }[args.cmd](args, base) or 0
    except ApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
