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
    (runtime / "prod-venv").symlink_to(venv)
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

    env["SCRAPER_EXPECTED_SOURCE_SHA"] = source_sha
    (venv / ".scraper-runtime-freeze.txt").write_text("requests>=2\n", encoding="utf-8")
    refused_freeze = subprocess.run(
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
    assert refused_freeze.returncode != 0
    assert "prior scraper freeze is not a unique exact-version lock" in refused_freeze.stderr
    assert (runtime / "prod-venv").resolve() == venv


@pytest.mark.parametrize(
    ("mode", "expected_rc", "expected_stage", "scrapes"),
    [
        ("success", 0, "completed", 1),
        ("fail", 42, "runtime-reprovision", 0),
        ("timeout", 124, "runtime-reprovision-timeout", 0),
    ],
)
def test_wrapper_reconciles_missing_fingerprint_once_without_real_scrape(
    tmp_path: Path, mode: str, expected_rc: int, expected_stage: str, scrapes: int
):
    source = tmp_path / "source"
    scripts = source / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPTS / "pi_scrape_hourly.sh", scripts / "pi_scrape_hourly.sh")
    (source / "requirements.txt").write_text("", encoding="utf-8")
    (scripts / "check_scraper_runtime.py").write_text(
        "import sys\nprint('synthetic' if '--fingerprint' in sys.argv else '{}')\n",
        encoding="utf-8",
    )
    (scripts / "pi_active_campaigns_scrape.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "p=Path(os.environ['SCRAPER_TEST_SCRAPE_MARKER'])\n"
        "p.write_text(str(int(p.read_text()) + 1 if p.exists() else 1))\n",
        encoding="utf-8",
    )
    (scripts / "provision_scraper_runtime.sh").write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, shutil, sys, time\n"
        "assert sys.argv[1:] == ['--held-lock']\n"
        "r=pathlib.Path(os.environ['SCRAPER_MAIN'])/'output/local-scraper'\n"
        "assert (r/'runner.lock/pid').read_text().strip() == os.environ['SCRAPER_RUNNER_LOCK_OWNER_PID']\n"
        "mode=os.environ['SCRAPER_TEST_PROVISION_MODE']\n"
        "if mode == 'fail': sys.exit(42)\n"
        "if mode == 'timeout': time.sleep(30); sys.exit(1)\n"
        "v=r/'prod-venvs/synthetic'\n"
        "(v/'bin').mkdir(parents=True)\n"
        "shutil.copy2(r/'prod-venvs/prior/bin/python', v/'bin/python')\n"
        "(v/'.source-at-provision').write_text(os.environ['SCRAPER_EXPECTED_SOURCE_SHA']+'\\n')\n"
        "(v/'.scraper-runtime-freeze.txt').write_text('pip==0\\n')\n"
        "(v/'.complete').touch()\n"
        "link=r/'.candidate-link'; link.symlink_to(v); os.replace(link, r/'prod-venv')\n",
        encoding="utf-8",
    )
    (scripts / "provision_scraper_runtime.sh").chmod(0o755)
    for args in (
        ["init", "-q", "--initial-branch=main"],
        ["add", "."],
        ["-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "fixture"],
    ):
        subprocess.run(["git", *args], cwd=source, check=True, capture_output=True)
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=source, check=True)
    subprocess.run(["git", "push", "-q", "-u", "origin", "main"], cwd=source, check=True)

    runtime = tmp_path / "output" / "local-scraper"
    prior = runtime / "prod-venvs" / "prior"
    (prior / "bin").mkdir(parents=True)
    (prior / ".complete").touch()
    (prior / ".source-at-provision").write_text(source_sha + "\n", encoding="utf-8")
    (prior / "bin" / "python").write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = -m ] && [ \"$2\" = pip ]; then\n"
        "  if [ \"$3\" = check ]; then exit 0; fi\n"
        "  if [ \"$3\" = freeze ]; then printf 'pip==0\\n'; exit 0; fi\n"
        "fi\n"
        f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    (prior / "bin" / "python").chmod(0o755)
    (runtime / "prod-venv").symlink_to(prior)
    marker = tmp_path / "synthetic-scrape-count"
    env = os.environ | {
        "SCRAPER_MAIN": str(tmp_path),
        "SCRAPER_WORKTREE": str(source),
        "SCRAPER_BASE_PYTHON": sys.executable,
        "SCRAPER_REPROVISION_TIMEOUT_SECONDS": "1",
        "SCRAPER_TEST_PROVISION_MODE": mode,
        "SCRAPER_TEST_SCRAPE_MARKER": str(marker),
    }
    result = subprocess.run(
        ["zsh", str(scripts / "pi_scrape_hourly.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == expected_rc, result.stderr
    assert f'"stage": "{expected_stage}"' in (runtime / "SCRAPER_STATUS.json").read_text()
    assert (int(marker.read_text()) if marker.exists() else 0) == scrapes
    assert (runtime / "prod-venv").resolve() == (runtime / "prod-venvs" / ("synthetic" if mode == "success" else "prior"))
    assert not (runtime / "runner.lock").exists()
