#!/usr/bin/env python3
"""Slack change reports for the local Campaign Hub queue export."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "output" / "local-scraper"
EXPORT_ROOT = OUTPUT_ROOT / "hub_queue_export"
SLACK_CREDENTIALS = Path.home() / ".slack" / "credentials.json"
BOT_SCOPES = [
    "channels:join",
    "channels:read",
    "chat:write",
    "chat:write.public",
    "files:write",
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


def latest_export_dir() -> Optional[Path]:
    dirs = [
        p for p in EXPORT_ROOT.iterdir()
        if p.is_dir() and (p / "all_untracked_links.csv").exists()
    ] if EXPORT_ROOT.exists() else []
    return sorted(dirs)[-1] if dirs else None


def previous_export_dir(current: Path) -> Optional[Path]:
    dirs = [
        p for p in EXPORT_ROOT.iterdir()
        if p.is_dir() and p != current and (p / "all_untracked_links.csv").exists()
    ] if EXPORT_ROOT.exists() else []
    return sorted(dirs)[-1] if dirs else None


def read_rows(export_dir: Path) -> List[Dict[str, str]]:
    path = export_dir / "all_untracked_links.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def row_url(row: Dict[str, str]) -> str:
    return (row.get("url") or "").strip()


def build_change_report(export_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    current = Path(export_dir) if export_dir else latest_export_dir()
    if current is not None and not current.is_absolute():
        current = ROOT / current
    if current is None or not current.exists():
        return {"ok": False, "error": "no export directory found"}

    previous = previous_export_dir(current)
    current_rows = read_rows(current)
    previous_rows = read_rows(previous) if previous else []
    previous_urls = {row_url(r) for r in previous_rows if row_url(r)}
    current_urls = {row_url(r) for r in current_rows if row_url(r)}

    new_rows = [r for r in current_rows if row_url(r) and row_url(r) not in previous_urls]
    removed_rows = [r for r in previous_rows if row_url(r) and row_url(r) not in current_urls]
    changed_campaigns = {
        r.get("campaign_title") or r.get("campaign_slug") or "Campaign"
        for r in [*new_rows, *removed_rows]
    }

    return {
        "ok": True,
        "export_dir": str(current),
        "previous_export_dir": str(previous) if previous else "",
        "current_total_videos": len(current_rows),
        "previous_total_videos": len(previous_rows),
        "net_change": len(current_rows) - len(previous_rows),
        "new_videos": len(new_rows),
        "removed_videos": len(removed_rows),
        "changed_songs": len(changed_campaigns),
        "has_changes": bool(new_rows or removed_rows),
        "new_rows": new_rows,
        "removed_rows": removed_rows,
        "attachment_path": "",
    }


def write_change_txt_report(report: Dict[str, Any], label: str = "scheduled") -> str:
    export_dir = Path(report["export_dir"])
    path = export_dir / f"slack_{label}_changes.txt"
    lines: List[str] = [
        "Campaign Hub scheduled queue changes",
        f"Generated: {datetime.now().isoformat()}",
        f"Current links: {report['current_total_videos']}",
        f"Previous links: {report['previous_total_videos']}",
        f"New links: {report['new_videos']}",
        f"Removed links: {report['removed_videos']}",
        "",
    ]

    def append_group(title: str, rows: List[Dict[str, str]]) -> None:
        lines.extend([title, "-" * len(title)])
        for row in rows:
            account = row.get("account") or ""
            prefix = f"{account} " if account else ""
            lines.append(f"{prefix}{row.get('url') or ''}")
        lines.append("")

    by_campaign: Dict[str, List[Dict[str, str]]] = {}
    for row in report.get("new_rows") or []:
        title = row.get("campaign_title") or row.get("campaign_slug") or "Campaign"
        by_campaign.setdefault(title, []).append(row)

    if by_campaign:
        for title in sorted(by_campaign):
            append_group(title, by_campaign[title])
    else:
        lines.append("No new links in this run.")
        lines.append("")

    removed = report.get("removed_rows") or []
    if removed:
        lines.extend(["Removed since previous export", "-----------------------------"])
        for row in removed:
            title = row.get("campaign_title") or row.get("campaign_slug") or "Campaign"
            account = row.get("account") or ""
            prefix = f"{account} " if account else ""
            lines.append(f"{title}: {prefix}{row.get('url') or ''}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    report["attachment_path"] = str(path)
    return str(path)


def format_message(report: Dict[str, Any], label: str = "scheduled") -> str:
    status = "changes found" if report.get("has_changes") else "no new links"
    return (
        f"Campaign Hub {label} scrape report: {status}\n"
        f"Current queue: {report.get('current_total_videos', 0)} links\n"
        f"Previous queue: {report.get('previous_total_videos', 0)} links\n"
        f"New: {report.get('new_videos', 0)} | Removed: {report.get('removed_videos', 0)} | "
        f"Changed songs: {report.get('changed_songs', 0)}"
    )


def slack_settings() -> Dict[str, str]:
    load_env()
    return {
        "channel": os.environ.get("SLACK_ALERTS_CHANNEL", "").strip(),
        "channel_label": os.environ.get("SLACK_ALERTS_CHANNEL_LABEL", "").strip() or "#scrape-updates",
        "app": os.environ.get("SLACK_CLI_APP_ID", "").strip(),
        "team": os.environ.get("SLACK_CLI_TEAM_ID", "").strip(),
        "project_dir": os.environ.get("SLACK_CLI_PROJECT_DIR", "").strip(),
    }


def slack_cli_credentials_token(team: str = "") -> str:
    if not SLACK_CREDENTIALS.exists():
        return ""
    try:
        credentials = json.loads(SLACK_CREDENTIALS.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(credentials, dict):
        return ""
    team_data = credentials.get(team) if team else None
    if not isinstance(team_data, dict):
        team_data = next((v for v in credentials.values() if isinstance(v, dict)), {})
    token = str(team_data.get("token") or "").strip()
    return token


def slack_api_direct_raw(method: str, payload: Dict[str, Any], token: str, timeout: int) -> Dict[str, Any]:
    req = Request(
        f"https://slack.com/api/{method}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        data=json.dumps(payload).encode("utf-8"),
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return parsed if isinstance(parsed, dict) else {"ok": False, "response": parsed}


def slack_api_form_raw(method: str, payload: Dict[str, Any], token: str, timeout: int) -> Dict[str, Any]:
    req = Request(
        f"https://slack.com/api/{method}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data=urlencode(payload).encode("utf-8"),
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return parsed if isinstance(parsed, dict) else {"ok": False, "response": parsed}


def developer_install_bot_token(settings: Dict[str, str]) -> str:
    if not settings.get("app"):
        return ""
    user_token = slack_cli_credentials_token(settings.get("team", ""))
    if not user_token:
        return ""
    result = slack_api_direct_raw(
        "apps.developerInstall",
        {"app_id": settings["app"], "bot_scopes": BOT_SCOPES},
        user_token,
        timeout=30,
    )
    tokens = result.get("api_access_tokens") if isinstance(result, dict) else {}
    return str((tokens or {}).get("bot") or "").strip()


def slack_token(settings: Dict[str, str]) -> str:
    return (
        os.environ.get("SLACK_BOT_TOKEN", "").strip()
        or developer_install_bot_token(settings)
        or os.environ.get("SLACK_USER_TOKEN", "").strip()
        or slack_cli_credentials_token(settings.get("team", ""))
    )


def slack_status() -> Dict[str, Any]:
    settings = slack_settings()
    token = slack_token(settings)
    configured = bool(settings["channel"]) and (
        bool(token)
        or bool(settings["app"] and settings["team"] and shutil.which("slack"))
    )
    if os.environ.get("SLACK_BOT_TOKEN"):
        auth_mode = "token_env"
    elif token and settings["app"]:
        auth_mode = "slack_app_developer_install"
    elif os.environ.get("SLACK_USER_TOKEN") or token:
        auth_mode = "slack_cli_credentials"
    else:
        auth_mode = "slack_cli_app"
    return {
        "ok": configured,
        "configured": configured,
        "channel": settings["channel"],
        "channel_label": settings["channel_label"],
        "auth_mode": auth_mode,
        "secret_values_redacted": True,
    }


def scrub_response(value: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(value)
    for key in ["token", "upload_url"]:
        if key in clean:
            clean[key] = "REDACTED"
    return clean


def slack_api(method: str, payload: Dict[str, Any], timeout: int = 30, scrub: bool = True) -> Dict[str, Any]:
    settings = slack_settings()
    if not settings["channel"]:
        return {"ok": False, "error": "SLACK_ALERTS_CHANNEL is not configured"}

    token = slack_token(settings)
    if token:
        result = slack_api_direct_raw(method, payload, token, timeout)
        return scrub_response(result) if scrub else result

    cmd = [
        "slack",
        "api",
        method,
        "--json",
        json.dumps(payload),
        "--skip-update",
        "--no-color",
    ]
    if settings["team"]:
        cmd.extend(["--team", settings["team"]])
    if settings["app"]:
        cmd.extend(["--app", settings["app"]])
    cwd = settings["project_dir"] if settings["project_dir"] and Path(settings["project_dir"]).exists() else str(ROOT)
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    try:
        parsed = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        parsed = {"raw_stdout": proc.stdout[-1000:]}
    parsed.setdefault("ok", proc.returncode == 0 and bool(parsed.get("ok", False)))
    if proc.returncode != 0:
        parsed["returncode"] = proc.returncode
        parsed["stderr_tail"] = proc.stderr[-1000:]
    return scrub_response(parsed) if scrub else parsed


def upload_file(path: str, comment: str, title: str) -> Dict[str, Any]:
    settings = slack_settings()
    file_path = Path(path)
    if not file_path.exists():
        return {"ok": False, "error": f"attachment missing: {path}"}

    token = slack_token(settings)
    if not token:
        return {"ok": False, "error": "no Slack token available"}

    first = slack_api_form_raw(
        "files.getUploadURLExternal",
        {"filename": file_path.name, "length": file_path.stat().st_size},
        token,
        timeout=30,
    )
    if not first.get("ok"):
        return {"ok": False, "phase": "getUploadURLExternal", "response": scrub_response(first)}

    upload_url = first.get("upload_url") or ""
    file_id = first.get("file_id") or ""
    if not upload_url or not file_id:
        return {"ok": False, "phase": "getUploadURLExternal", "response": scrub_response(first)}

    upload = subprocess.run(
        ["curl", "-fsS", "-X", "POST", "-F", f"file=@{file_path}", upload_url],
        text=True,
        capture_output=True,
        timeout=60,
    )
    if upload.returncode != 0:
        return {
            "ok": False,
            "phase": "upload",
            "returncode": upload.returncode,
            "stderr_tail": upload.stderr[-1000:],
        }

    complete = slack_api(
        "files.completeUploadExternal",
        {
            "files": [{"id": file_id, "title": title}],
            "channel_id": settings["channel"],
            "initial_comment": comment,
        },
        timeout=30,
    )
    complete["phase"] = "completeUploadExternal"
    return complete


def send_change_alert(export_dir: Optional[str | Path] = None, label: str = "scheduled") -> Dict[str, Any]:
    settings = slack_settings()
    status = slack_status()
    if not status.get("configured"):
        return {
            "ok": False,
            "sent": False,
            "channel": settings["channel"],
            "channel_label": settings["channel_label"],
            "error": "Slack alerts are not configured; refusing to use fallback channels.",
            "secret_values_redacted": True,
        }

    report = build_change_report(export_dir)
    if not report.get("ok"):
        return {"ok": False, "sent": False, "report": report, "secret_values_redacted": True}

    attachment_path = write_change_txt_report(report, label=label)
    message = format_message(report, label=label)
    upload = upload_file(
        attachment_path,
        message,
        f"Campaign Hub {label} scrape changes",
    )

    fallback_message = None
    if not upload.get("ok"):
        fallback_message = slack_api(
            "chat.postMessage",
            {
                "channel": settings["channel"],
                "text": f"{message}\nTXT attachment failed; local file: {attachment_path}",
            },
            timeout=30,
        )

    return {
        "ok": bool(upload.get("ok")),
        "sent": bool(upload.get("ok") or (fallback_message or {}).get("ok")),
        "channel": settings["channel"],
        "channel_label": settings["channel_label"],
        "upload": upload,
        "fallback_message": fallback_message or {},
        "report": {
            k: v for k, v in report.items()
            if k not in {"new_rows", "removed_rows"}
        },
        "secret_values_redacted": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status", "send", "report"], nargs="?", default="status")
    parser.add_argument("--export-dir", default="")
    parser.add_argument("--label", default="manual")
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(slack_status(), indent=2, sort_keys=True))
        return 0
    if args.command == "report":
        report = build_change_report(args.export_dir or None)
        if report.get("ok"):
            write_change_txt_report(report, args.label)
            report = {k: v for k, v in report.items() if k not in {"new_rows", "removed_rows"}}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("ok") else 1

    result = send_change_alert(args.export_dir or None, args.label)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
