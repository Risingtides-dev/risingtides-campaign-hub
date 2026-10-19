"""Synthetic lock regressions; these never provision or launch a scrape."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.mark.parametrize("script", ["pi_scrape_hourly.sh", "provision_scraper_runtime.sh"])
def test_stale_runner_lock_is_preserved_under_concurrent_attempts(tmp_path: Path, script: str):
    runtime = tmp_path / "output" / "local-scraper"
    lock = runtime / "runner.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("99999999\n", encoding="utf-8")
    env = os.environ | {
        "SCRAPER_MAIN": str(tmp_path),
        "SCRAPER_WORKTREE": str(tmp_path),
    }
    processes = [
        subprocess.Popen(
            ["zsh", str(SCRIPTS / script)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = [process.communicate(timeout=10) for process in processes]
    assert [process.returncode for process in processes] == [75, 75], results
    assert (lock / "pid").read_text(encoding="utf-8") == "99999999\n"


def test_held_lock_mode_refuses_unrelated_caller(tmp_path: Path):
    runtime = tmp_path / "output" / "local-scraper"
    lock = runtime / "runner.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    env = os.environ | {
        "SCRAPER_MAIN": str(tmp_path),
        "SCRAPER_WORKTREE": str(tmp_path),
        "SCRAPER_RUNNER_LOCK_OWNER_PID": str(os.getpid()),
        "SCRAPER_EXPECTED_SOURCE_SHA": "a" * 40,
    }
    result = subprocess.run(
        ["zsh", str(SCRIPTS / "provision_scraper_runtime.sh"), "--held-lock"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 75
    assert "held scraper lock proof missing" in result.stderr
    assert (lock / "pid").read_text(encoding="utf-8") == f"{os.getpid()}\n"


def test_held_lock_reuses_complete_runtime_at_exact_source(tmp_path: Path):
    candidates = [os.environ.get("SCRAPER_TEST_PYTHON"), sys.executable, shutil.which("python3")]
    python = next(
        (
            candidate
            for candidate in candidates
            if candidate
            and subprocess.run(
                [candidate, "-m", "pip", "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode == 0
            and subprocess.run(
                [candidate, "-m", "pip", "check"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode == 0
        ),
        None,
    )
    if python is None:
        pytest.skip("synthetic held-lock runtime requires a healthy Python with pip")
    worktree = tmp_path / "source"
    (worktree / "scripts").mkdir(parents=True)
    (worktree / "requirements.txt").write_text("", encoding="utf-8")
    (worktree / "scripts" / "check_scraper_runtime.py").write_text(
        "import sys\nprint('synthetic' if '--fingerprint' in sys.argv else '{}')\n",
        encoding="utf-8",
    )
    for args in (
        ["init", "-q"],
        ["add", "."],
        ["-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "fixture"],
    ):
        subprocess.run(["git", *args], cwd=worktree, check=True, capture_output=True)
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree, text=True).strip()

    runtime = tmp_path / "output" / "local-scraper"
    lock = runtime / "runner.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    venv = runtime / "prod-venvs" / "synthetic"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text(
        f"#!/bin/sh\nexec {shlex.quote(python)} \"$@\"\n", encoding="utf-8"
    )
    (venv / "bin" / "python").chmod(0o755)
    (venv / ".complete").touch()
    (venv / ".source-at-provision").write_text(source_sha + "\n", encoding="utf-8")
    freeze = subprocess.check_output([python, "-m", "pip", "freeze", "--all"], text=True)
    (venv / ".scraper-runtime-freeze.txt").write_text(
        "\n".join(sorted(freeze.splitlines())) + "\n", encoding="utf-8"
    )
    env = os.environ | {
        "SCRAPER_MAIN": str(tmp_path),
        "SCRAPER_WORKTREE": str(worktree),
        "SCRAPER_BASE_PYTHON": python,
        "SCRAPER_RUNNER_LOCK_OWNER_PID": str(os.getpid()),
        "SCRAPER_EXPECTED_SOURCE_SHA": source_sha,
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import subprocess,sys; sys.exit(subprocess.call(sys.argv[1:]))",
            str(SCRIPTS / "provision_scraper_runtime.sh"),
            "--held-lock",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (runtime / "prod-venv").resolve() == venv
    assert (lock / "pid").read_text(encoding="utf-8") == f"{os.getpid()}\n"
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree, text=True).strip() == source_sha

    env["SCRAPER_EXPECTED_SOURCE_SHA"] = "0" * 40 if source_sha != "0" * 40 else "f" * 40
    refused = subprocess.run(
        [
            sys.executable,
            "-c",
            "import subprocess,sys; sys.exit(subprocess.call(sys.argv[1:]))",
            str(SCRIPTS / "provision_scraper_runtime.sh"),
            "--held-lock",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert refused.returncode != 0
    assert "production source moved" in refused.stderr
    assert (runtime / "prod-venv").resolve() == venv
