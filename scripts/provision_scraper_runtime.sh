#!/usr/bin/env zsh
# Explicitly build and atomically activate an immutable production scraper venv.
set -euo pipefail

MAIN="${SCRAPER_MAIN:-/Users/risingtidesdev/dev/risingtides-campaign-hub}"
WT="${SCRAPER_WORKTREE:-/Users/risingtidesdev/dev/rt-scraper-prod}"
BASE_PY="${SCRAPER_BASE_PYTHON:-/opt/homebrew/opt/python@3.14/bin/python3.14}"
RUNTIME_ROOT="$MAIN/output/local-scraper"
VENV_ROOT="$RUNTIME_ROOT/prod-venvs"
CURRENT_VENV="$RUNTIME_ROOT/prod-venv"
RUNNER_LOCK="$RUNTIME_ROOT/runner.lock"
TARGET="${SCRAPER_IMPERSONATE_TARGET:-chrome-136}"
LOCK_HELD=0
BUILDING=""
LOCK_INODE=""
HELD_LOCK=0

cleanup() {
  if [[ -n "$BUILDING" && -d "$BUILDING" ]]; then
    rm -rf "$BUILDING"
  fi
  if [[ $LOCK_HELD -eq 1 && -d "$RUNNER_LOCK" ]]; then
    local owner="" inode=""
    [[ -f "$RUNNER_LOCK/pid" ]] && owner=$(<"$RUNNER_LOCK/pid")
    inode=$(stat -f %i "$RUNNER_LOCK" 2>/dev/null || true)
    if [[ "$owner" == "$$" && "$inode" == "$LOCK_INODE" ]]; then
      rm -f "$RUNNER_LOCK/pid"
      rmdir "$RUNNER_LOCK" 2>/dev/null || true
    fi
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$RUNTIME_ROOT"
if [[ ${1:-} == "--held-lock" && $# -eq 1 ]]; then
  HELD_LOCK=1
  owner="${SCRAPER_RUNNER_LOCK_OWNER_PID:-}"
  expected="${SCRAPER_EXPECTED_SOURCE_SHA:-}"
  # Only the bounded watchdog child of the current lock owner can use this
  # mode. The wrapper retains its lock until this process has exited.
  grandparent=$(ps -p "$PPID" -o ppid= 2>/dev/null | tr -d ' ')
  if [[ "$owner" != <-> || "$grandparent" != "$owner" ]] || ! [[ "$expected" =~ '^[0-9a-f]{40}$' ]]; then
    print -u2 -- "held scraper lock proof missing"
    exit 75
  fi
  if [[ ! -f "$RUNNER_LOCK/pid" || "$(<"$RUNNER_LOCK/pid")" != "$owner" ]] || ! kill -0 "$owner" 2>/dev/null; then
    print -u2 -- "scraper runner lock owner changed"
    exit 75
  fi
elif [[ $# -eq 0 ]]; then
  if ! mkdir "$RUNNER_LOCK" 2>/dev/null; then
    owner=""
    for attempt in {1..20}; do
      [[ -f "$RUNNER_LOCK/pid" ]] && owner=$(<"$RUNNER_LOCK/pid")
      [[ "$owner" == <-> ]] && break
      sleep 0.1
    done
    if [[ "$owner" == <-> ]] && kill -0 "$owner" 2>/dev/null; then
      print -u2 -- "scraper runner is active as pid=$owner; refusing to provision"
    else
      print -u2 -- "stale or ambiguous scraper runner lock; manual reconciliation required"
    fi
    exit 75
  fi
  print -r -- "$$" > "$RUNNER_LOCK/pid"
  LOCK_INODE=$(stat -f %i "$RUNNER_LOCK")
  LOCK_HELD=1
else
  print -u2 -- "unsupported provisioner argument"
  exit 2
fi

[[ -x "$BASE_PY" ]] || { print -u2 -- "missing base Python: $BASE_PY"; exit 1; }
cd "$WT"
if [[ $HELD_LOCK -eq 1 ]]; then
  [[ "$(git rev-parse HEAD)" == "$expected" && -z "$(git status --porcelain --untracked-files=no)" ]] || {
    print -u2 -- "production source moved during locked provision"
    exit 1
  }
  # Preserve the complete previously approved distribution set. Loose ranges
  # in requirements.txt must not be re-resolved by an unattended recovery.
  [[ -L "$CURRENT_VENV" ]] || exit 1
  prior_venv="$($BASE_PY -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$CURRENT_VENV")"
  [[ "$prior_venv" == "$VENV_ROOT"/* && -f "$prior_venv/.complete" ]] || exit 1
  PRIOR_FREEZE="$prior_venv/.scraper-runtime-freeze.txt"
  prior_source=""
  [[ -f "$prior_venv/.source-at-provision" ]] && prior_source=$(<"$prior_venv/.source-at-provision")
  if [[ "$prior_source" != "$expected" ]]; then
    attestation="$RUNTIME_ROOT/source-attestations/$expected.${prior_venv:t}"
    [[ -f "$PRIOR_FREEZE" && -f "$attestation" ]] || exit 1
    freeze_sha=$(shasum -a 256 "$PRIOR_FREEZE" | awk '{print $1}')
    [[ "$(<"$attestation")" == "$freeze_sha" ]] || exit 1
  fi
  # The stored freeze is an input to unattended installation. Require it to
  # match the installed prior runtime, even when its source SHA already matches.
  prior_freeze_actual="$RUNTIME_ROOT/.prior-freeze.$$"
  if ! "$prior_venv/bin/python" -m pip freeze --all | LC_ALL=C sort > "$prior_freeze_actual"; then
    rm -f "$prior_freeze_actual"
    print -u2 -- "prior scraper runtime cannot be inspected; manual reconciliation required"
    exit 1
  fi
  if ! cmp -s "$PRIOR_FREEZE" "$prior_freeze_actual"; then
    rm -f "$prior_freeze_actual"
    print -u2 -- "prior scraper freeze differs from installed distributions"
    exit 1
  fi
  rm -f "$prior_freeze_actual"
  "$BASE_PY" - "$PRIOR_FREEZE" <<'PY_FREEZE'
import pathlib, re, sys
rows = pathlib.Path(sys.argv[1]).read_text().splitlines()
names = [row.split('==', 1)[0].lower().replace('_', '-') for row in rows]
if not rows or len(names) != len(set(names)) or any(
    re.fullmatch(r'[A-Za-z0-9_.-]+==[A-Za-z0-9_.!+~:-]+', row) is None
    for row in rows
):
    raise SystemExit('prior scraper freeze is not a unique exact-version lock')
PY_FREEZE
else
  git fetch origin --quiet
  git reset --hard origin/main --quiet
  git clean -fdq -e .venv -e output
fi
source_sha=$(git rev-parse HEAD)

REQ="$WT/requirements.txt"
GUARD="$WT/scripts/check_scraper_runtime.py"
[[ -f "$REQ" && -f "$GUARD" ]] || { print -u2 -- "deployed runtime guard is missing"; exit 1; }

[[ $HELD_LOCK -eq 0 || ( "$(git rev-parse HEAD)" == "$expected" && -z "$(git status --porcelain --untracked-files=no)" ) ]] || {
  print -u2 -- "production source moved before runtime fingerprint"
  exit 1
}
fingerprint="$($BASE_PY "$GUARD" --requirements "$REQ" --fingerprint)"
VENV="$VENV_ROOT/$fingerprint"
mkdir -p "$VENV_ROOT"

if [[ ! -f "$VENV/.complete" ]]; then
  rm -rf "$VENV"
  BUILDING="$VENV"
  "$BASE_PY" -m venv "$VENV"
  if [[ $HELD_LOCK -eq 1 ]]; then
    "$VENV/bin/python" -m pip install --disable-pip-version-check --no-deps -r "$PRIOR_FREEZE"
  else
    "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$REQ"
  fi
  "$VENV/bin/python" "$GUARD" --requirements "$REQ" > "$VENV/.scraper-runtime-manifest.json"
  "$VENV/bin/python" -m pip check
  "$VENV/bin/python" -m yt_dlp --list-impersonate-targets 2>&1 \
    | grep -qi -- "$TARGET" || {
      print -u2 -- "impersonation target unavailable: $TARGET"
      exit 1
    }
  "$VENV/bin/python" -m pip freeze --all | LC_ALL=C sort \
    > "$VENV/.scraper-runtime-freeze.txt"
  if [[ $HELD_LOCK -eq 1 ]]; then
    cmp -s "$VENV/.scraper-runtime-freeze.txt" "$PRIOR_FREEZE" || {
      print -u2 -- "recovered runtime differs from approved distribution freeze"
      exit 1
    }
  fi
  print -r -- "$fingerprint" > "$VENV/.scraper-runtime-fingerprint"
  print -r -- "$(git rev-parse HEAD)" > "$VENV/.source-at-provision"
  touch "$VENV/.complete"
  BUILDING=""
else
  "$VENV/bin/python" "$GUARD" --requirements "$REQ" >/dev/null
  "$VENV/bin/python" -m pip check >/dev/null
  "$VENV/bin/python" -m yt_dlp --list-impersonate-targets 2>&1 \
    | grep -qi -- "$TARGET" || {
      print -u2 -- "impersonation target unavailable: $TARGET"
      exit 1
    }
  freeze_tmp="$RUNTIME_ROOT/.provision-freeze.$$"
  "$VENV/bin/python" -m pip freeze --all | LC_ALL=C sort > "$freeze_tmp"
  cmp -s "$freeze_tmp" "$VENV/.scraper-runtime-freeze.txt" || {
    rm -f "$freeze_tmp"
    print -u2 -- "existing immutable runtime was mutated: $VENV"
    exit 1
  }
  rm -f "$freeze_tmp"
  if [[ $HELD_LOCK -eq 1 ]]; then
    cmp -s "$VENV/.scraper-runtime-freeze.txt" "$PRIOR_FREEZE" || {
      print -u2 -- "existing runtime differs from approved distribution freeze"
      exit 1
    }
  fi
fi

[[ "$(git rev-parse HEAD)" == "$source_sha" && -z "$(git status --porcelain --untracked-files=no)" ]] || {
  print -u2 -- "production source moved before runtime activation or attestation"
  exit 1
}
attest_dir="$RUNTIME_ROOT/source-attestations"
mkdir -p "$attest_dir"
freeze_sha=$(shasum -a 256 "$VENV/.scraper-runtime-freeze.txt" | awk '{print $1}')
attest_tmp="$attest_dir/.attest.$$"
(umask 077; print -r -- "$freeze_sha" > "$attest_tmp")
mv -f "$attest_tmp" "$attest_dir/$source_sha.$fingerprint"
link_tmp="$RUNTIME_ROOT/.prod-venv-link.$$"
rm -f "$link_tmp"
ln -s "$VENV" "$link_tmp"
"$BASE_PY" -c 'import os,sys; os.replace(sys.argv[1], sys.argv[2])' \
  "$link_tmp" "$CURRENT_VENV"

print -- "provisioned scraper runtime"
print -- "fingerprint=$fingerprint"
print -- "venv=$VENV"
print -- "source=$(git rev-parse HEAD)"
