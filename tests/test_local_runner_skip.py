from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

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
    for child_rc, expected_rc, expected in (
        (76, 0, "STATUS:null skipped 0"),
        (1, 1, "STATUS:false scrape-exit 1"),
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
            ["/bin/zsh", "-c", prelude + footer],
            cwd=root, text=True, capture_output=True, timeout=5,
        )
        assert run.returncode == expected_rc
        assert expected in run.stdout
        if child_rc == 76:
            assert "STATUS:true completed" not in run.stdout
