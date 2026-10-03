from __future__ import annotations

from importlib import metadata
from pathlib import Path

from scripts.check_scraper_runtime import (
    exact_pins,
    runtime_fingerprint,
    runtime_report,
)


def test_exact_pins_normalizes_distribution_names(tmp_path: Path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "yt-dlp==2026.3.17\n"
        "curl_cffi==0.11.4  # native backend\n"
        "requests>=2.31\n",
        encoding="utf-8",
    )

    assert exact_pins(requirements) == {
        "yt-dlp": "2026.3.17",
        "curl-cffi": "0.11.4",
    }


def test_runtime_fingerprint_changes_with_requirements(tmp_path: Path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("curl_cffi==0.11.4\n", encoding="utf-8")
    first = runtime_fingerprint(requirements)

    requirements.write_text("curl_cffi==0.14.0\n", encoding="utf-8")
    second = runtime_fingerprint(requirements)

    assert first["fingerprint"] != second["fingerprint"]
    assert first["requirements_sha256"] != second["requirements_sha256"]
    assert first["runtime"]["cache_tag"]
    assert first["runtime"]["machine"]


def test_runtime_report_accepts_matching_critical_pins(tmp_path: Path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "yt-dlp==2026.3.17\ncurl_cffi==0.11.4\n",
        encoding="utf-8",
    )
    installed = {"yt-dlp": "2026.3.17", "curl-cffi": "0.11.4"}

    report = runtime_report(requirements, version_lookup=installed.__getitem__)

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["packages"]["curl-cffi"]["matches"] is True


def test_runtime_report_fails_closed_on_drift(tmp_path: Path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "yt-dlp==2026.3.17\ncurl_cffi==0.11.4\n",
        encoding="utf-8",
    )
    installed = {"yt-dlp": "2026.3.17", "curl-cffi": "0.14.0"}

    report = runtime_report(requirements, version_lookup=installed.__getitem__)

    assert report["ok"] is False
    assert report["packages"]["curl-cffi"] == {
        "expected": "0.11.4",
        "installed": "0.14.0",
        "matches": False,
    }
    assert "curl-cffi installed=0.14.0 expected=0.11.4" in report["errors"]


def test_runtime_report_requires_exact_pin_and_installed_package(tmp_path: Path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("yt-dlp==2026.3.17\n", encoding="utf-8")

    def lookup(name: str) -> str:
        if name == "curl-cffi":
            raise metadata.PackageNotFoundError(name)
        return "2026.3.17"

    report = runtime_report(requirements, version_lookup=lookup)

    assert report["ok"] is False
    assert "curl-cffi is not exactly pinned" in report["errors"][0]
    assert "curl-cffi is not installed" in report["errors"][1]
