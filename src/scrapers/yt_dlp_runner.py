"""Centralized yt-dlp command builder + runner for TikTok scraping.

Why this exists:
    Every scraper was building its own raw `yt-dlp <url>` command with no
    cookies, no user-agent, no impersonation, no retries. TikTok has been
    aggressively blocking those requests — return code 0 but stdout is
    empty, which the callers interpret as "no new videos" and silently
    move on. Result: cron runs report 139/139 success but 0 new matches
    across the entire active campaign roster.

    This module gives every scraper a single hardened entry point.

Hardening strategy (each is a distinct lever, all controlled by env vars):

    1. **Pinned yt-dlp version** — pip install yt-dlp without a version
       pulls whatever's latest at Docker build time, so the prod deploy's
       behavior changes between rebuilds. Pin in requirements.txt instead.

    2. **TIKTOK_COOKIES_FILE** — path to a Netscape-format cookies file.
       Logged-in cookies bypass most of TikTok's bot wall. Mount via
       Railway volume or env var pointing at a written file.

    3. **TIKTOK_PROXY** — optional HTTP/SOCKS proxy URL. yt-dlp accepts
       --proxy <url>. Use for residential/rotating IPs when cookies aren't
       enough.

    4. **--extractor-args "tiktok:impersonation_target=chrome"** — yt-dlp
       has a TikTok-specific impersonation knob. Combined with curl_cffi
       backend (already a yt-dlp dep), this mimics a real browser TLS
       fingerprint instead of Python's giveaway requests-style handshake.

    5. **--user-agent** — explicit modern Chrome UA, since yt-dlp's
       default UA leaks "yt-dlp/<version>" in some code paths.

    6. **--retries / --fragment-retries** — TikTok intermittently 429s
       even successful sessions; let yt-dlp back off and retry instead of
       failing the whole creator scrape on a single hiccup.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _yt_dlp_base() -> List[str]:
    """Base command — prefer THIS interpreter's yt_dlp module, PATH binary last.

    The venv's yt-dlp is the one whose deps we control (curl_cffi for
    --impersonate). Preferring the PATH binary bit us on 2026-06-28: a brew
    upgrade replaced /opt/homebrew/bin/yt-dlp with a build lacking curl_cffi,
    and every local scrape silently returned 0 videos ("Impersonate target
    not available") until caught on 2026-07-01. A random PATH binary must
    never outrank the pinned venv install.
    """
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def build_tiktok_cmd(
    target_url: str,
    *,
    flat_playlist: bool = True,
    dump_json: bool = True,
    playlist_end: Optional[int] = None,
    extra: Optional[List[str]] = None,
) -> List[str]:
    """Build a yt-dlp command for TikTok with all hardening applied.

    Args:
        target_url: profile URL or video URL.
        flat_playlist: True for profile listings (don't fetch each video).
        dump_json: True to emit JSON per video on stdout (parsed by callers).
        playlist_end: max number of videos when scraping a profile.
        extra: extra args appended verbatim before the URL.
    """
    cmd: List[str] = _yt_dlp_base()

    if flat_playlist:
        cmd.append("--flat-playlist")
    if dump_json:
        cmd.append("--dump-json")
    if playlist_end is not None:
        cmd.extend(["--playlist-end", str(playlist_end)])

    # Hardening
    cmd.extend([
        "--user-agent", os.environ.get("TIKTOK_USER_AGENT", _DEFAULT_UA),
        "--retries", "3",
        "--fragment-retries", "3",
        "--socket-timeout", "30",
    ])

    # Impersonation: yt-dlp's `--impersonate` requires curl_cffi installed
    # AND a matching impersonate target available at runtime. yt-dlp 2026.x
    # is picky about target names — generic "chrome" often doesn't work,
    # specific versions like "chrome-110" or "edge-99" do. To avoid breaking
    # the scraper when the target isn't available, this is OFF by default.
    # Set TIKTOK_IMPERSONATE=1 + TIKTOK_IMPERSONATE_TARGET=<exact-name> to
    # enable. Use `python -m yt_dlp --list-impersonate-targets` to find the
    # available names on your system.
    if os.environ.get("TIKTOK_IMPERSONATE", "0") == "1":
        target = os.environ.get("TIKTOK_IMPERSONATE_TARGET", "chrome").strip()
        if target:
            cmd.extend(["--impersonate", target])

    cookies_file = (os.environ.get("TIKTOK_COOKIES_FILE") or "").strip()
    if cookies_file and os.path.exists(cookies_file):
        cmd.extend(["--cookies", cookies_file])

    proxy = (os.environ.get("TIKTOK_PROXY") or "").strip()
    if proxy:
        cmd.extend(["--proxy", proxy])

    if extra:
        cmd.extend(extra)

    cmd.append(target_url)
    return cmd


def run_tiktok_cmd(
    cmd: List[str],
    *,
    timeout: int = 90,
) -> subprocess.CompletedProcess:
    """Run a yt-dlp command and return the CompletedProcess.

    Caller is responsible for parsing stdout. Returns the raw process so
    callers can inspect returncode + stderr for diagnostics.
    """
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def parse_jsonl(stdout: str) -> List[Dict]:
    """Parse newline-delimited JSON from yt-dlp's --dump-json output."""
    out: List[Dict] = []
    for line in (stdout or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def diagnose_failure(stderr: str) -> str:
    """Classify a yt-dlp stderr blob into a short reason code.

    Used by the scheduler's outcome counters so we can tell rate-limit
    from format-change from network-down at a glance.
    """
    s = (stderr or "").lower()
    if "http error 429" in s or "too many requests" in s:
        return "rate_limited"
    if "http error 403" in s or "forbidden" in s:
        return "forbidden"
    if "http error 404" in s or "not found" in s:
        return "not_found"
    if "private" in s or "login required" in s:
        return "auth_required"
    if "no video formats" in s or "unable to extract" in s:
        return "extractor_broken"
    if "timed out" in s or "timeout" in s:
        return "timeout"
    if "unavailable" in s:
        return "unavailable"
    return "unknown"
