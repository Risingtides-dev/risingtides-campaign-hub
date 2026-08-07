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
_________________________________________________________________________________
time:      [16:56] [07-24-26]
agent:     [pi] [thoth]
worktree:  [main]
type:      [bug report]
area:      [automations]

Root-caused four hourly scraper worker SIGABRTs to curl-cffi 0.14.0 drift against the committed 0.11.4 pin. Hardened the local production rail: typed native subprocess crashes now bypass cache fallback and retries, cancel queued creator work, fail the exact cron run, and propagate a nonzero top-level result. Added an explicit immutable production-runtime provisioner, exact-pin and full-freeze drift gates, Python ABI/platform fingerprinting, production-only venv activation, tracked-launcher checksum enforcement, outer runner locking, and atomic status writes. Downgraded the shared development venv to curl-cffi 0.11.4 for manual safety. Validation before deployment: 39 focused tests green, shell/Python syntax and diff checks green; full suite 453 green with the pre-existing unrelated TT-label matching test still failing.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [17:07] [07-24-26]
agent:     [pi] [thoth]
worktree:  [main]
type:      [workflow]
area:      [testing]

Deployed scraper hardening commit 4e367d8 to origin/main. Provisioned and atomically activated dedicated production runtime fingerprint 157062a67be46a3b with Python 3.14.6, yt-dlp 2026.3.17, and curl-cffi 0.11.4; installed the tracked launcher copy and verified its checksum, exact pins, pip consistency, freeze manifest, Chrome-136 support, and production health probe. Concurrent canaries for the four previously crashing creators all returned 3/3 items with zero new crash reports. Full supervised production run 420 completed cleanly in 487 seconds: 165 creators (160 ok, 5 empty, 0 error), 38/38 campaigns refreshed, 16 new matches, degraded=false, export 187 links, and no additional Python crash reports.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [16:13] [07-31-26]
agent:     [claude] [fable 5]
worktree:  fix/notion-multi-source-api
type:      [bug-report]
area:      [backend]

Root-caused both Notion syncs going dark on 07-28: Notion migrated the workspace databases to multi-source format (each gained an empty "New data source"), and the pinned API version 2022-06-28 gets HTTP 400 on every query of a multi-source database. Master Pages cron failed 286 consecutive runs since 07-28 20:37 UTC (visible in notion_sync_log); the CRM webhook sync swallowed the same 400 silently and has never created a campaign (0 rows with source='notion'). Fix: bumped NOTION_VERSION to 2025-09-03, added resolve_data_source_id() (first-listed source, env-overridable via NOTION_CRM_DATA_SOURCE_ID / NOTION_MASTER_PAGES_DATA_SOURCE_ID, cached per process), pointed both query paths at /data_sources/<id>/query, and made query_new_clients log failures instead of swallowing them. Live smoke: CRM resolves + returns 1 Client entry (sam_barber_run, already exists, will be skipped), Master Pages fetches 61 pages. Tests: 55 affected tests green, full suite 459 passed with only the pre-existing TT-label matching failure. Note: an unknown external process creates Hub campaigns from CRM Lead entries daily (118 since June, source='manual' + notion_page_id, empty CRM fields) — creator not found in any local repo; flagged to john.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [12:59] [08-07-26]
agent:     [claude] [opus 5]
worktree:  perf/campaigns-list-filter-pushdown
type:      [refactor]
area:      [backend]

John asked what we could do to speed up the Railway Postgres instance, since Campaign Hub takes noticeably longer to source information on some days. Profiled the live DB first: it is 68 MB with a 100% buffer cache hit ratio, zero deadlocks, zero temp files, no query running longer than five seconds, and sub-millisecond internal latency — the instance is not the bottleneck and a bigger plan would buy nothing. The real cost is GET /api/campaigns, which measured 3.2–7.1s wall for a 24 KB response while /health answered in 40ms. Cause: get_campaigns() loaded every campaign, then filtered to active ones in Python. Prod has 285 completed vs 37 active campaigns and ~90% of matched_videos hang off the completed ones, so the default page load pulled all 322 campaigns, 3,724 creators and 17,406 matched_videos out of Postgres, built a dict for each, ran calc_budget and a stats resolution per campaign, then discarded ~90% of it. That also explains the table stats: 145k sequential scans on matched_videos having read 1.84 billion tuples, and 3.3M index scans against the fat 15 KB-per-row tides_tracker_stats_cache. Fix: added a `completion` param ("active" | "finished" | None) to db.list_campaigns_with_creators() that filters in the query, threaded it through get_campaigns(), and had the route resolve the active/finished split before fetching instead of after. Because the creators/matched_videos selectinload is driven by the campaign IDs the parent query returns, the child fetches narrow too. Benchmarked against the prod DB: 1386ms -> 127ms, an 11x cut, dropping the loaded set from 322/3724/17406 to 37/513/1701 and the stats loop from 322 campaigns to 37. Existing behavioural contract test (test_active_filter_excludes_completed) still passes unchanged, confirming identical output; added four tests pinning the filter to the query layer so it cannot regress into the caller. Suite: 454 passed, same 12 pre-existing failures as clean main (notion_resolve / services_matching / upsert_dialect_compile, all unrelated). Left the three other get_campaigns() callers — Slack booking intake, inbox fuzzy match, /api/search — on the unfiltered default, since narrowing those changes matching behaviour rather than just performance; flagged to john as a follow-up along with enabling pg_stat_statements for ongoing query visibility.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [13:34] [08-07-26]
agent:     [claude] [opus 5]
worktree:  main
type:      [bug-report]
area:      [backend]

Follow-up to the campaigns-list perf work: john reported it was still slow on startup and suspected the Railway service, since some days are faster than others. It is not Railway. After the query-pushdown fix the endpoint measured strictly bimodal — 0.37s or a flat 5.2s, with nothing in between across a dozen samples. A noisy-neighbour or undersized-container problem produces a smooth spread; a clean two-value split with a suspiciously round upper bound is a timeout being hit or missed. Traced it to the Tides Tracker read cache: TIDES_TRACKER_CACHE_TTL_SECONDS defaults to 300s, but the tides_tracker_pull cron that refills that cache runs every 1800s. The cache was therefore treated as stale for 25 of every 30 minutes, so most requests fell through to a live inline fetch of the Tides Tracker API — up to ten parallel calls at timeout=5, hence the flat 5.2s. The cron's warm_cache write-through (CAMP-74) was working fine; the read path just refused to trust it for 83% of the cycle. Set TIDES_TRACKER_CACHE_TTL_SECONDS=2700 on Railway (above the 30-min refill, with headroom for one missed tick). Endpoint went from 3.2–7.1s before any of today's work to 0.22–0.90s across 22 samples. Verified output is unchanged: 37 active + 285 finished = 322 total, ?active=false returns no active rows, search still matches (7 hits for "sam" once finished campaigns are included). Residual: the four gunicorn workers each hold their own in-process L1 cache, so exactly one request per worker still pays a cold hydrate after each deploy — that is the remaining startup slowness, and the fix would be warming at boot or leaning harder on the shared Postgres L2.

Separately, while explaining the 12 test failures that have been sitting red on main: 11 of them are one live bug, not test rot. notion_sync.py:631 calls _db.dialect_insert(), which does not exist in db.py, so every membership insert raises AttributeError and resolve_memberships() swallows it per-row as "resolve_failed". Confirmed against prod — internal_creator_group_members has 0 rows and every 15-minute cron run logs memberships_added=0. The RTA-9 label/booker grouping feature has been dead in production while reporting success. The 12th failure is the separate known TT-label sound-matching one from 07-31. Flagged to john, not fixed — the fix is implementing dialect_insert as a Postgres/SQLite upsert dispatcher, which is its own change.
_________________________________________________________________________________
