#!/usr/bin/env python3
"""Scheduled local scrape maintenance runner.

This is the target invoked by launchd. It keeps the recurring job small:
load local env, export the active Campaign Hub scrape queue, write a run
report, and send the configured Slack delta report.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools" / "yt-scraper"
OUTPUT_ROOT = ROOT / "output" / "local-scraper"
RUNS_ROOT = OUTPUT_ROOT / "agent-runs"
LOCK_PATH = OUTPUT_ROOT / "pi_scrape_maintenance.lock"
STALE_LOCK_SECONDS = 2 * 60 * 60


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    age = datetime.now().timestamp() - LOCK_PATH.stat().st_mtime
    if (pid and not pid_is_running(pid)) or (not pid and age > 60) or age > STALE_LOCK_SECONDS:
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
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_status(path: Path, payload: Dict[str, Any]) -> None:
    lines = [
        f"mode={payload.get('mode', '')}",
        f"ok={payload.get('ok', False)}",
        f"started_at={payload.get('started_at', '')}",
        f"finished_at={payload.get('finished_at', '')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_dir_from_smoke(smoke: Dict[str, Any]) -> str:
    export_block = smoke.get("export") or {}
    parsed = export_block.get("parsed") or {}
    return str(parsed.get("output_dir") or "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", default="scheduled")
    parser.add_argument("--no-slack", action="store_true")
    args = parser.parse_args()

    fd = None
    started_at = now_iso()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_ROOT / run_id

    report: Dict[str, Any] = {
        "ok": False,
        "mode": args.mode,
        "started_at": started_at,
        "run_dir": str(run_dir),
    }

    try:
        fd = acquire_lock()
    except FileExistsError:
        report.update({
            "ok": False,
            "error": f"maintenance lock exists: {LOCK_PATH}",
            "finished_at": now_iso(),
        })
        write_json(run_dir / "report.json", report)
        write_status(run_dir / "status.txt", report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 75

    try:
        pi_ops = load_module("pi_ops", TOOLS_DIR / "pi_ops.py")
        slack_alerts = load_module("slack_alerts", TOOLS_DIR / "slack_alerts.py")

        pi_ops.load_agent_env()
        smoke = pi_ops.run_smoke(run_export=True, quick=True)
        report["smoke"] = smoke
        report["ok"] = bool(smoke.get("ok"))

        disable_slack = (
            args.no_slack
            or os.environ.get("PI_SCRAPE_NO_SLACK", "").strip().lower() in {"1", "true", "yes"}
        )
        if args.mode == "scheduled" and not disable_slack:
            export_dir = export_dir_from_smoke(smoke)
            report["slack_change_alert"] = slack_alerts.send_change_alert(
                export_dir=export_dir or None,
                label="scheduled",
            )
        elif disable_slack:
            report["slack_change_alert"] = {"ok": True, "sent": False, "disabled": True}

        report["finished_at"] = now_iso()
        write_json(run_dir / "report.json", report)
        write_status(run_dir / "status.txt", report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1
    except Exception as exc:
        report.update({
            "ok": False,
            "error": str(exc),
            "finished_at": now_iso(),
        })
        write_json(run_dir / "report.json", report)
        write_status(run_dir / "status.txt", report)
        print(json.dumps(report, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if fd is not None:
            release_lock(fd)


if __name__ == "__main__":
    raise SystemExit(main())
