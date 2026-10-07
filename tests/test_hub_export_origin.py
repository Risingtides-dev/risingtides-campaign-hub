"""Synthetic origin and failure checks for local Campaign Hub helpers."""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from urllib.error import HTTPError

import pytest


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "https://campaignhub.risingtidesviral.com"


def load_script(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("hub_queue_export", "tools/yt-scraper/export_hub_queue_links.py"),
        ("hub_pi_ops", "tools/yt-scraper/pi_ops.py"),
    ],
)
def test_local_helpers_default_to_canonical_hub(monkeypatch, name, path):
    monkeypatch.delenv("CAMPAIGN_HUB_API_URL", raising=False)
    module = load_script(name, path)
    assert module.hub_base() == CANONICAL


def test_groups_cli_defaults_to_canonical_hub(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_HUB_API", raising=False)
    module = load_script("hub_groups_cli", "scripts/internal_groups_cli.py")
    assert module.DEFAULT_BASE == CANONICAL


def test_export_keeps_explicit_local_override_and_api_suffix(monkeypatch):
    module = load_script("hub_queue_override", "tools/yt-scraper/export_hub_queue_links.py")
    monkeypatch.setenv("CAMPAIGN_HUB_API_URL", "http://localhost:5055/api/")
    assert module.queue_url(500) == "http://localhost:5055/api/scrape-tasks/queue?limit=500"


@pytest.mark.parametrize(
    "base",
    [
        "https://hub.example/other",
        "https://user:secret@hub.example",
        "https://hub.example?token=secret",
        "https://hub.example:bad",
        "file:///tmp/hub.json",
    ],
)
def test_export_rejects_invalid_origin_before_io(monkeypatch, tmp_path, base):
    module = load_script("hub_queue_invalid", "tools/yt-scraper/export_hub_queue_links.py")
    monkeypatch.setenv("CAMPAIGN_HUB_API_URL", base)
    monkeypatch.setattr(module, "OUTPUT_ROOT", tmp_path / "no-env")
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: pytest.fail("network requested"))
    with pytest.raises(ValueError, match="CAMPAIGN_HUB_API_URL"):
        module.export_queue(tmp_path / "exports", 500)
    assert not (tmp_path / "exports").exists()


def test_export_http_failure_is_bounded_and_writes_nothing(monkeypatch, tmp_path):
    module = load_script("hub_queue_404", "tools/yt-scraper/export_hub_queue_links.py")
    monkeypatch.delenv("CAMPAIGN_HUB_API_URL", raising=False)
    monkeypatch.setattr(module, "OUTPUT_ROOT", tmp_path / "no-env")

    def fail(req, timeout):
        assert req.full_url == CANONICAL + "/api/scrape-tasks/queue?limit=500"
        assert timeout == 45
        raise HTTPError(req.full_url, 404, "missing", {}, io.BytesIO(b"private diagnostics"))

    monkeypatch.setattr(module, "urlopen", fail)
    with pytest.raises(RuntimeError, match="HTTP 404") as err:
        module.export_queue(tmp_path / "exports", 500)
    assert "private diagnostics" not in str(err.value)
    assert not (tmp_path / "exports").exists()


def test_export_rejects_oversized_response_without_output(monkeypatch, tmp_path):
    module = load_script("hub_queue_big", "tools/yt-scraper/export_hub_queue_links.py")
    monkeypatch.setattr(module, "OUTPUT_ROOT", tmp_path / "no-env")
    monkeypatch.setattr(module, "MAX_QUEUE_RESPONSE_BYTES", 8)

    class BigResponse:
        headers = {"Content-Length": "9"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            assert size <= 9
            return b"x" * size

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: BigResponse())
    with pytest.raises(RuntimeError, match="size limit"):
        module.export_queue(tmp_path / "exports", 1)
    assert not (tmp_path / "exports").exists()


def test_export_rejects_incomplete_response_without_receipt(monkeypatch, tmp_path):
    module = load_script("hub_queue_short", "tools/yt-scraper/export_hub_queue_links.py")
    monkeypatch.setattr(module, "OUTPUT_ROOT", tmp_path / "no-env")

    class ShortResponse:
        headers = {"Content-Length": "200"}

        def __init__(self):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            self.calls += 1
            return b'{"campaigns":[]}' if self.calls == 1 else b""

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: ShortResponse())
    with pytest.raises(RuntimeError, match="incomplete"):
        module.export_queue(tmp_path / "exports", 1)
    assert not (tmp_path / "exports").exists()


def test_export_deadline_bounds_stalled_body(monkeypatch, tmp_path):
    import time

    module = load_script("hub_queue_stall", "tools/yt-scraper/export_hub_queue_links.py")
    monkeypatch.setattr(module, "OUTPUT_ROOT", tmp_path / "no-env")
    monkeypatch.setattr(module, "QUEUE_REQUEST_TIMEOUT_SECONDS", 0.05)

    class SlowResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            time.sleep(1)
            return b"{}"

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: SlowResponse())
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="time limit"):
        module.export_queue(tmp_path / "exports", 1)
    assert time.monotonic() - started < 0.5
    assert not (tmp_path / "exports").exists()


def test_export_local_http_success_preserves_receipt(monkeypatch, tmp_path):
    import json
    import sqlite3
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    module = load_script("hub_queue_local_http", "tools/yt-scraper/export_hub_queue_links.py")
    monkeypatch.setattr(module, "OUTPUT_ROOT", tmp_path / "no-env")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    body = json.dumps({
        "campaigns": [{
            "slug": "sample",
            "title": "Sample",
            "videos": [{"url": "https://www.tiktok.com/@sample/video/123"}],
        }],
        "total_untracked": 1,
    }).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/api/scrape-tasks/queue?limit=1"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("CAMPAIGN_HUB_API_URL", f"http://127.0.0.1:{server.server_port}")
        result = module.export_queue(tmp_path / "exports", 1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result["campaigns"] == 1
    assert result["links_exported"] == 1
    output_dir = tmp_path / "exports" / Path(result["output_dir"]).name
    assert (output_dir / "all_post_links_copy_paste.txt").read_text().strip() ==         "https://www.tiktok.com/@sample/video/123"
    with sqlite3.connect(tmp_path / "exports" / "scrape_records.sqlite") as conn:
        assert conn.execute("SELECT status, links_exported FROM scrape_runs").fetchone() == ("completed", 1)
