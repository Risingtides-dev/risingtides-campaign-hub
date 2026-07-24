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

cleanup() {
  if [[ -n "$BUILDING" && -d "$BUILDING" ]]; then
    rm -rf "$BUILDING"
  fi
  if [[ $LOCK_HELD -eq 1 && -d "$RUNNER_LOCK" ]]; then
    rm -rf "$RUNNER_LOCK"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$RUNTIME_ROOT"
if ! mkdir "$RUNNER_LOCK" 2>/dev/null; then
  owner=""
  for attempt in {1..20}; do
    [[ -f "$RUNNER_LOCK/pid" ]] && owner=$(<"$RUNNER_LOCK/pid")
    [[ "$owner" == <-> ]] && break
    sleep 0.1
  done
  if [[ "$owner" != <-> ]]; then
    print -u2 -- "ambiguous scraper runner lock; refusing to provision"
    exit 75
  fi
  if kill -0 "$owner" 2>/dev/null; then
    print -u2 -- "scraper runner is active as pid=$owner; refusing to provision"
    exit 75
  fi
  rm -rf "$RUNNER_LOCK"
  mkdir "$RUNNER_LOCK"
fi
print -r -- "$$" > "$RUNNER_LOCK/pid"
LOCK_HELD=1

[[ -x "$BASE_PY" ]] || { print -u2 -- "missing base Python: $BASE_PY"; exit 1; }
cd "$WT"
git fetch origin --quiet
git reset --hard origin/main --quiet
git clean -fdq -e .venv -e output

REQ="$WT/requirements.txt"
GUARD="$WT/scripts/check_scraper_runtime.py"
[[ -f "$REQ" && -f "$GUARD" ]] || { print -u2 -- "deployed runtime guard is missing"; exit 1; }

fingerprint="$($BASE_PY "$GUARD" --requirements "$REQ" --fingerprint)"
VENV="$VENV_ROOT/$fingerprint"
mkdir -p "$VENV_ROOT"

if [[ ! -f "$VENV/.complete" ]]; then
  rm -rf "$VENV"
  BUILDING="$VENV"
  "$BASE_PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$REQ"
  "$VENV/bin/python" "$GUARD" --requirements "$REQ" > "$VENV/.scraper-runtime-manifest.json"
  "$VENV/bin/python" -m pip check
  "$VENV/bin/python" -m yt_dlp --list-impersonate-targets 2>&1 \
    | grep -qi -- "$TARGET" || {
      print -u2 -- "impersonation target unavailable: $TARGET"
      exit 1
    }
  "$VENV/bin/python" -m pip freeze --all | LC_ALL=C sort \
    > "$VENV/.scraper-runtime-freeze.txt"
  print -r -- "$fingerprint" > "$VENV/.scraper-runtime-fingerprint"
  print -r -- "$(git rev-parse HEAD)" > "$VENV/.source-at-provision"
  touch "$VENV/.complete"
  BUILDING=""
else
  "$VENV/bin/python" "$GUARD" --requirements "$REQ" >/dev/null
  "$VENV/bin/python" -m pip check >/dev/null
  freeze_tmp="$RUNTIME_ROOT/.provision-freeze.$$"
  "$VENV/bin/python" -m pip freeze --all | LC_ALL=C sort > "$freeze_tmp"
  cmp -s "$freeze_tmp" "$VENV/.scraper-runtime-freeze.txt" || {
    rm -f "$freeze_tmp"
    print -u2 -- "existing immutable runtime was mutated: $VENV"
    exit 1
  }
  rm -f "$freeze_tmp"
fi

link_tmp="$RUNTIME_ROOT/.prod-venv-link.$$"
rm -f "$link_tmp"
ln -s "$VENV" "$link_tmp"
"$BASE_PY" -c 'import os,sys; os.replace(sys.argv[1], sys.argv[2])' \
  "$link_tmp" "$CURRENT_VENV"

print -- "provisioned scraper runtime"
print -- "fingerprint=$fingerprint"
print -- "venv=$VENV"
print -- "source=$(git rev-parse HEAD)"
