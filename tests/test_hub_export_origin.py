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
