#!/usr/bin/env zsh
set -euo pipefail

cd /Users/risingtidesdev/dev/risingtides-campaign-hub

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/opt/python@3.13/bin/python3.13}"
if [[ -x "$PWD/.venv/bin/python" ]]; then
  PYTHON_BIN="$PWD/.venv/bin/python"
elif [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

exec "$PYTHON_BIN" scripts/pi_active_campaigns_scrape.py --run --write-report --export --no-proxy
