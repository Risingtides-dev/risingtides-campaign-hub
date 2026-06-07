#!/usr/bin/env python3
"""Run the local active-campaign scrape and write an ops report."""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT_ROOT = ROOT / "output" / "local-scraper"
RUNS_ROOT = OUTPUT_ROOT / "agent-runs"
LOCK_PATH = OUTPUT_ROOT / "active_campaigns_scrape.lock"
STALE_LOCK_SECONDS = 3 * 60 * 60


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def load_local_env() -> Dict[str, Any]:
    loaded_files: List[str] = []
    loaded_names: List[str] = []
    for path in [
        OUTPUT_ROOT / ".env",
        OUTPUT_ROOT / "runtime" / "pi_node.env",
    ]:
        values = parse_env_file(path)
        if values:
            loaded_files.append(str(path))
        for key, value in values.items():
            os.environ.setdefault(key, value)
            loaded_names.append(key)
    return {
        "loaded_files": loaded_files,
        "loaded_names": sorted(set(loaded_names)),
    }


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def clear_stale_lock() -> bool:
    if not LOCK_PATH.exists():
        return False
    raw = LOCK_PATH.read_text(encoding="utf-8", errors="ignore").strip()
    pid = int(raw) if raw.isdigit() else 0
    age = time.time() - LOCK_PATH.stat().st_mtime
    if (pid and not pid_is_running(pid)) or age > STALE_LOCK_SECONDS:
        LOCK_PATH.unlink()
        return True
    return False


def acquire_lock() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    clear_stale_lock()
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode("ascii"))
    return fd


def release_lock(fd: int) -> None:
    try:
        os.close(fd)
    finally:
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def latest_campaign_refresh_log() -> Dict[str, Any]:
    from campaign_manager import db as _db

    for log in _db.get_cron_logs(limit=10) or []:
        if log.get("job_type") == "campaign_refresh":
            return log
    return {}


def export_queue() -> Dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "tools/yt-scraper/export_hub_queue_links.py", "--limit", "500"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=120,
    )
    parsed: Dict[str, Any] = {}
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = {}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "parsed": parsed,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def env_snapshot(env_info: Dict[str, Any]) -> Dict[str, Any]:
    cookies_file = os.environ.get("TIKTOK_COOKIES_FILE", "").strip()
    return {
        **env_info,
        "database_url_set": bool(os.environ.get("DATABASE_URL")),
        "cookies_file_set": bool(cookies_file),
        "cookies_file_exists": bool(cookies_file and Path(cookies_file).exists()),
        "cookies_from_browser": os.environ.get("TIKTOK_COOKIES_FROM_BROWSER", "").strip(),
        "impersonation_enabled": os.environ.get("TIKTOK_IMPERSONATE", "").strip().lower() in {"1", "true", "yes"},
        "impersonation_target": os.environ.get("TIKTOK_IMPERSONATE_TARGET", "").strip(),
        "proxy_configured": bool(os.environ.get("TIKTOK_PROXY", "").strip()),
        "secret_values_redacted": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="run campaign_refresh; otherwise only preflight")
    parser.add_argument("--write-report", action="store_true", help="write report under output/local-scraper/agent-runs")
    parser.add_argument("--export", action="store_true", help="export the hydrated queue after the run")
    parser.add_argument("--no-proxy", action="store_true", help="unset TIKTOK_PROXY for this local run")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_ROOT / run_id
    started_at = now_iso()
    started = time.monotonic()
    report: Dict[str, Any] = {
        "ok": False,
        "mode": "active_campaigns_scrape",
        "started_at": started_at,
        "run": bool(args.run),
        "run_dir": str(run_dir),
    }

    fd = None
    try:
        fd = acquire_lock()
        env_info = load_local_env()
        if args.no_proxy:
            os.environ.pop("TIKTOK_PROXY", None)
            report["proxy_disabled_for_run"] = True
        report["environment"] = env_snapshot(env_info)

        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError("DATABASE_URL is required for local campaign_refresh")

        from campaign_manager import db as _db
        from campaign_manager.services.scheduler import run_campaign_refresh

        _db.init()
        active_campaigns = _db.list_campaigns(status="active", exclude_completed=True)
        report["active_campaigns_excluding_completed"] = len(active_campaigns)

        if args.run:
            run_campaign_refresh()
            latest = latest_campaign_refresh_log()
            summary = latest.get("summary") or {}
            report["cron_log"] = {
                "id": latest.get("id"),
                "status": latest.get("status"),
                "started_at": latest.get("started_at"),
                "finished_at": latest.get("finished_at"),
                "campaigns_refreshed": summary.get("campaigns_refreshed"),
                "campaigns_failed": summary.get("campaigns_failed"),
                "total_new_matches": summary.get("total_new_matches"),
                "total_videos_checked": summary.get("total_videos_checked"),
                "creators_scraped_total": summary.get("creators_scraped_total"),
                "scrape_outcome_counts": summary.get("scrape_outcome_counts"),
                "empty_creator_rate": summary.get("empty_creator_rate"),
                "degraded": summary.get("degraded"),
                "auto_dedupe": summary.get("auto_dedupe"),
                "errors": (summary.get("errors") or [])[:10],
            }
            report["ok"] = latest.get("status") == "completed" and not bool(summary.get("degraded"))
        else:
            report["ok"] = True

        if args.export:
            report["export"] = export_queue()
            report["ok"] = bool(report["ok"] and report["export"].get("ok"))

        report["finished_at"] = now_iso()
        report["duration_seconds"] = round(time.monotonic() - started, 1)
        if args.write_report:
            write_json(run_dir / "report.json", report)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0 if report["ok"] else 1
    except FileExistsError:
        report.update({
            "ok": False,
            "error": f"active campaign scrape lock exists: {LOCK_PATH}",
            "finished_at": now_iso(),
            "duration_seconds": round(time.monotonic() - started, 1),
        })
        if args.write_report:
            write_json(run_dir / "report.json", report)
        print(json.dumps(report, indent=2, sort_keys=True, default=str), file=sys.stderr)
        return 75
    except Exception as exc:
        report.update({
            "ok": False,
            "error": str(exc),
            "finished_at": now_iso(),
            "duration_seconds": round(time.monotonic() - started, 1),
        })
        if args.write_report:
            write_json(run_dir / "report.json", report)
        print(json.dumps(report, indent=2, sort_keys=True, default=str), file=sys.stderr)
        return 1
    finally:
        if fd is not None:
            release_lock(fd)


if __name__ == "__main__":
    raise SystemExit(main())
