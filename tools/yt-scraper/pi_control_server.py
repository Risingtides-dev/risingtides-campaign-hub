#!/usr/bin/env python3
"""Small local status/download server for queue exports."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import argparse
import importlib.util

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "output" / "local-scraper"
EXPORT_ROOT = OUTPUT_ROOT / "hub_queue_export"

# Webhook actions this node will run. Whitelist only — the request body never
# supplies a command/prompt, just picks one of these named handlers. This is
# what keeps an internet-reachable endpoint from being a remote shell.
SCRAPER_LAUNCHD_LABEL = "com.risingtides.pi-scrape-hourly"


def latest_export_dir() -> Path | None:
    dirs = [
        p for p in EXPORT_ROOT.iterdir()
        if p.is_dir() and (p / "summary.json").exists()
    ] if EXPORT_ROOT.exists() else []
    return sorted(dirs)[-1] if dirs else None


def load_summary() -> dict:
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
        "links_exported": summary.get("links_exported", 0),
        "campaigns": summary.get("campaigns", 0),
        "generated_at": summary.get("generated_at", ""),
    }


def response_bytes(payload: bytes, status: int = 200, content_type: str = "application/json"):
    return status, content_type, payload


def safe_download_path(kind: str) -> Path | None:
    latest = latest_export_dir()
    if not latest:
        return None
    if kind == "all.txt":
        return latest / "all_post_links_copy_paste.txt"
    if kind == "grouped.txt":
        return latest / "all_post_links_grouped.txt"
    if kind == "all.csv":
        return latest / "all_untracked_links.csv"
    if kind == "summary.json":
        return latest / "summary.json"
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: ANN001
        return

    def _send(self, status: int, content_type: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self) -> bool:
        token = os.environ.get("PI_CONTROL_TOKEN", "").strip()
        if not token:
            return True
        query = parse_qs(urlparse(self.path).query)
        return (query.get("token") or [""])[0] == token

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            payload = json.dumps(load_summary(), indent=2).encode("utf-8")
            self._send(200, "application/json", payload)
            return
        if parsed.path == "/queue_report.html" or parsed.path == "/":
            summary = load_summary()
            html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Pi Scrape Queue</title>
<style>body{{font-family:system-ui;margin:32px;max-width:760px}}a{{display:block;margin:8px 0}}</style>
</head><body>
<h1>Pi Scrape Queue</h1>
<pre>{json.dumps(summary, indent=2)}</pre>
<a href="/download/all.txt">Download all TXT</a>
<a href="/download/grouped.txt">Download grouped TXT</a>
<a href="/download/all.csv">Download CSV</a>
<a href="/download/summary.json">Download summary JSON</a>
</body></html>"""
            self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
            return
        if parsed.path.startswith("/download/"):
            if not self._authorized():
                self._send(403, "application/json", b'{"error":"bad token"}')
                return
            kind = parsed.path.rsplit("/", 1)[-1]
            path = safe_download_path(kind)
            if not path or not path.exists():
                self._send(404, "application/json", b'{"error":"not found"}')
                return
            ctype = "text/csv" if path.suffix == ".csv" else "text/plain"
            if path.suffix == ".json":
                ctype = "application/json"
            self._send(200, ctype, path.read_bytes())
            return
        self._send(404, "application/json", b'{"error":"not found"}')

    def _run_local_scrape(self) -> dict:
        """Whitelisted action: kick the local scrape launchd job. No request input
        is passed to the shell — this only restarts a fixed, pre-installed job."""
        import subprocess
        domain = f"gui/{os.getuid()}/{SCRAPER_LAUNCHD_LABEL}"
        try:
            listed = subprocess.run(
                ["launchctl", "list", SCRAPER_LAUNCHD_LABEL],
                capture_output=True, text=True, timeout=10,
            )
            if '"PID"' in (listed.stdout or ""):
                return {"ok": True, "action": "scrape", "started": False,
                        "note": "scrape already running"}
            proc = subprocess.run(
                ["launchctl", "kickstart", domain],
                capture_output=True, text=True, timeout=15,
            )
            ok = proc.returncode == 0
            return {"ok": ok, "action": "scrape", "started": ok,
                    "detail": (proc.stderr or proc.stdout or "").strip()[:300]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "action": "scrape", "error": str(exc)}

    def _dispatch_action(self, body: dict):
        action = (body.get("action") or "").strip()
        if action == "scrape":
            return 200, self._run_local_scrape()
        return 400, {"ok": False, "error": f"unknown action: {action!r}",
                     "allowed": ["scrape"]}

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            return {}

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/run-now":
            if not self._authorized():
                self._send(403, "application/json", b'{"error":"bad token"}')
                return
            code, result = self._dispatch_action(self._read_json_body())
            self._send(code, "application/json", json.dumps(result, indent=2).encode("utf-8"))
            return
        if parsed.path != "/api/export":
            self._send(404, "application/json", b'{"error":"not found"}')
            return
        if not self._authorized():
            self._send(403, "application/json", b'{"error":"bad token"}')
            return
        spec = importlib.util.spec_from_file_location(
            "export_hub_queue_links",
            ROOT / "tools" / "yt-scraper" / "export_hub_queue_links.py",
        )
        if spec is None or spec.loader is None:
            self._send(500, "application/json", b'{"error":"cannot load exporter"}')
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.export_queue(EXPORT_ROOT, 500)
        self._send(200, "application/json", json.dumps(result, indent=2).encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Pi control server listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
