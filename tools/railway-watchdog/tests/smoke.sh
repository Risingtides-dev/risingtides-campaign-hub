#!/bin/bash
# Local end-to-end test: `wrangler dev` (local mode, local KV) + tests/mock.mjs standing in for
# Railway, a health URL and GitHub. FAKE secrets only; no real network call leaves this machine.
# Replays the 2026-10-06 outage and the guard rails. ~2.5 min. Usage: bash tests/smoke.sh
set -u
cd "$(dirname "$0")/.." || exit 1
MOCK_PORT=${MOCK_PORT:-18797}; DEV_PORT=${DEV_PORT:-18798}
W="http://127.0.0.1:$DEV_PORT"; M="http://127.0.0.1:$MOCK_PORT"
TMP=$(mktemp -d); DEV_PID=; MOCK_PID=
trap 'kill $MOCK_PID $DEV_PID 2>/dev/null; wait 2>/dev/null; rm -rf "$TMP"' EXIT
cat > "$TMP/secrets.env" <<S
RAILWAY_TOKEN=fake-railway-token
GITHUB_TOKEN=fake-github-token
S
WATCH="[{\"env\":\"e1\"},{\"env\":\"e2\",\"health\":{\"lab\":\"$M/health/lab\"}}]"
fails=0
ok()   { echo "PASS $1"; }
bad()  { echo "FAIL $1"; fails=$((fails+1)); }
expect() { [ "$2" = "$3" ] && ok "$1" || bad "$1 (want $3, got $2)"; }
tick() { curl -s -o /dev/null "$W/__scheduled?cron=*+*+*+*+*"; sleep 1; }
set_() { curl -s -o /dev/null -X POST -H 'Content-Type: application/json' -d "$1" "$M/__set"; }
L() { curl -s "$M/__log"; }
ncalls() { L | jq '.calls|length'; }
calls_since() { L | jq -c --argjson n "$1" '[.calls[$n:][]|[.op,(.id//.service)]]'; }

node tests/mock.mjs "$MOCK_PORT" > "$TMP/mock.log" 2>&1 & MOCK_PID=$!
wrangler dev --port "$DEV_PORT" --ip 127.0.0.1 --test-scheduled --persist-to "$TMP/state" \
  --env-file "$TMP/secrets.env" \
  --var "RAILWAY_API:$M/graphql" --var "GITHUB_API_BASE:$M" --var "WORKSPACE_ID:abc-123" \
  --var "COOLDOWN_S:60" --var "WATCH:$WATCH" \
  > "$TMP/dev.log" 2>&1 & DEV_PID=$!
for _ in $(seq 1 240); do curl -s -o /dev/null "$W/" && break; sleep 1; done
curl -s -o /dev/null "$W/" || { echo "wrangler dev did not start"; tail -30 "$TMP/dev.log"; exit 1; }

echo "== everything running"
tick
expect "no Railway actions"                 "$(ncalls)" 0
expect "no alert issue"                     "$(L | jq '.issues|length')" 0
expect "token accepted by Railway"          "$(L | jq '.authFails')" 0
expect "no HTTP surface"                    "$(curl -s -o /dev/null -w '%{http_code}' "$W/status")" 404

echo "== the 2026-10-06 outage: Railway removes every deployment in campaign-hub"
set_ '{"services":{"pg":{"latest":null,"active":[]},"app":{"latest":null,"active":[]},"bk":{"latest":null,"active":[]}}}'
n=$(ncalls); tick
expect "database restored first, alone"     "$(calls_since "$n")" '[["redeploy","pg-old"]]'
expect "restore reuses the built image"     "$(L | jq '.calls[-1].previousImage')" true
expect "one alert issue opened"             "$(L | jq '.issues|length')" 1
expect "issue carries the key line"         "$(L | jq -r '.issues[0].body|split("\n")[0]')" "key: RAILWAY-WATCHDOG"
L | jq -r '.issues[0].body' | grep -q '\*\*Postgres\*\* (campaign-hub / production) was not running' \
  && ok "issue text is plain English" || bad "issue text is plain English"

echo "== database still starting: code services wait"
set_ '{"services":{"pg":{"latest":"DEPLOYING","active":[["pg-new","DEPLOYING"]]}}}'
n=$(ncalls); tick
expect "nothing while the database starts"  "$(calls_since "$n")" '[]'

echo "== database up: code services come back; a lost image falls back to a fresh build"
set_ '{"services":{"pg":{"latest":"SUCCESS","active":[["pg-new","SUCCESS"]]}},"failIds":["bk-old"]}'
n=$(ncalls); tick
expect "app restored past its failed builds, cron falls back" "$(calls_since "$n")" \
  '[["redeploy","app-old"],["redeploy","bk-old"],["deploy","bk"]]'
expect "update posted on the same issue"    "$(L | jq '[.comments[]|select(.issue==1)]|length')" 1

echo "== all running again: issue closes"
set_ '{"services":{"app":{"latest":"SUCCESS","active":[["a2","SUCCESS"]]},"bk":{"latest":"SUCCESS"}}}'
n=$(ncalls); tick
expect "no more actions"                    "$(calls_since "$n")" '[]'
expect "issue closed"                       "$(L | jq -r '.issues[0].state')" closed
L | jq -r '.comments[-1].body' | grep -q '^Everything is running again' && ok "resolved text" || bad "resolved text"
n=$(ncalls); tick
expect "quiet afterwards"                   "$(calls_since "$n")" '[]'
expect "no extra comments"                  "$(L | jq '.comments|length')" 2

echo "== a running service fails its health check 3 times: restart"
set_ '{"health":{"lab":500}}'
n=$(ncalls); tick; tick
expect "no restart on a short blip"         "$(calls_since "$n")" '[]'
expect "a short blip pages nobody"          "$(L | jq '.issues|length')" 1
tick
expect "restarted the running deployment"   "$(calls_since "$n")" '[["restart","lab-live"]]'
expect "new alert issue"                    "$(L | jq '.issues|length')" 2
set_ '{"health":{"lab":200}}'; tick
expect "health back: issue closed"          "$(L | jq -r '.issues[1].state')" closed

echo "== spending cap: never restart, page once with the numbers"
set_ '{"services":{"lab":{"latest":null,"active":[]}},"billing":{"over":true,"usage":123.45,"hard":100}}'
n=$(ncalls); tick; tick
expect "no actions while capped"            "$(calls_since "$n")" '[]'
expect "one cap issue"                      "$(L | jq '.issues|length')" 3
L | jq -r '.issues[2].body' | grep -q 'used \$123.45 of a \$100.00 hard limit' && ok "cap numbers in the alert" || bad "cap numbers in the alert"
echo "waiting 60 s for the lab's restart cooldown..."; sleep 60
set_ '{"billing":{"over":false,"usage":20,"hard":200}}'
n=$(ncalls); tick
expect "cap lifted: brought back"           "$(calls_since "$n")" '[["redeploy","lab-old"]]'

echo "== paused"
wrangler kv key put paused 1 --binding WATCHDOG --local --persist-to "$TMP/state" > /dev/null 2>&1
set_ '{"services":{"pg":{"latest":null,"active":[]}}}'
n=$(ncalls); tick
expect "no actions while paused"            "$(calls_since "$n")" '[]'

echo "== secrets never logged"
grep -q -e fake-railway-token -e fake-github-token "$TMP/dev.log" && bad "a token appeared in the Worker log" || ok "no token in the Worker log"

echo
[ "$fails" -eq 0 ] && echo "ALL PASS" || { echo "$fails FAILED"; tail -40 "$TMP/dev.log"; exit 1; }
