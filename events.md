# events.md — risingtides-campaign-hub repo ledger

Append-only chronological ledger for this repository. Schema per ~/.claude/CLAUDE.md.
_________________________________________________________________________________
time:      [22:05] [07-16-26]
agent:     [claude] [fable 5]
type:      [bug-report]
area:      [infra]

Root-caused and fixed the Internal TikTok silent-zero stats (stale since 06-03): Railway `sleepApplication: true` was stopping the container on idle, killing in-flight scrape threads (job registry is in-memory) AND preventing the 6 AM APScheduler from ever firing — which is likely why SCHEDULER_ENABLED had been turned off as "broken". Fixes: disabled app sleeping on production via Railway GraphQL, set SCHEDULER_ENABLED=true (scheduler confirmed started: campaign_refresh 06:00, internal_scrape 06:02 EST, notion_sync 15m, tides_tracker_pull 30m), triggered a backfill scrape from 2026-06-03 (completed: 2,266 videos, 48/54 accounts, 6 failed handles worth auditing), and shipped PR #205 — GET /api/internal/freshness + an amber staleness banner on the Internal TikTok stats tab so stale data can never again read as zeros. Also earlier today: PR #204 Mission Control embed (Overview button on TidesTrackers → /tracker-overview iframe of risingtides-tracker.com/internal) + Dockerfile ARG fix so VITE_TRACKER_* vars bake into Railway builds.
_________________________________________________________________________________
time:      [22:40] [07-16-26]
agent:     [claude] [fable 5]
type:      [refactor]
area:      [frontend]

Corrected the "booker" misnomer on rt-tracker (PR #206): the leaderboard was always the Notion Poster column, but CAMP-34-era work invented "booker" for it. Per john's taxonomy — CREATORS are external people we book; POSTERS are internal team members who run our pages. UI renamed to "By Poster", canonical /api/internal/posters routes added (old /bookers kept as compat aliases, rows carry both poster and legacy booker keys). Verified live: zero booker strings render on rt-tracker.
_________________________________________________________________________________
time:      [19:50] [07-19-26]
agent:     [claude] [fable 5]
type:      [review]
area:      [backend]

Race audit fixes (PRs #207 #208): (1) useInternalGroupStats queryKey omitted days — the stats period picker on Internal TikTok + group detail silently served the first-fetched window forever; days now in the key. (2) Group create/delete used raw fetch + window.location.reload() — aborted in-flight mutations, swallowed 4xx/5xx; replaced with invalidating react-query mutations with error surfacing. (3) Cross-worker scrape collisions (4 gunicorn processes, per-process guards): merge_internal_cache now multi-row ON CONFLICT DO UPDATE with GREATEST views/likes; membership inserts ON CONFLICT DO NOTHING (both API and notion_sync paths); attribution rows idempotent. (4) /api/internal/results scope column — a small manual scrape can no longer shadow the 06:02 full cron corpus as "latest". (5) Manual scrapes now default to the scheduler's rate-safe 2 workers / 50 videos (TikTok silent-empty-200 protection), payload-overridable. pytest 439 green (1 pre-existing failure). Dead code noted for future cleanup: web_dashboard.py duplicate legacy scrape path.
_________________________________________________________________________________
