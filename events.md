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
_________________________________________________________________________________
time:      [13:26] [08-07-26]
agent:     [claude] [fable 5]
worktree:  main
type:      [bug-report]
area:      [backend]

John called out that the campaigns page was still taking ~8s to show data after the morning's fixes — and he was right: the UI fetches /api/campaigns?include_finished=true, the exact path yesterday's pushdown skipped, and I had verified with curl against the default path instead of the page's real request. Root cause of the remaining slowness: the tides_tracker_pull cron only warms ACTIVE campaigns' trackers, so the 285 finished campaigns' cache entries are permanently stale (some 61 days), and every UI load burned the entire 10-tracker cold batch (timeout=5s, ~6.5s wall) re-fetching stats for campaigns whose numbers cannot change — crowding the active trackers out of the batch in the process. Fix shipped in PR #215 (squash ac3e18c): (1) new frozen_slugs param on get_campaign_stats_bulk() — completed campaigns never spend the live-fetch budget and serve from the durable L2 cache or scraper fallback, with shared trackers still fetched for their active campaign; (2) frontend split — CampaignsList now loads useActiveCampaigns (~37 rows) and useFinishedCampaigns (~285 rows) independently, each tab gating only on its own query, split keys sharing the "campaigns" prefix so existing invalidations refetch both. Three new backend tests pin the frozen behaviour (never fetch live / shared tracker exception / cold budget goes to live trackers); 457 passed, same 12 known failures; tsc + vite green. Verified against the deployed app by reconstructing the full browser waterfall (HTML -> entry/queries bundles -> both API calls, three runs): active rows visible in ~0.35-0.6s cold, finished tab filling in ~1.3s behind it, and the deployed queries chunk confirmed to contain the split fetch. Finished path itself dropped 7.0s -> 1.2-2.1s with stats sources showing api_cached/scraper_fallback as designed. Could not click through in Chrome directly — the Claude extension wasn't connected and reconnecting requires a Chrome restart over john's open session — so the waterfall reconstruction stands in for in-browser timing until he loads the page.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [13:47] [08-07-26]
agent:     [claude] [fable 5]
worktree:  main
type:      [bug-report]
area:      [backend]

John reported the page still taking 7.6s after PR #215, and with browser-use newly installed I could finally reproduce it in a real browser instead of curl: 7.0s to visible rows, with the ACTIVE /api/campaigns call itself at 5.7s. Root cause found by probing every active tracker's upstream directly: sombr_june_release's Tides Tracker endpoint returns 200 but takes 7.5s (262KB payload), which exceeds the list endpoint's 5s inline prewarm timeout. A timed-out fetch writes no cache, so every request retried it and burned the full 5s again — the request path could never heal this tracker, only the 30-min cron (15s timeout) could, and each deploy resets the scheduler so the first tick fires 30 min after boot. Today's repeated deploys kept knocking it stale; upstream Vercel latency variance is the long-standing "some days faster than others" symptom. Fix (PR #216, squash 4ce709f): stale-while-revalidate in the bulk prewarm — stale-but-present trackers serve their cached entry immediately and refresh in a daemon thread at the full 15s timeout; only trackers with no cache anywhere may block inline (new trackers, 5s, once); every attempt marks a 120s per-worker cooldown so a dead upstream is probed once per window, not per request; invalidate_cache() clears cooldown marks so manual refresh still goes live. Five new tests pin the contract (stale serves + hands off / missing blocks once at 5s / failure cooldown kills the retry loop / no re-schedule inside cooldown / background path uses 15s and caches); 462 passed, same 12 known failures. Verified IN THE BROWSER this time, three full page loads against prod: rows visible in 0.86s / 1.63s / 1.14s (down from john's measured 7.6s), Finished tab renders its 285 rows in 0.09s from the prefetched background query, API endpoint steady at 0.12-0.38s across 8 consecutive worker hits with zero 5s spikes. Screenshot confirmed the table fully populated with budgets/views/CPM.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [14:06] [08-07-26]
agent:     [claude] [fable 5]
worktree:  main
type:      [bug-report]
area:      [backend]

Three-item batch from john. (1) Booking Efficiency tab was dead with "Unexpected token 'I' ... is not valid JSON": creators with spend but zero tracked views get float('inf') for cost_per_view/cost_per_engagement in booking_efficiency.py, and Python's json writes that as bare Infinity — not valid JSON, so the browser's JSON.parse rejected the whole payload. Fixed in PR #217 (squash 37fc455): new _num() sanitizer at the API boundary turns non-finite floats into null across all efficiency endpoints, frontend types those fields nullable and renders an em dash, plus fixed a latent ZeroDivisionError in the report averages when every creator has inf unit costs. Four regression tests including a strict parse_constant rejector. (2) Same PR adds search + sorting to the TidesTrackers tab: token search over name/campaign/group/cobrand+tracker URLs, click-to-sort headers for Name/Campaign/Group/Created with direction toggle, blanks sinking to the bottom. Browser-verified post-deploy: efficiency page renders (index 57.6, 306 creators), tracker search filters live ("sombr" -> 2 rows), name sort works both directions. 466 passed, same 12 known failures. (3) Investigated the Mission Control "duplicate campaigns": the page is an iframe of the external TidesTracker board (risingtides-tracker.com/internal, repo KINGMAKER-SYSTEMS/tidestracker — checked out locally at ~/dev/tidestracker), and the duplication is real duplicate tracker entries in THAT system, not a rendering bug here: harvested all 202 cards from the live board and found 8 clusters sharing byte-identical stats under different names (Warner CPM Pages / Warner Music Campaign both 164.66m + 3,907 posts; Bebe Rexha - New Religion x3 name variants at 17.48m; Warner Test Pages x3 at 16.65m; Sam Barber Run/Pages, Stella Lefty R2, Dexter 12 Steps pairs), matching our own tracker_campaign_links rows where bebe_rexha_new_religion has 3 trackers and three campaigns have 2. Because the board defaults to Sort: Most views and the biggest clusters are all high-view, the first screens look mostly duplicated even though it's ~18 of 202 cards. Fix belongs in the tidestracker repo (dedupe/merge trackers sharing a Cobrand activation, or board-side collapse) — flagged to john rather than silently crossing repos.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [14:40] [08-07-26]
agent:     [claude] [fable 5]
worktree:  main
type:      [infra]
area:      [infra]

Hosted the Hub at https://campaignhub.risingtidesviral.com per john. Railway custom domain attached to the risingtides-campaign-hub service via CLI (domain id 6b397763), then created the two DNS records in Cloudflare (zone risingtidesviral.com on the Smathdaddy account, driven through the dashboard with browser-use since the wrangler OAuth token lacks DNS write scope): CNAME campaignhub -> 6mqle4gy.up.railway.app set to DNS-only so Railway could validate ownership and issue its own certificate, plus TXT _railway-verify.campaignhub with Railway's verification string. Cert issued ~90s after the records landed; verified in the browser: page serves on the new domain with rows visible in 0.82s. Also set CORS_ORIGINS to the new domain + the railway.app URL (it still pointed at the deleted Vercel deployment), and PR #219 fixes the browser tab title from "frontend" to "Campaign Hub". The old railway.app URL keeps serving, so nothing that references it (webhooks, scripts, bookmarks) breaks. Same session: PR #218 tucked the Internal/Intake/Distribution sidebar sections behind a collapsed "Other" group (auto-expands when the active route lives inside it), browser-verified collapsed by default with all four links present on expand.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [14:43] [08-07-26]
agent:     [claude] [fable 5]
worktree:  main
type:      [feature-request]
area:      [frontend]

Added the RT wave favicon to Campaign Hub per john (PR #220): same rt-logo-icon.svg mark that tidestracker and content-posting-lab use (both carry the identical path data, fill #FAFCFF), recolored to solid black as requested and wired into frontend/index.html in place of the leftover vite.svg. Verified live on campaignhub.risingtidesviral.com — /favicon.svg serves the black-fill SVG and the link tag points at it. Note: a black mark is near-invisible against dark browser tab bars; if it vanishes on john's theme, the gradient variant (rt-logo-primary-gradient.svg) is sitting in tidestracker/public ready to swap in.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [13:48] [08-10-26]
agent:     [claude] [fable 5]
worktree:  main
type:      [analysis]
area:      [backend]

Two-parter from john: the check-off-campaign interaction "takes forever", and assess the move to the rust rebuild. (1) Fixed the toggle in PR #221: the handler awaited the edit API call and then a full refetch of BOTH campaign lists before the checkbox changed (~1-2s+); now it patches the React Query caches optimistically — checkbox flips instantly, the row moves between Active/Finished so tab counts update, server reconciles in the background, API failure rolls back to a snapshot. The edit endpoint itself measured 60ms; it was pure frontend wait. (2) Rust assessment, probed live: the campaign-hub-rust-rewrite Railway project runs a real axum port with the same response shapes — core reads + campaign-edit/creator-add writes implemented, full list 0.5-1.4s vs Python's 2.3-4.2s warm — but it was last deployed 2026-07-07 via CLI with NO GitHub repo linked, the source is not on this Mac and not in either GitHub org (if that laptop is gone the code is gone), its own Postgres is a July 1 snapshot (48 campaigns vs 329), efficiency-leaderboard/internal-freshness are explicit stubs, everything scraper-fed 503s, the notion webhook 503s, and it has surprise Google OAuth + PayPal sandbox scope wired in. Recommended path logged in memory: no big-bang — source into GitHub with CI as a hard precondition, point rust at prod Postgres (reconciling schema drift since July), parity-diff the ~23 read routes, then strangler: rust serves reads and proxies the rest to Flask, writes cut over route-by-route; scrapers/crons/Slack/Notion/Cobrand stay Python indefinitely. Also measured today's remaining Python debt for the honest comparison: post-deploy cold window puts requests at 10-30s for several minutes while each gunicorn worker rebuilds its L1 (measured live after the 13:30 deploy), steady state has crept to ~0.6s active / ~3s finished as data grew to 329 campaigns — both fixable in Python by precomputing aggregates in the L2 cache instead of parsing submission blobs per request.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [01:29] [08-14-26]
agent:     [claude] [fable 5]
worktree:  main
type:      [bug-report]
area:      [backend]

Two greenlit fixes landed and verified. (1) PR #222 implemented the missing db.dialect_insert + _sql_greatest helpers that notion_sync._apply_membership_diff had been calling since RTA-9's race-hardening — every membership insert had raised AttributeError, swallowed per-row as resolve_failed, so internal_creator_group_members sat at 0 rows for months while the cron logged success. Verified live: the first cron tick after deploy (notion_sync_log id 4524, 04:34 UTC) wrote 60 memberships across the cluster groups (internal_page 37, warner_test_ugc 10, warner_ugc 5, mon_rovia 4, ...) and subsequent ticks are 0/0 — idempotent steady state. This also cleared 11 of the 12 long-red tests; only the known TT-label matching failure remains. (2) The same PR added phase timing to get_campaigns, and its first cold window turned theory into data: stats_bulk=3.15s of total=4.18s — every worker's first request per endpoint was deserializing the full submissions blob per tracker just to SUM totals, and those 3-4s requests queued on 4 sync workers into the observed 12-21s walls. PR #223 fixed it: tides_tracker_stats_cache gains agg_views/likes/comments/shares/post_count written by every _cache_set, the list path serves an aggregates-only CampaignStatsResult on L1 miss (no blob parse, same totals), the bulk prewarm's freshness check probes fetched_at from the same cheap row, legacy NULL rows fall back to the blob path, and scripts/migrations/backfill_tides_cache_aggregates.sql (run post-deploy, 252/252 rows) covers finished campaigns' trackers the cron never rewrites. Verified on the fresh container with all L1s cold: active 0.26-0.45s, finished 1.6-1.9s from the very first request, zero slow-phase log lines — the post-deploy cold window that produced 10-30s requests after every deploy since at least 08-07 is gone. Suite: 577 passed, 1 known failure.
_________________________________________________________________________________
