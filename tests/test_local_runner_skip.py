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
    assert runner.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["skipped"] is True
    assert report["scrape_outcome"] == "skipped"
    assert "export" not in report
    assert json.loads((Path(report["run_dir"]) / "report.json").read_text())["skipped"]
    assert not runner.LOCK_PATH.exists()
