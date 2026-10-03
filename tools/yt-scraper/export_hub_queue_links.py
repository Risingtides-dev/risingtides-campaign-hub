#!/usr/bin/env python3
"""Export Campaign Hub scrape-task queue links to local report files."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "output" / "local-scraper"
DEFAULT_HUB_BASE = "https://risingtides-campaign-hub-production.up.railway.app"

CSV_FIELDS = [
    "campaign_slug",
    "campaign_title",
    "artist",
    "song",
    "account",
    "url",
    "views",
    "likes",
    "timestamp",
    "first_seen_at",
    "match_strategy",
    "sound_id",
    "matched_video_id",
]


def parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def load_env() -> List[str]:
    loaded: List[str] = []
    for path in [
        OUTPUT_ROOT / ".env",
        OUTPUT_ROOT / "runtime" / "pi_node.env",
    ]:
        vals = parse_env_file(path)
        if vals:
            loaded.append(str(path))
        for key, value in vals.items():
            os.environ.setdefault(key, value)
    return loaded


def hub_base() -> str:
    raw = os.environ.get("CAMPAIGN_HUB_API_URL", "").strip() or DEFAULT_HUB_BASE
    raw = raw.rstrip("/")
    if raw.endswith("/api"):
        raw = raw[:-4]
    return raw


def queue_url(limit: int) -> str:
    return f"{hub_base()}/api/scrape-tasks/queue?{urlencode({'limit': limit})}"


def fetch_queue(limit: int) -> Dict[str, Any]:
    url = queue_url(limit)
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=45) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict) or "campaigns" not in payload:
        raise RuntimeError(f"unexpected queue payload from {url}")
    payload["_source_url"] = url
    return payload


def safe_slug(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip())
    clean = "_".join(part for part in clean.split("_") if part)
    return clean.lower() or "campaign"


def flatten_campaigns(campaigns: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for campaign in campaigns:
        slug = str(campaign.get("slug") or "")
        title = str(campaign.get("title") or slug)
        artist = str(campaign.get("artist") or "")
        campaign_song = str(campaign.get("song") or "")
        for video in campaign.get("videos") or []:
            url = str(video.get("url") or "").strip()
            if not url:
                continue
            rows.append({
                "campaign_slug": slug,
                "campaign_title": title,
                "artist": artist,
                "song": campaign_song or str(video.get("song") or ""),
                "account": str(video.get("account") or ""),
                "url": url,
                "views": int(video.get("views") or 0),
                "likes": int(video.get("likes") or 0),
                "timestamp": str(video.get("timestamp") or ""),
                "first_seen_at": str(video.get("first_seen_at") or ""),
                "match_strategy": str(video.get("match_strategy") or campaign.get("match_strategy") or ""),
                "sound_id": str(video.get("extracted_sound_id") or ""),
                "matched_video_id": str(video.get("id") or ""),
            })
    return rows


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def write_plain_links(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.write_text("".join(f"{row['url']}\n" for row in rows), encoding="utf-8")


def write_grouped_links(path: Path, campaigns: List[Dict[str, Any]]) -> None:
    lines: List[str] = []
    for campaign in campaigns:
        videos = [v for v in campaign.get("videos") or [] if v.get("url")]
        if not videos:
            continue
        title = str(campaign.get("title") or campaign.get("slug") or "Campaign")
        lines.extend([title, "-" * len(title)])
        for video in videos:
            account = str(video.get("account") or "").strip()
            prefix = f"{account} " if account else ""
            lines.append(f"{prefix}{video.get('url')}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_by_account(path: Path, videos: List[Dict[str, Any]]) -> None:
    by_account: Dict[str, List[str]] = {}
    for video in videos:
        url = str(video.get("url") or "").strip()
        if not url:
            continue
        account = str(video.get("account") or "@unknown").strip() or "@unknown"
        by_account.setdefault(account, []).append(url)

    lines: List[str] = []
    for account in sorted(by_account):
        lines.extend([account, "-" * len(account)])
        lines.extend(by_account[account])
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_campaign_dirs(output_dir: Path, campaigns: List[Dict[str, Any]]) -> None:
    for campaign in campaigns:
        videos = campaign.get("videos") or []
        if not videos:
            continue
        slug = safe_slug(str(campaign.get("slug") or campaign.get("title") or "campaign"))
        campaign_dir = output_dir / slug
        campaign_dir.mkdir(parents=True, exist_ok=True)
        (campaign_dir / "queue_links.json").write_text(
            json.dumps(campaign, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        write_plain_links(campaign_dir / "post_links_copy_paste.txt", flatten_campaigns([campaign]))
        write_by_account(campaign_dir / "post_links_by_account.txt", videos)


def record_run(output_root: Path, summary: Dict[str, Any], status: str = "completed", error: str = "") -> None:
    db_path = output_root / "scrape_records.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scrape_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              output_dir TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL,
              source TEXT NOT NULL,
              generated_at TEXT NOT NULL,
              recorded_at TEXT NOT NULL,
              campaigns INTEGER NOT NULL DEFAULT 0,
              links_exported INTEGER NOT NULL DEFAULT 0,
              total_untracked_reported INTEGER NOT NULL DEFAULT 0,
              summary_json TEXT NOT NULL DEFAULT '{}',
              error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scrape_runs_recorded_at ON scrape_runs(recorded_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scrape_runs_generated_at ON scrape_runs(generated_at DESC)"
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO scrape_runs
              (output_dir, status, source, generated_at, recorded_at, campaigns,
               links_exported, total_untracked_reported, summary_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(summary.get("output_dir") or ""),
                status,
                "export_hub_queue_links",
                str(summary.get("generated_at") or ""),
                datetime.now(timezone.utc).isoformat(),
                int(summary.get("campaigns") or 0),
                int(summary.get("links_exported") or 0),
                int(summary.get("total_untracked_reported") or 0),
                json.dumps(summary.get("summary") or []),
                error,
            ),
        )
        conn.commit()


def export_queue(output_root: Path, limit: int) -> Dict[str, Any]:
    load_env()
    payload = fetch_queue(limit)
    campaigns = list(payload.get("campaigns") or [])
    rows = flatten_campaigns(campaigns)
    generated_at = datetime.now().isoformat()
    output_dir = output_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    write_csv(output_dir / "all_untracked_links.csv", rows)
    write_plain_links(output_dir / "all_post_links_copy_paste.txt", rows)
    write_grouped_links(output_dir / "all_post_links_grouped.txt", campaigns)
    write_campaign_dirs(output_dir, campaigns)

    summary = {
        "generated_at": generated_at,
        "source": payload.get("_source_url") or queue_url(limit),
        "output_dir": str(output_dir.relative_to(ROOT)),
        "campaigns": len(campaigns),
        "total_untracked_reported": int(payload.get("total_untracked") or 0),
        "links_exported": len(rows),
        "summary": [
            {
                "campaign_slug": str(c.get("slug") or ""),
                "campaign_title": str(c.get("title") or c.get("slug") or ""),
                "untracked_count": int(c.get("untracked_count") or 0),
                "exported_links": len([v for v in c.get("videos") or [] if v.get("url")]),
            }
            for c in campaigns
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "output_dir"}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    record_run(output_root, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT / "hub_queue_export"))
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    summary = export_queue(Path(args.output_root), args.limit)
    print(json.dumps({
        "output_dir": summary["output_dir"],
        "campaigns": summary["campaigns"],
        "links_exported": summary["links_exported"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
