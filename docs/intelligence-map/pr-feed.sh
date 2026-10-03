#!/usr/bin/env bash
# Poll GitHub for Campaign Hub PR + review activity, write a flat event feed JSON.
# Background it:  ./pr-feed.sh &
set -e
cd "$(dirname "$0")"
REPO="Risingtides-dev/risingtides-campaign-hub"
OUT="pr-feed.json"
INTERVAL="${PR_FEED_INTERVAL:-45}"

while true; do
  {
    echo '{'
    echo '  "updated": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",'
    echo '  "prs": '
    gh pr list --repo "$REPO" --state all --limit 14 \
      --json number,title,state,headRefName,mergeable,isDraft,reviewDecision,updatedAt \
      2>/dev/null || echo '[]'
    echo '  ,"events": '
    gh api "repos/$REPO/pulls/comments?sort=created&direction=desc&per_page=50" \
      --jq '[.[] | {pr: (.pull_request_url|split("/")|last|tonumber), user: .user.login, path: .path, line: (.line // .original_line), body: (.body|gsub("!\\[.*?\\)";"")|gsub("\\s+";" ")|.[0:260]), at: .created_at}]' \
      2>/dev/null || echo '[]'
    echo '}'
  } > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"
  sleep "$INTERVAL"
done
