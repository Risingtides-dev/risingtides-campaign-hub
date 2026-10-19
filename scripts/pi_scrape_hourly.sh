#!/usr/bin/env zsh
# Canonical launchd runner for the production local scraper.
# Deploy with: install -m 0755 scripts/pi_scrape_hourly.sh \
#   output/local-scraper/run_prod_scrape.sh
set -uo pipefail

MAIN="${SCRAPER_MAIN:-/Users/risingtidesdev/dev/risingtides-campaign-hub}"
WT="${SCRAPER_WORKTREE:-/Users/risingtidesdev/dev/rt-scraper-prod}"
BASE_PY="${SCRAPER_BASE_PYTHON:-/opt/homebrew/opt/python@3.14/bin/python3.14}"
RUNTIME_ROOT="$MAIN/output/local-scraper"
VENV_ROOT="$RUNTIME_ROOT/prod-venvs"
CURRENT_VENV="$RUNTIME_ROOT/prod-venv"
STATUS="$RUNTIME_ROOT/SCRAPER_STATUS.json"
RUNNER_LOCK="$RUNTIME_ROOT/runner.lock"
LOCK_HELD=0
FREEZE_TMP=""
LOCK_INODE=""

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }

write_status() {  # $1=ok(true|false|null) $2=stage $3=rc
  mkdir -p "${STATUS:h}"
  local tmp="${STATUS}.tmp.$$"
  print -r -- "{\"ok\": $1, \"stage\": \"$2\", \"rc\": ${3:-0}, \"at\": \"$(stamp)\"}" > "$tmp"
  mv -f "$tmp" "$STATUS"
}

cleanup() {
  [[ -n "$FREEZE_TMP" ]] && rm -f "$FREEZE_TMP"
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

fail() {  # $1=stage $2=rc
  write_status false "$1" "${2:-1}"
  print -u2 -- "[pi_scrape_hourly] FAILED stage=$1 rc=${2:-1} at $(stamp)"
  exit "${2:-1}"
}

acquire_runner_lock() {
  mkdir -p "$RUNTIME_ROOT"
  if mkdir "$RUNNER_LOCK" 2>/dev/null; then
    print -r -- "$$" > "$RUNNER_LOCK/pid"
    LOCK_INODE=$(stat -f %i "$RUNNER_LOCK")
    LOCK_HELD=1
    return 0
  fi

  local owner=""
  local attempt
  # The lock owner creates the directory before publishing its PID. Wait for
  # that publication window; an ownerless/invalid lock is ambiguous and must
  # fail closed rather than being deleted under a live process.
  for attempt in {1..20}; do
    [[ -f "$RUNNER_LOCK/pid" ]] && owner=$(<"$RUNNER_LOCK/pid")
    [[ "$owner" == <-> ]] && break
    sleep 0.1
  done
  if [[ "$owner" != <-> ]]; then
    print -u2 -- "[pi_scrape_hourly] ambiguous runner lock; refusing to start"
    exit 75
  fi
  if kill -0 "$owner" 2>/dev/null; then
    print -u2 -- "[pi_scrape_hourly] already running as pid=$owner"
    exit 75
  fi

  print -u2 -- "[pi_scrape_hourly] stale runner lock pid=$owner; manual reconciliation required"
  exit 75
}

acquire_runner_lock
write_status null "starting" 0

[[ -x "$BASE_PY" ]] || fail "base-python-missing" 1
[[ -d "$WT/.git" || -f "$WT/.git" ]] || fail "worktree-missing" 1
cd "$WT" || fail "worktree-cd" 1

# Production source remains a hard-reset deployment worktree.
git fetch origin --quiet 2>/dev/null || print -u2 -- "[pi_scrape_hourly] warn: git fetch failed; using cached origin/main"
git reset --hard origin/main --quiet 2>/dev/null || fail "git-reset" 1
git clean -fdq -e .venv -e output 2>/dev/null || fail "git-clean" 1

REQ="$WT/requirements.txt"
GUARD="$WT/scripts/check_scraper_runtime.py"
CANONICAL="$WT/scripts/pi_scrape_hourly.sh"
[[ -f "$REQ" ]] || fail "requirements-missing" 1
[[ -f "$GUARD" ]] || fail "runtime-guard-missing" 1
[[ -f "$CANONICAL" ]] || fail "canonical-runner-missing" 1
PROVISIONER="$WT/scripts/provision_scraper_runtime.sh"
[[ -f "$PROVISIONER" ]] || fail "runtime-provisioner-missing" 1

# launchd executes an installed copy under output/. Refuse invisible launcher
# edits by comparing it with the reset production source, not the dev checkout.
if [[ "${0:A}" != "${CANONICAL:A}" ]]; then
  deployed_sha=$(shasum -a 256 "${0:A}" | awk '{print $1}')
  canonical_sha=$(shasum -a 256 "$CANONICAL" | awk '{print $1}')
  [[ "$deployed_sha" == "$canonical_sha" ]] || fail "runner-drift" 1
fi

source_sha=$(git rev-parse HEAD) || fail "source-inspect" 1
fingerprint="$($BASE_PY "$GUARD" --requirements "$REQ" --fingerprint)" || fail "runtime-fingerprint" 1
EXPECTED_VENV="$VENV_ROOT/$fingerprint"
if [[ ! -f "$EXPECTED_VENV/.complete" ]]; then
  # Only a base-Python drift at the same deployed source may self-heal.
  [[ -L "$CURRENT_VENV" ]] || fail "runtime-not-provisioned" 1
  prior_venv="$($BASE_PY -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$CURRENT_VENV")" || fail "runtime-inspect" 1
  [[ "$prior_venv" == "$VENV_ROOT"/* && -f "$prior_venv/.complete" ]] || fail "runtime-not-provisioned" 1
  [[ -f "$prior_venv/.source-at-provision" && "$(<"$prior_venv/.source-at-provision")" == "$source_sha" ]] || fail "runtime-source-changed" 1
  free_kib=$(df -Pk "$RUNTIME_ROOT" | awk 'NR==2 {print $4}')
  [[ "$free_kib" == <-> && "$free_kib" -ge 8388608 ]] || fail "runtime-capacity" 1
  SCRAPER_RUNNER_LOCK_OWNER_PID="$$" SCRAPER_EXPECTED_SOURCE_SHA="$source_sha" \
    "$BASE_PY" - "$PROVISIONER" <<'PY_REPROVISION'
import os
import signal
import subprocess
import sys

proc = subprocess.Popen([sys.argv[1], '--held-lock'], start_new_session=True)
try:
    rc = proc.wait(timeout=600)
except subprocess.TimeoutExpired:
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    rc = 124
sys.exit(rc)
PY_REPROVISION
  [[ $? -eq 0 ]] || fail "runtime-reprovision" 1
  [[ "$(git rev-parse HEAD)" == "$source_sha" ]] || fail "runtime-source-changed" 1
  [[ -f "$EXPECTED_VENV/.complete" ]] || fail "runtime-not-provisioned" 1
fi
[[ -L "$CURRENT_VENV" ]] || fail "runtime-not-active" 1
active_venv="$($BASE_PY -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$CURRENT_VENV")" || fail "runtime-inspect" 1
[[ "$active_venv" == "$EXPECTED_VENV" ]] || fail "runtime-release-mismatch" 1

PY="$CURRENT_VENV/bin/python"
"$PY" "$GUARD" --requirements "$REQ" || fail "dependency-drift" 1
"$PY" -m pip check || fail "pip-check" 1

# Detect any mutation after provisioning, including loose-range dependencies.
FREEZE_TMP="$RUNTIME_ROOT/.runtime-freeze.$$"
"$PY" -m pip freeze --all | LC_ALL=C sort > "$FREEZE_TMP" || fail "freeze-inspect" 1
cmp -s "$FREEZE_TMP" "$EXPECTED_VENV/.scraper-runtime-freeze.txt" || fail "runtime-mutated" 1
rm -f "$FREEZE_TMP"
FREEZE_TMP=""

write_status null "scraping" 0
"$PY" scripts/pi_active_campaigns_scrape.py --run --write-report --export --no-proxy
rc=$?
if [[ $rc -eq 76 ]]; then
  write_status null "skipped" 0
  print -- "[pi_scrape_hourly] skipped: another campaign refresh owns the Hub lease at $(stamp)"
  exit 0
fi
[[ $rc -eq 77 ]] && fail "export-exit" "$rc"
[[ $rc -eq 0 ]] || fail "scrape-exit" "$rc"

write_status true "completed" 0
print -- "[pi_scrape_hourly] ok at $(stamp)"
