"""Configuration behavior for the Flask session signing key."""
import os
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_secret_key(*, secret_key=None, railway_environment=None):
    env = os.environ.copy()
    env.pop("SECRET_KEY", None)
    env.pop("RAILWAY_ENVIRONMENT", None)
    if secret_key is not None:
        env["SECRET_KEY"] = secret_key
    if railway_environment is not None:
        env["RAILWAY_ENVIRONMENT"] = railway_environment

    return subprocess.run(
        [sys.executable, "-c", "from campaign_manager.config import Config; print(Config.SECRET_KEY)"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_secret_key_generates_a_random_development_key():
    result = _load_secret_key()

    assert result.returncode == 0, result.stderr
    assert re.fullmatch(r"[0-9a-f]{48}\n", result.stdout)


def test_configured_railway_secret_key_is_preserved():
    result = _load_secret_key(
        secret_key="synthetic-test-secret",
        railway_environment="production",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "synthetic-test-secret\n"


def test_missing_railway_secret_key_fails_during_config_load():
    result = _load_secret_key(railway_environment="production")

    assert result.returncode != 0
    assert "SECRET_KEY must be set in production (Railway)" in result.stderr
