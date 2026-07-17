# events.md — risingtides-campaign-hub repo ledger

Append-only chronological ledger for this repository. Schema per ~/.claude/CLAUDE.md.
_________________________________________________________________________________
time:      [22:05] [07-16-26]
agent:     [claude] [fable 5]
type:      [bug-report]
area:      [infra]

Root-caused and fixed the Internal TikTok silent-zero stats (stale since 06-03): Railway `sleepApplication: true` was stopping the container on idle, killing in-flight scrape threads (job registry is in-memory) AND preventing the 6 AM APScheduler from ever firing — which is likely why SCHEDULER_ENABLED had been turned off as "broken". Fixes: disabled app sleeping on production via Railway GraphQL, set SCHEDULER_ENABLED=true (scheduler confirmed started: campaign_refresh 06:00, internal_scrape 06:02 EST, notion_sync 15m, tides_tracker_pull 30m), triggered a backfill scrape from 2026-06-03 (completed: 2,266 videos, 48/54 accounts, 6 failed handles worth auditing), and shipped PR #205 — GET /api/internal/freshness + an amber staleness banner on the Internal TikTok stats tab so stale data can never again read as zeros. Also earlier today: PR #204 Mission Control embed (Overview button on TidesTrackers → /tracker-overview iframe of risingtides-tracker.com/internal) + Dockerfile ARG fix so VITE_TRACKER_* vars bake into Railway builds.
_________________________________________________________________________________
