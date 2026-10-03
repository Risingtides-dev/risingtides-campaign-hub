#!/usr/bin/env python3
"""Fail closed when the scraper runtime does not match deployed exact pins."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
from typing import Callable, Dict, Iterable

CRITICAL_DISTRIBUTIONS = ("yt-dlp", "curl-cffi")
_EXACT_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)")


def canonical_name(name: str) -> str:
    """Apply the package-name normalization needed by our requirements file."""
    return re.sub(r"[-_.]+", "-", name).lower()


def exact_pins(requirements_path: Path) -> Dict[str, str]:
    """Return normalized distribution names with exact ``==`` pins."""
    pins: Dict[str, str] = {}
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        match = _EXACT_PIN.match(line)
        if match:
            pins[canonical_name(match.group(1))] = match.group(2)
    return pins


def runtime_fingerprint(requirements_path: Path) -> dict:
    """Fingerprint dependency inputs and the Python ABI/platform."""
    requirements_sha = hashlib.sha256(requirements_path.read_bytes()).hexdigest()
    runtime = {
        "executable": os.path.realpath(sys.executable),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "cache_tag": sys.implementation.cache_tag,
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "macos": platform.mac_ver()[0],
    }
    payload = json.dumps(
        {"requirements_sha256": requirements_sha, "runtime": runtime},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "fingerprint": hashlib.sha256(payload).hexdigest(),
        "requirements_sha256": requirements_sha,
        "runtime": runtime,
    }


def runtime_report(
    requirements_path: Path,
    required: Iterable[str] = CRITICAL_DISTRIBUTIONS,
    version_lookup: Callable[[str], str] = metadata.version,
) -> dict:
    """Compare installed critical packages with exact deployed pins."""
    pins = exact_pins(requirements_path)
    packages = {}
    errors = []

    for raw_name in required:
        name = canonical_name(raw_name)
        expected = pins.get(name)
        installed = None
        if expected is None:
            errors.append(f"{name} is not exactly pinned in {requirements_path}")
        try:
            installed = version_lookup(name)
        except metadata.PackageNotFoundError:
            errors.append(f"{name} is not installed")
        if expected is not None and installed is not None and installed != expected:
            errors.append(f"{name} installed={installed} expected={expected}")
        packages[name] = {
            "expected": expected,
            "installed": installed,
            "matches": bool(expected is not None and installed == expected),
        }

    return {
        "ok": not errors,
        "requirements": str(requirements_path),
        "packages": packages,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument(
        "--fingerprint",
        action="store_true",
        help="print only the runtime/input fingerprint",
    )
    args = parser.parse_args()

    requirements_path = args.requirements.resolve()
    if args.fingerprint:
        print(runtime_fingerprint(requirements_path)["fingerprint"])
        return 0

    report = runtime_report(requirements_path)
    report["runtime_fingerprint"] = runtime_fingerprint(requirements_path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
