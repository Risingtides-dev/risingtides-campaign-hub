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


@pytest.fixture
def song_scrape_options(monkeypatch, tmp_path):
    import sys
    import types

    from src.scrapers import yt_dlp_runner

    cookies = tmp_path / "fixture-cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    proxy = "http://fixture-user:fixture-pass@proxy.invalid:8080/?fixture=1"
    monkeypatch.setenv("TIKTOK_PROXY", proxy)
    monkeypatch.setenv("TIKTOK_COOKIES_FILE", str(cookies))
    monkeypatch.setenv("TIKTOK_USER_AGENT", "fixture-agent")
    monkeypatch.delenv("TIKTOK_IMPERSONATE", raising=False)
    monkeypatch.delenv("TIKTOK_IMPERSONATE_TARGET", raising=False)
    monkeypatch.setitem(sys.modules, "yt_dlp", types.ModuleType("yt_dlp"))
    monkeypatch.setattr(yt_dlp_runner.shutil, "which", lambda _name: "/fixture/bin/yt-dlp")
    return proxy, str(cookies)


@pytest.mark.parametrize("target", [None, "chrome-110"])
def test_song_scrape_shared_options_preserve_results_and_date_window(
    monkeypatch, song_scrape_options, target
):
    import json
    import sys
    from datetime import datetime, timedelta

    from src.utils import get_post_links_by_song as song_scrape

    proxy, cookies = song_scrape_options
    if target:
        monkeypatch.setenv("TIKTOK_IMPERSONATE", "1")
        monkeypatch.setenv("TIKTOK_IMPERSONATE_TARGET", target)
    start = datetime(2026, 10, 6, 9, 30)
    end = start + timedelta(hours=1)
    rows = [
        {"timestamp": (start - timedelta(seconds=1)).timestamp(), "webpage_url": "https://fixture.invalid/old"},
        {
            "timestamp": (start + timedelta(minutes=23)).timestamp(),
            "webpage_url": "https://fixture.invalid/in-window",
            "track": "Fixture song",
            "artist": "Fixture artist",
            "view_count": 12,
            "like_count": 3,
            "upload_date": "20261006",
        },
        {"timestamp": (end + timedelta(seconds=1)).timestamp(), "webpage_url": "https://fixture.invalid/new"},
    ]
    captured = []

    def run(cmd, **kwargs):
        captured.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd, 1, stdout="\n".join(json.dumps(row) for row in rows), stderr="fixture warning"
        )

    monkeypatch.setattr(song_scrape.subprocess, "run", run)
    videos = song_scrape.scrape_account_videos(
        "@fixture.creator", start_datetime=start, end_datetime=end, limit=7
    )

    assert videos == [{
        "url": "https://fixture.invalid/in-window",
        "song": "Fixture song",
        "artist": "Fixture artist",
        "account": "@fixture.creator",
        "views": 12,
        "likes": 3,
        "upload_date": "20261006",
        "timestamp": start + timedelta(minutes=23),
    }]
    assert len(captured) == 1
    cmd, kwargs = captured[0]
    assert kwargs == {"capture_output": True, "text": True, "timeout": 120}
    assert cmd[:3] == [sys.executable, "-m", "yt_dlp"]
    assert cmd[-1] == "https://www.tiktok.com/@fixture.creator"
    for flag, value in [
        ("--playlist-end", "7"), ("--proxy", proxy), ("--cookies", cookies),
        ("--user-agent", "fixture-agent"), ("--retries", "3"),
        ("--fragment-retries", "3"), ("--socket-timeout", "30"),
    ]:
        assert cmd.count(flag) == 1
        assert cmd[cmd.index(flag) + 1] == value
    assert "--flat-playlist" in cmd and "--dump-json" in cmd
    if target:
        assert cmd.count("--impersonate") == 1
        assert cmd[cmd.index("--impersonate") + 1] == target
    else:
        assert "--impersonate" not in cmd


def test_song_command_explicit_legacy_target_overrides_once(monkeypatch, song_scrape_options):
    from src.utils import get_post_links_by_song as song_scrape

    proxy, cookies = song_scrape_options
    monkeypatch.setenv("TIKTOK_IMPERSONATE", "1")
    monkeypatch.setenv("TIKTOK_IMPERSONATE_TARGET", "chrome-110")
    cmd = song_scrape.build_yt_dlp_command("https://fixture.invalid/profile", 2, "safari")
    assert cmd.count("--impersonate") == 1
    assert cmd[cmd.index("--impersonate") + 1] == "safari"
    assert "--proxy" in cmd and "--cookies" in cmd
    assert cmd[cmd.index("--proxy") + 1] == proxy
    assert cmd[cmd.index("--cookies") + 1] == cookies
    assert cmd[-1] == "https://fixture.invalid/profile"


def test_song_scrape_native_crash_is_fatal_without_retry(monkeypatch, song_scrape_options):
    from src.utils import get_post_links_by_song as song_scrape

    calls = []

    def run(cmd, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(cmd, -signal.SIGABRT, stdout="{}", stderr="")

    monkeypatch.setattr(song_scrape.subprocess, "run", run)
    with pytest.raises(NativeSubprocessCrash, match="SIGABRT"):
        song_scrape.scrape_account_videos("@fixture.creator")
    assert calls == [{"capture_output": True, "text": True, "timeout": 120}]


def test_song_scrape_timeout_keeps_finite_account_attempts(monkeypatch, song_scrape_options):
    from src.utils import get_post_links_by_song as song_scrape

    calls = []

    def run(cmd, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(song_scrape.subprocess, "run", run)
    with pytest.raises(song_scrape.ScrapeError, match="Timeout after 120s"):
        song_scrape.scrape_account_videos("@fixture.creator")
    assert len(calls) == song_scrape.MAX_RETRIES == 3
    assert all(call["timeout"] == 120 for call in calls)


def test_song_scrape_rate_limit_backoff_then_success(monkeypatch, song_scrape_options):
    from src.utils import get_post_links_by_song as song_scrape

    attempts = []
    waits = []

    def run(cmd, **kwargs):
        attempts.append(kwargs)
        if len(attempts) < 3:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP Error 429")
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"webpage_url":"https://fixture.invalid/video"}', stderr=""
        )

    monkeypatch.setattr(song_scrape.subprocess, "run", run)
    monkeypatch.setattr(song_scrape.time, "sleep", waits.append)
    result = song_scrape.scrape_account_videos("@fixture.creator")
    assert len(result) == 1 and result[0]["url"] == "https://fixture.invalid/video"
    assert len(attempts) == 3 and waits == [60, 120]


def test_song_scrape_stderr_redacts_options_before_truncation(
    monkeypatch, song_scrape_options, capsys
):
    from src.utils import get_post_links_by_song as song_scrape

    proxy, cookies = song_scrape_options
    detail = "useful fixture failure " + "x" * 260 + proxy + " cookies " + cookies
    monkeypatch.setattr(
        song_scrape.subprocess, "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=detail),
    )
    with pytest.raises(song_scrape.ScrapeError) as exc_info:
        song_scrape.scrape_account_videos("@fixture.creator")
    output = capsys.readouterr().out
    error = str(exc_info.value)
    sensitive = [proxy, cookies, "fixture-user:fixture-pass"]
    assert not any(value in error or value in output for value in sensitive)
    assert "useful fixture failure" in error and "[redacted]" in error


def test_song_scrape_exception_argv_is_redacted(monkeypatch, song_scrape_options, capsys):
    from src.utils import get_post_links_by_song as song_scrape

    proxy, cookies = song_scrape_options

    def run(cmd, **_kwargs):
        raise RuntimeError("fixture runner refused argv " + repr(cmd))

    monkeypatch.setattr(song_scrape.subprocess, "run", run)
    with pytest.raises(song_scrape.ScrapeError) as exc_info:
        song_scrape.scrape_account_videos("@fixture.creator")
    output = capsys.readouterr().out
    error = str(exc_info.value)
    sensitive = [proxy, cookies, "fixture-user:fixture-pass"]
    assert not any(value in error or value in output for value in sensitive)
    assert "fixture runner refused argv" in error and "[redacted]" in error


@pytest.mark.parametrize("mode", ["stderr", "exception"])
def test_song_scrape_escaped_cookie_diagnostic_is_redacted(
    monkeypatch, song_scrape_options, tmp_path, capsys, mode
):
    from src.utils import get_post_links_by_song as song_scrape

    proxy, _cookies = song_scrape_options
    cookies = tmp_path / 'fixture-private-cookie-marker-"\'-\\-name.txt'
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("TIKTOK_COOKIES_FILE", str(cookies))
    suffix = " unrelated quote ' and backslash \\ stay"

    def run(cmd, **_kwargs):
        assert cmd[cmd.index("--cookies") + 1] == str(cookies)
        if mode == "exception":
            raise RuntimeError("fixture runner diagnostic " + repr(cmd) + suffix)
        detail = "fixture runner diagnostic " + repr(str(cookies)) + " " + repr(proxy) + suffix
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=detail)

    monkeypatch.setattr(song_scrape.subprocess, "run", run)
    with pytest.raises(song_scrape.ScrapeError) as exc_info:
        song_scrape.scrape_account_videos("@fixture.creator")
    output = capsys.readouterr().out
    error = str(exc_info.value)
    assert "fixture-private-cookie-marker" not in error + output
    assert not any(value in error + output for value in [proxy, str(cookies), "fixture-user:fixture-pass"])
    assert "fixture runner diagnostic" in error
    assert error.count("[redacted]") == 2
    assert suffix in error


@pytest.mark.parametrize("mode,reason", [
    ("nonzero", "forbidden"),
    ("empty", "empty_output"),
    ("timeout", "timeout"),
    ("exception", "unexpected"),
    ("invalid_json", "invalid_output"),
])
def test_master_tracker_source_failure_is_typed_and_does_not_print_secrets(
    monkeypatch, capsys, mode, reason,
):
    from src.scrapers import master_tracker
    from src.scrapers.yt_dlp_runner import NativeSubprocessCrash

    secret = "fixture-proxy-password"
    cached = [{"url": "https://www.tiktok.com/@creator/video/123", "account": "@creator"}]
    monkeypatch.setattr(master_tracker, "load_account_cache", lambda *_args: (cached, None))
    monkeypatch.setattr(master_tracker, "enrich_videos_with_sound_ids", lambda *_args: None)

    def run(cmd, **_kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired(cmd, 120, stderr=secret)
        if mode == "exception":
            raise RuntimeError(f"failed argv: {secret}")
        return subprocess.CompletedProcess(
            cmd, 1 if mode == "nonzero" else 0,
            stdout="bad json" if mode == "invalid_json" else "",
            stderr=f"HTTP Error 403: {secret}" if mode == "nonzero" else "",
        )

    monkeypatch.setattr(master_tracker.subprocess, "run", run)
    with pytest.raises(master_tracker.TikTokScrapeError) as exc_info:
        master_tracker.scrape_tiktok_account("@creator", use_cache=True)
    assert exc_info.value.reason == reason
    assert exc_info.value.cached_videos == cached
    assert secret not in str(exc_info.value) + capsys.readouterr().out


def test_master_tracker_valid_old_post_is_genuine_empty_not_fetch_error(monkeypatch):
    import json
    from datetime import date, datetime
    from src.scrapers import master_tracker

    row = {"webpage_url": "https://www.tiktok.com/@creator/video/123",
           "timestamp": datetime(2020, 1, 1).timestamp()}
    monkeypatch.setattr(
        master_tracker.subprocess, "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(row), stderr=""),
    )
    assert master_tracker.scrape_tiktok_account(
        "@creator", start_date=date(2026, 10, 1), use_cache=False,
    ) == []


def test_master_tracker_invalid_only_urls_are_source_failure(monkeypatch):
    import json
    from src.scrapers import master_tracker

    row = {"webpage_url": "https://www.tiktok.com/@x/not-a-video"}
    monkeypatch.setattr(
        master_tracker.subprocess, "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(row), stderr=""),
    )
    with pytest.raises(master_tracker.TikTokScrapeError) as exc_info:
        master_tracker.scrape_tiktok_account("@creator", use_cache=False)
    assert exc_info.value.reason == "invalid_output"
