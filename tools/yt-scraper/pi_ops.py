#!/usr/bin/env python3
"""Local Pi scrape node health and export operations."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools" / "yt-scraper"
OUTPUT_ROOT = ROOT / "output" / "local-scraper"
EXPORT_ROOT = OUTPUT_ROOT / "hub_queue_export"
DEFAULT_HUB_BASE = "https://risingtides-campaign-hub-production.up.railway.app"

EXPECTED_ENV = [
    "DATABASE_URL",
    "DECODO_API_KEY",
    "PI_AGENT_COMMAND",
    "PI_CONTROL_TOKEN",
    "SLACK_ALERTS_CHANNEL",
    "SLACK_CLI_APP_ID",
    "SLACK_CLI_PROJECT_DIR",
    "SLACK_CLI_TEAM_ID",
    "TIKTOK_COOKIES_FILE",
    "TIKTOK_COOKIES_FROM_BROWSER",
    "TIKTOK_IMPERSONATE",
    "TIKTOK_IMPERSONATE_TARGET",
    "TIKTOK_PROXY",
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


def load_agent_env() -> Dict[str, Any]:
    loaded_files: List[str] = []
    loaded_names: List[str] = []
    for path in [
        OUTPUT_ROOT / ".env",
        OUTPUT_ROOT / "runtime" / "pi_node.env",
    ]:
        vals = parse_env_file(path)
        if vals:
            loaded_files.append(str(path))
        for key, value in vals.items():
            os.environ.setdefault(key, value)
            loaded_names.append(key)
    return {
        "loaded_files": loaded_files,
        "loaded_names": sorted(set(loaded_names)),
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_cmd(args: List[str], timeout: int = 30, cwd: Optional[Path] = None) -> Dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd or ROOT),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
            "error": f"timed out after {timeout}s",
        }


def env_snapshot() -> Dict[str, Any]:
    load_info = load_agent_env()
    present = [name for name in EXPECTED_ENV if os.environ.get(name)]
    missing = [name for name in EXPECTED_ENV if not os.environ.get(name)]
    cookies_file = os.environ.get("TIKTOK_COOKIES_FILE", "").strip()
    return {
        **load_info,
        "present": present,
        "missing": missing,
        "secret_values_redacted": True,
        "cookies": {
            "file_configured": bool(cookies_file),
            "file_exists": bool(cookies_file and Path(cookies_file).exists()),
            "file_path": cookies_file if cookies_file else "",
            "from_browser": os.environ.get("TIKTOK_COOKIES_FROM_BROWSER", "").strip(),
        },
        "proxy_configured": bool(os.environ.get("TIKTOK_PROXY", "").strip()),
        "impersonation": {
            "enabled": os.environ.get("TIKTOK_IMPERSONATE", "").strip().lower() in {"1", "true", "yes"},
            "target": os.environ.get("TIKTOK_IMPERSONATE_TARGET", "").strip(),
        },
    }


def hub_base() -> str:
    raw = os.environ.get("CAMPAIGN_HUB_API_URL", "").strip() or DEFAULT_HUB_BASE
    raw = raw.rstrip("/")
    if raw.endswith("/api"):
        raw = raw[:-4]
    return raw


def hub_status() -> Dict[str, Any]:
    url = f"{hub_base()}/api/scrape-tasks/queue?limit=2"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return {
            "ok": True,
            "url": url,
            "campaigns": len(payload.get("campaigns") or []),
            "total_untracked": int(payload.get("total_untracked") or 0),
        }
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def latest_export_dir() -> Optional[Path]:
    dirs = [
        p for p in EXPORT_ROOT.iterdir()
        if p.is_dir() and (p / "summary.json").exists()
    ] if EXPORT_ROOT.exists() else []
    return sorted(dirs)[-1] if dirs else None


def latest_summary() -> Dict[str, Any]:
    latest = latest_export_dir()
    if not latest:
        return {"ok": False, "error": "no export found"}
    try:
        summary = json.loads((latest / "summary.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "export_dir": str(latest), "error": str(exc)}
    return {
        "ok": True,
        "export_dir": str(latest),
        "links_exported": int(summary.get("links_exported") or 0),
        "campaigns": int(summary.get("campaigns") or 0),
        "generated_at": summary.get("generated_at") or "",
    }


def latest_runs(limit: int = 5) -> List[Dict[str, Any]]:
    runs_root = OUTPUT_ROOT / "agent-runs"
    dirs = sorted([p for p in runs_root.iterdir() if p.is_dir()])[-limit:] if runs_root.exists() else []
    results: List[Dict[str, Any]] = []
    for run_dir in reversed(dirs):
        report_path = run_dir / "report.json"
        if not report_path.exists():
            results.append({"run_dir": str(run_dir), "ok": None})
            continue
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            results.append({
                "run_dir": str(run_dir),
                "ok": report.get("ok"),
                "mode": report.get("mode"),
                "started_at": report.get("started_at"),
                "finished_at": report.get("finished_at"),
            })
        except Exception as exc:
            results.append({"run_dir": str(run_dir), "ok": False, "error": str(exc)})
    return results


def local_server_status() -> Dict[str, Any]:
    url = "http://127.0.0.1:8899/api/status"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return {"ok": True, **payload}
    except Exception as exc:
        summary = latest_summary()
        root_url = "http://127.0.0.1:8899/"
        try:
            req = Request(root_url, headers={"Accept": "text/html"})
            with urlopen(req, timeout=5) as resp:
                reachable = resp.status < 500
            if reachable:
                return {
                    "ok": True,
                    "url": root_url,
                    "legacy_server": True,
                    "status_endpoint": "missing",
                    "latest_export": summary,
                }
        except Exception:
            pass
        return {
            "ok": False,
            "url": url,
            "error": str(exc),
            "latest_export": summary,
        }


def scheduler_status() -> Dict[str, Any]:
    label = "com.risingtides.pi-scrape-hourly"
    result = run_cmd(["launchctl", "print", f"gui/{os.getuid()}/{label}"], timeout=10)
    status: Dict[str, Any] = {
        "ok": result["ok"],
        "label": label,
        "raw_tail": result.get("stdout_tail", "")[-1200:],
    }
    out = result.get("stdout_tail", "")
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("state ="):
            status["state"] = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("runs ="):
            status["runs"] = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("last exit code ="):
            status["last_exit_code"] = stripped.split("=", 1)[1].strip()
    return status


def dependency_status() -> Dict[str, Any]:
    commands = {}
    for name in ["yt-dlp", "cloudflared", "tmux", "launchctl"]:
        path = shutil.which(name)
        commands[name] = {"ok": bool(path), "path": path or ""}

    packages = {}
    for dist in ["yt-dlp", "curl-cffi", "slack-sdk"]:
        try:
            packages[dist] = {"ok": True, "version": importlib.metadata.version(dist)}
        except importlib.metadata.PackageNotFoundError:
            packages[dist] = {"ok": False, "version": ""}

    production_runtime: Dict[str, Any] = {
        "ok": False,
        "error": "production runtime is not provisioned",
    }
    prod_python = OUTPUT_ROOT / "prod-venv" / "bin" / "python"
    guard = ROOT / "scripts" / "check_scraper_runtime.py"
    if prod_python.exists() and guard.exists():
        checked = run_cmd(
            [
                str(prod_python),
                str(guard),
                "--requirements",
                str(ROOT / "requirements.txt"),
            ],
            timeout=30,
        )
        try:
            production_runtime = json.loads(checked.get("stdout_tail") or "{}")
        except json.JSONDecodeError:
            production_runtime = {
                "ok": False,
                "error": checked.get("stderr_tail") or "runtime guard returned invalid JSON",
            }

    return {
        "ok": bool(production_runtime.get("ok")),
        "commands": commands,
        "python_packages": packages,
        "production_runtime": production_runtime,
        "python": {
            "ok": True,
            "version": ".".join(map(str, sys.version_info[:3])),
            "executable": sys.executable,
        },
    }


def slack_alert_status() -> Dict[str, Any]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("slack_alerts", TOOLS_DIR / "slack_alerts.py")
    if spec is None or spec.loader is None:
        return {"ok": False, "error": "cannot load slack_alerts.py"}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.slack_status()


def run_export() -> Dict[str, Any]:
    script = TOOLS_DIR / "export_hub_queue_links.py"
    result = run_cmd([sys.executable, str(script)], timeout=90)
    parsed: Dict[str, Any] = {}
    if result.get("stdout_tail"):
        try:
            parsed = json.loads(result["stdout_tail"])
        except json.JSONDecodeError:
            parsed = {}
    result["parsed"] = parsed
    return result


def run_smoke(run_export: bool = False, quick: bool = True) -> Dict[str, Any]:
    load_agent_env()
    smoke: Dict[str, Any] = {
        "checked_at": now_iso(),
        "environment": env_snapshot(),
        "hub": hub_status(),
        "local_server": local_server_status(),
        "dependencies": dependency_status(),
        "slack_alerts": slack_alert_status(),
    }
    if run_export:
        smoke["export"] = run_export_fn = run_export_queue()
        if run_export_fn.get("ok"):
            smoke["local_server"] = local_server_status()
    smoke["ok"] = (
        bool(smoke["hub"].get("ok"))
        and bool((smoke.get("export") or {"ok": True}).get("ok"))
        and bool(smoke["dependencies"].get("ok"))
    )
    if not quick:
        smoke["scheduler"] = scheduler_status()
        smoke["recent_runs"] = latest_runs()
    return smoke


def run_export_queue() -> Dict[str, Any]:
    return run_export()


def build_health(quick: bool = False, run_export_flag: bool = False) -> Dict[str, Any]:
    health = run_smoke(run_export=run_export_flag, quick=quick)
    health["scheduler"] = scheduler_status()
    health["recent_runs"] = latest_runs()
    return health


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["health", "smoke", "export"], nargs="?", default="health")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--run-export", action="store_true")
    args = parser.parse_args()

    if args.command == "export":
        result = run_export()
    elif args.command == "smoke":
        result = run_smoke(run_export=args.run_export, quick=args.quick)
    else:
        result = build_health(quick=args.quick, run_export_flag=args.run_export)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
