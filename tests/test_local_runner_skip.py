from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from campaign_manager import db
from campaign_manager.services import scheduler


def test_local_runner_treats_same_type_skip_as_noop(monkeypatch, tmp_path, capsys):
    module_path = Path(__file__).resolve().parents[1] / "scripts/pi_active_campaigns_scrape.py"
    spec = importlib.util.spec_from_file_location("local_runner_under_test", module_path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "RUNS_ROOT", tmp_path / "agent-runs")
    monkeypatch.setattr(runner, "LOCK_PATH", tmp_path / "runner.lock")
    monkeypatch.setattr(runner, "load_local_env",
                        lambda: {"loaded_files": [], "loaded_names": []})
    monkeypatch.setattr(runner, "export_queue",
                        lambda: (_ for _ in ()).throw(AssertionError(
                            "skipped scrape must not export as a fresh run")))
    monkeypatch.setenv("DATABASE_URL", "test-only-url")
    monkeypatch.setattr(db, "init", lambda: None)
    monkeypatch.setattr(db, "list_campaigns", lambda **_kwargs: [])
    monkeypatch.setattr(scheduler, "run_campaign_refresh",
                        lambda: {"status": "skipped",
                                 "summary": {"reason": "already_running"}})
    monkeypatch.setattr(sys, "argv", ["pi_active_campaigns_scrape.py",
                                      "--run", "--export", "--write-report"])
    assert runner.main() == 76
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["skipped"] is True
    assert report["scrape_outcome"] == "skipped"
    assert "export" not in report
    assert json.loads((Path(report["run_dir"]) / "report.json").read_text())["skipped"]
    assert not runner.LOCK_PATH.exists()


def test_hourly_wrapper_maps_only_noop_to_neutral_status(tmp_path):
    import subprocess

    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts/pi_scrape_hourly.sh").read_text()
    marker = 'write_status null "scraping" 0'
    assert marker in source
    footer = source[source.index(marker):]
    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("the hourly wrapper requires zsh; executed on the Mac release host")
    for child_rc, expected_rc, expected in (
        (76, 0, "STATUS:null skipped 0"),
        (1, 1, "STATUS:false scrape-exit 1"),
        (77, 77, "STATUS:false export-exit 77"),
        (0, 0, "STATUS:true completed 0"),
    ):
        fake = tmp_path / "fake-child"
        fake.write_text("#!/bin/sh\nexit " + str(child_rc) + "\n")
        fake.chmod(0o755)
        prelude = (
            'PY=' + str(fake) + '\n'
            'stamp(){ print 2026-10-07T19:00:00Z; }\n'
            'write_status(){ print "STATUS:$1 $2 $3"; }\n'
            'fail(){ write_status false "$1" "$2"; exit "$2"; }\n'
        )
        run = subprocess.run(
            [zsh, "-c", prelude + footer],
            cwd=root, text=True, capture_output=True, timeout=5,
        )
        assert run.returncode == expected_rc
        assert expected in run.stdout
        if child_rc == 76:
            assert "STATUS:true completed" not in run.stdout


@pytest.mark.parametrize(
    ("degraded", "expected_exit", "expected_stage"),
    [(False, 77, "export"), (True, 1, None)],
)
def test_local_runner_preserves_completed_scrape_when_export_fails(
    monkeypatch, tmp_path, capsys, degraded, expected_exit, expected_stage
):
    import importlib.util

    module_path = Path(__file__).resolve().parents[1] / "scripts/pi_active_campaigns_scrape.py"
    spec = importlib.util.spec_from_file_location("local_runner_export_under_test", module_path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "RUNS_ROOT", tmp_path / "agent-runs")
    monkeypatch.setattr(runner, "LOCK_PATH", tmp_path / "runner.lock")
    monkeypatch.setattr(runner, "load_local_env",
                        lambda: {"loaded_files": [], "loaded_names": []})
    monkeypatch.setattr(runner, "export_queue",
                        lambda: {"ok": False, "returncode": 1})
    monkeypatch.setenv("DATABASE_URL", "test-only-url")
    monkeypatch.setattr(db, "init", lambda: None)
    monkeypatch.setattr(db, "list_campaigns", lambda **_kwargs: [])
    monkeypatch.setattr(scheduler, "run_campaign_refresh",
                        lambda: {"status": "completed", "summary": {"degraded": degraded}})
    monkeypatch.setattr(sys, "argv", ["pi_active_campaigns_scrape.py",
                                      "--run", "--export", "--write-report"])
    assert runner.main() == expected_exit
    report = json.loads(capsys.readouterr().out)
    assert report["cron_log"]["status"] == "completed"
    assert report["scrape_outcome"] == "completed"
    assert report.get("failure_stage") == expected_stage
    assert report["ok"] is False
    saved = json.loads((Path(report["run_dir"]) / "report.json").read_text())
    assert saved.get("failure_stage") == expected_stage
    assert saved["export"]["ok"] is False


def test_local_runner_does_not_neutralize_expired_request(monkeypatch, tmp_path, capsys):
    import importlib.util

    module_path = Path(__file__).resolve().parents[1] / "scripts/pi_active_campaigns_scrape.py"
    spec = importlib.util.spec_from_file_location("local_runner_expired_under_test", module_path)
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "RUNS_ROOT", tmp_path / "agent-runs")
    monkeypatch.setattr(runner, "LOCK_PATH", tmp_path / "runner.lock")
    monkeypatch.setattr(runner, "load_local_env",
                        lambda: {"loaded_files": [], "loaded_names": []})
    monkeypatch.setenv("DATABASE_URL", "test-only-url")
    monkeypatch.setattr(db, "init", lambda: None)
    monkeypatch.setattr(db, "list_campaigns", lambda **_kwargs: [])
    monkeypatch.setattr(scheduler, "run_campaign_refresh",
                        lambda: {"status": "skipped",
                                 "summary": {"reason": "request_expired"}})
    monkeypatch.setattr(sys, "argv", ["pi_active_campaigns_scrape.py",
                                      "--run", "--write-report"])
    assert runner.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["skip_reason"] == "request_expired"
