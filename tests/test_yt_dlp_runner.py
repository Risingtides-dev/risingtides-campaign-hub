from __future__ import annotations

import signal
import subprocess

import pytest

from src.scrapers.yt_dlp_runner import (
    NativeSubprocessCrash,
    raise_for_native_crash,
)


def _result(returncode: int) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["yt-dlp"], returncode, stdout="", stderr="")


def test_normal_and_python_error_exit_codes_do_not_look_like_native_crashes():
    raise_for_native_crash(_result(0))
    raise_for_native_crash(_result(1))


def test_sigabrt_is_raised_with_actionable_context():
    with pytest.raises(NativeSubprocessCrash) as exc_info:
        raise_for_native_crash(
            _result(-signal.SIGABRT),
            context="yt-dlp for @creator",
        )

    error = exc_info.value
    assert error.returncode == -signal.SIGABRT
    assert error.signal_name == "SIGABRT"
    assert "yt-dlp for @creator terminated by native signal SIGABRT" in str(error)


def test_unknown_negative_returncode_is_still_fatal():
    with pytest.raises(NativeSubprocessCrash, match="SIGNAL_999"):
        raise_for_native_crash(_result(-999))


def test_master_tracker_does_not_convert_native_crash_to_cached_success(monkeypatch):
    from src.scrapers import master_tracker

    monkeypatch.setattr(
        master_tracker.subprocess,
        "run",
        lambda *_args, **_kwargs: _result(-signal.SIGABRT),
    )

    with pytest.raises(NativeSubprocessCrash):
        master_tracker.scrape_tiktok_account(
            "@creator",
            limit=1,
            use_cache=False,
        )
