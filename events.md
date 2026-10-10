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
_________________________________________________________________________________
time:      [17:51] [09-29-26]
agent:     [claude]
worktree:  feat/crm-internal-captions
type:      [feature-request]
area:      [backend]

john asked for a caption section in the CRM that populates the sound section and stays synced, so custom text on screen submitted on an intake form goes into the system properly. The CRM already had an empty "Internal Captions" text property that nothing read. The Hub now reads it in the same page read that refreshes Content Niche Targets, stores it verbatim on the campaign (new nullable internal_captions column, added at boot by the existing column reconcile), and keeps it current for active campaigns on the existing 15-minute refresh under the same rule as niches: an unreadable or missing property preserves what is stored, an explicitly empty one clears it, and a value too long to read inline is read whole through Notion's paginated property endpoint or counted as unreadable, never cut short. New endpoint GET /api/campaigns/captions lists active campaigns whose captions have been read, with their sound, for the posting control plane (its half is on ecfromthedc/rotational-posting-agent, branch feat/crm-sound-captions); the campaign list carries no caption text, and campaign detail shows the field. Finished campaigns are left out of the endpoint because the refresh stops following their CRM rows. Both CRM intake forms (Internal New artists fillout, and the public Rising Tides Campaign Onboarding Form) now have an optional long-answer question writing to Internal Captions; Notion's API cannot add form questions, so those were added in the form builder and confirmed by reading the views back. A whole-campaign save sets captions only when it creates the campaign; after that they change only through the CRM refresh, because the scraper and the edit doors save a copy they loaded earlier and an independent review showed that copy putting old captions back over new ones. Verified: 689 passed with the one known TT-label failure, the 25 new and moved tests fail against the old code, and a rehearsal on a throwaway local Postgres showed the new build adding the column to an old schema and the old build still reading and saving afterwards. Found while in the forms, not changed: the public form's required "Project Lead" question writes to the Sentiment property, so clients are shown sentiment tags as the answer to who their contact is.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [23:31] [09-29-26]
agent:     [claude]
worktree:  feat/internal-captions-write
type:      [feature-request]
area:      [backend]

Eric's team asked on rotational-posting-agent#672 for campaign captions to sync both ways, and the one thing missing on the Hub side was a door that saves one campaign's captions. PUT /api/campaign/<slug>/internal-captions takes internal_captions and expected (the value the caller last saw, or null), writes the text to the campaign's CRM page first and stores it here only once the CRM took it, so the CRM stays the source of truth; a stored value that differs from expected answers 409 with the current value, a CRM refusal answers 502 and stores nothing, a campaign without a CRM page is stored here only, and when HUB_WRITE_KEY is set the X-Hub-Write-Key header must match it. Known window: a refresh that read the CRM just before such a write can put the older value back until the next refresh. 696 passed with the one known TT-label failure; seven new tests.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [12:17pm] [10-03-26]
agent:     [codex] [gpt-6]
worktree:  codex/campaign-sound-invariant-20261003
type:      [bug report]
area:      [backend]

Closed the campaign sound URL invariant bypass in legacy POST /api/campaign/<slug>/edit: changing official_sound to an HTTP(S) URL now requires the exact expected_official_sound revision, canonicalizes the URL, rejects canonical duplicates, and takes the same campaign-sound transaction advisory lock before re-reading and saving. Existing numeric/non-URL sound_id edits keep their behavior. Added backend regressions for canonical duplicate/stale revision rejection, sound-ID compatibility, and lock/CAS ordering. Verification: 27 relevant campaign endpoint tests passed; the complete target file has one existing date-fixture failure because its hard-coded 2026-09-30 end date precedes the fixture's 2026-10-03 default start date. PR #228 remains untouched and held; this branch is a separate candidate with no merge or deployment.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [12:20pm] [10-03-26]
agent:     [codex] [gpt-6]
worktree:  codex/campaign-sound-invariant-20261003
type:      [gh actions]
area:      [review]

Published the isolated sound URL invariant repair as Campaign Hub PR #236 from commit 72e7669. The PR is open for review; no merge or deployment performed.
_________________________________________________________________________________
_________________________________________________________________________________
time:      [12:39pm] [10-03-26]
agent:     [codex] [gpt-6]
worktree:  codex/campaign-sound-invariant-20261003
type:      [bug report]
area:      [backend]

Fixed PR #236 review regressions: CampaignHeader now sends the displayed official_sound as expected_official_sound for URL edits, and the API preserves the typed token in the POST body; numeric sound IDs send no revision token. The legacy edit route now returns 409 when save_campaign reports missing_revision, conflict, or duplicate; a deterministic interleaving test proves a competing URL write is preserved and the stale edit is rejected. Backend checks: focused sound regressions 4 passed; full campaign endpoint file 28 passed and the existing hard-coded 2026-09-30 end-date fixture failed against 2026-10-03 default start. Frontend tests were added but not run because node_modules is absent and the host volume is full; no dependency installation or cleanup was attempted. No merge or deployment.
_________________________________________________________________________________

_________________________________________________________________________________
time:      [05:18am] [10-04-26]
agent:     [codex] [gpt-6]
worktree:  codex/repair-campaign-save-conflicts
type:      [bug report]
area:      [backend]

Fixed false-success handling for campaign create, Notion webhook create, and Notion sync when save_campaign reports a duplicate, conflict, or other non-success result. Create/webhook now return 409 for known races and fail closed on unexpected statuses before saving creators; sync skips known conflicts and reports unexpected save failures without marking campaigns created. Added focused outcome regressions. Verification: campaign and webhook backend test files, 66 passed; Python compileall and git diff --check passed. Candidate is based on PR #240 head b1972436813892e2fb47a641d78e4dfc84a93e16; independent review and push pending. Non-ASCII X-Hub-Write-Key TypeError remains a separate P3 finding.
_________________________________________________________________________________

_________________________________________________________________________________
time:      [05:16am] [10-04-26]
agent:     [codex] [gpt-6]
worktree:  codex/campaign240-merge-event-20261004
type:      [gh actions]
area:      [release]

PR #240 fix commit db3601a5e2ba2d37a347b9c0e8e6c5cc9a537e2c passed the hosted backend check and was squash-merged as 878c2f16bb6e7c446a01e1b20d10b8bb152838a4. The merge-commit backend workflow 37191619980 is pending. Production deployment is unverified: the documented Railway hostname returned 404 Application not found and the Railway CLI is unauthenticated. No live write was attempted. The P3 non-ASCII HUB_WRITE_KEY case remains open.
_________________________________________________________________________________

_________________________________________________________________________________
time: [1:00am] [05-10-26]
agent: [codex] [hub_auth_companions]
worktree: [codex/content-lab-hub-auth-20261005] [/private/tmp/hub-flask-lab-auth-20261005]
type: [workflow]
area: [backend]

Prepared the minimal Flask caller companion for Content Lab PR #179: optional server-only CONTENT_LAB_HUB_API_KEY authenticates existing Sound Assignments proxy requests, browser headers cannot supply it, configured-key calls do not follow redirects, and transport errors stay credential-free. Independent source review approved the change; the app-config source audit found no whole-config serialization or logging. All 18 focused checks pass, including real loopback redirect controls; the full existing backend suite on Python 3.10.19 passes 884 with five existing disposable-PostgreSQL skips. The Python 3.11 hosted gate remains required before merge. No credential values, production configuration, database, deployment, or phone state changed; Content Lab still needs actual ingress/configuration/caller evidence.

_________________________________________________________________________________
time: [6:37pm] [10-05-26]
agent: [Codex desktop] [gpt-6]
worktree: [codex/review-campaign-hub-195-event-20261005]
type: [issues]: Risingtides-dev/risingtides-campaign-hub PR #195
area: [review] [backend]

Independent adversarial review of PR #195 at head 44ac724bf87677b8813451133ac3cbe47cba8230 against base 8fcac22a9c3423708279d32479aa1694becca4f2 found the branch diverged from current main 55d193c9f2d74f5da6643901dbe8f98521aca3c4 (3 commits ahead, 118 behind); no hosted checks were reported for this head. Treat its prior review and checks as insufficient for current integration. In the candidate code, generic _sync_columns can recreate missing columns without their original constraints/defaults, swallow DDL failures, and commit repairs column by column while /health still returns 200. Its health URL parser does not fail closed on ambiguous raw @ credentials. Current main has a versioned completion_status repair with an advisory lock, backfill/default restoration and verification, plus readiness failure on repair errors and make_url-based fail-closed URL handling. The PR also adds a duplicate CI workflow weaker than the existing backend-tests.yml permissions, pinned actions, cancellation, timeout and prescribed test scope. Recommendation: do not approve or merge this branch; close it as superseded or rebuild any needed workflow-only change on current main. No database mutation, deployment, or production behavior was exercised.
_________________________________________________________________________________

_________________________________________________________________________________
time: [07:04am] [06-10-26]
agent: [codex desktop]
worktree: [codex/include-root-backend-regressions] [/private/tmp/hub-root-regression-ci-20261006T105235580396Z/repo]
type: [gh actions]: Campaign Hub existing Python CI coverage
area: [testing]: root regressions and backend discovery
entry-id: root-hub-ci-root-regressions-20261006T110434Z
utc: 2026-10-06T11:04:34.403015+00:00

On actual main 782acecbc483ec44fda090653444a333d8bb2f3d, independently audited Eric's PR #195 and found its remaining plain-pytest coverage intent was not fully delivered: the current hosted job collected only tests/backend. Preserve #195 and its branch while carrying that useful intent through the existing hardened workflow.

Changed only .github/workflows/backend-tests.yml's pytest command to python -m pytest and the root AGENTS.md Verification bullet. Existing pyproject.toml discovery includes every backend case plus tests/test_scheduler_scrape_health.py, tests/test_scrape_tasks_dismiss.py, tests/test_scrape_tasks_round_filter.py, tests/test_scraper_runtime_guard.py and tests/test_yt_dlp_runner.py. Least-privilege permissions, pinned actions, persist-credentials:false, timeout, concurrency cancellation, trigger scope and Python 3.11 stay intact. No duplicate workflow, source/test/dependency changes or new service.

Before controls: the five root modules passed 34/34 on unchanged main; original workflow collection907, default collection941, exactly34 added and no missing backend cases. Final private full run passed936, failed0, skipped5 existing disposable-PostgreSQL cases. Python3.10.19 reused existing dependencies satisfying all19 requirements; all114 repository imports came from the private checkout. Credentials and production DB configuration were absent, scheduler disabled; only3 connections to exact test-owned temporary loopback listeners occurred. Initial2 full-run and three2-case failures came from private guard setup (blanket denial/macOS unsupported socket option); their original artifacts remain labeled, no tests were skipped or assertions changed. Corrected guard affected cases passed2/2.

Evidence: /private/tmp/hub-root-regression-ci-20261006T105235580396Z/candidate-corrected-full-python.receipt.json and prefreeze-source-preservation.json. Other322 tracked blobs retain main bytes. Root owns actual canonical append, final source freeze, independent review, exact-head hosted normal941 discovery under3.11 and release. No push, PR closure, merge, deployment, schema mutation, credential grant, paid resource or queue change by this builder. John's holds and peer ownership remain.
_________________________________________________________________________________
_________________________________________________________________________________
time: [7:20am] [06-10-26] EDT
agent: [Codex desktop] [GPT-6] [local scraper GUI boundary builder]
worktree: [codex/secure-local-scraper-gui] /private/tmp/hub-local-scraper-gui-after-ci249-20261006T111904702145Z/repo
type: [issues]: Risingtides-dev/risingtides-campaign-hub local yt-scraper GUI
area: [backend], [testing]
entry-id: hub-local-scraper-gui-loopback-browser-boundary-20261006

Repair the existing local yt-scraper GUI's non-loopback bind and browser-origin exposure on actual current main 92cbd779b90af84cd53a0bb816fc5b92f06e9f53, after the verified CI249 merge. Bind only literal loopback IPs or exact localhost, use the actual bound address/port, validate Host/Origin/Fetch-Site before body reads or dispatch, reject unsupported methods, and remove wildcard CORS. Preserve same-origin GUI and originless local CLI/MCP calls; HTML, Cargo dependencies/lock and scraping behavior are unchanged. Preserve CI249's full Python test discovery and root Verification while appending the locked Cargo suite to the existing workflow. The corrected prefreeze modified-source Cargo execution at 11:01:44.993126-11:01:55.169878 UTC passed 29/29 on the earlier 782acec checkout, including five synthetic loopback HTTP boundary regressions and one strict default-port authority regression. Current GUI/main/Cargo/lock/README bytes match those actual tested inputs; only workflow/root documentation integrated onto the new base, so no new execution is claimed. Diff check and GUI rustfmt pass. Independent corrected source review found no remaining actionable defect; immutable-head review and final own-head hosted verification remain separate gates. No Pi, real scraper, production endpoint, paid call, installation, deployment or public posting is claimed. Receipt: /private/tmp/hub-local-scraper-gui-boundary-20261006T104652666398Z/corrected-full-existing-scraper-suite-result.json.
_________________________________________________________________________________
_________________________________________________________________________________
time: [8:05am] [06-10-26] EDT
agent: [Codex desktop] [GPT-6] [independent review and release owner]
worktree: [codex/bound-pi-chat-subprocess] /private/tmp/hub-pi-cli-pipe-correctness-20261006T115153716630Z/repo
type: [issues]: Risingtides-dev/risingtides-campaign-hub Pi chat subprocess output
area: [backend], [testing], [review]
entry-id: root-hub-pi-output-deadline-20261006

Repair actual main 9fef2bfac68fecb485ffaad30c645aeff3767e45: a valid verbose Pi child falsely timed out at 15.009s; an exited leader with an inherited output pipe returned a reply at 17.201s, beyond its 15s deadline. Reuse existing scraper readers, diagnostic formatter and process-group cleanup. Drain both streams before waiting; include child exit and complete output in one spawn deadline. Apply the shared scraper's 8 MiB stdout/16 KiB stderr limits to Pi, including decoded UTF-8 expansion. Preserve argv/prompt, inherited stdin, production 15-600s clamp, reply/API fields and successful chat behavior. Incomplete or oversized replies leave history unchanged; errors cancel readers and stop the owned Unix process group. Valid stdout survives oversized stderr diagnostics. Windows retains direct-child-only cleanup.

Actual modified-source Cargo suite passed 37/37 with eight new fake-Pi regressions and all 29 inherited tests, zero failures or ignored tests. Independent root tests passed 2/2: continuous output respects its deadline and preserves prior history; nonzero exit stops a helper with closed output pipes and preserves prior history. Root reviewed the actual collector and shared helpers with zero actionable findings. The first missing-import compile failure is retained alongside the corrected success. Root AGENTS and README record the stable contract; the empty child index stays unchanged because ownership remains at root. Main helpers, proxy, origin guards, dependencies, workflow and HTML remain unchanged. Synthetic executable and test-owned loopback HTTP only; no real Pi, scraper, paid request, installation or live adoption. Freeze and exact-head hosted CI remain separate gates.
Evidence: /private/tmp/hub-pi-cli-pipe-correctness-20261006T115153716630Z/root-independent-prefreeze-pi-source-qualified-review.json; /private/tmp/hub-pi-independent-adversarial-review-20261006T120227684190Z/root-adversarial-pi-test-receipt.json; /private/tmp/hub-pi-cli-pipe-correctness-20261006T115153716630Z/corrected-full-modified-pi-scraper-suite-result.json.
_________________________________________________________________________________
_________________________________________________________________________________
time: [8:24am] [06-10-26] EDT
agent: [Codex desktop] [GPT-6] [review and release owner]
worktree: [codex/bound-local-hub-proxy-after-pi] /private/tmp/hub-proxy-after-pi-20261006T121550328604Z/repo
type: [issues]: Risingtides-dev/risingtides-campaign-hub local GUI Hub proxy
area: [backend], [testing], [review]
entry-id: root-hub-proxy-header-body-deadline-20261006

Repair the existing local GUI proxy on actual merged Pi main 9ae2afd6089d3a713b5396a0d23d2a85b103ff2d. Previously, an accepted upstream connection could stall headers/body indefinitely; a failed partial body became fabricated HTTP200 {}. The original behavior failed three meaningful synthetic controls; repaired controls pass. Use the existing ureq 30-second overall connection/response-header/body timeout, including a progressing body; retain the inherited DNS-resolution limitation explicitly. Transport or incomplete-body errors return existing HTTP502 JSON; successful status/body and foreign-origin zero-upstream refusal remain unchanged. No new service, resolver, dependency, UI or remote-access mode.

Actual integrated modified-source Cargo execution12:21:18.320320-12:21:32.209463UTC passed41/41, zero failures/ignored/filtered: all37 mergedPi/existing checks plus four proxy regressions for stalled headers, partial body, trickling body, healthy recovery and status/body passthrough. Focused controls also passed4/4. Independent review rehashed current inputs/logs and qualified zero findings; correcting the owning contract closed the DNS precision finding. Complete Pi imports/collector/history/tests, origin boundary, HTML, main helpers, README, workflow, dependencies and committed-main events prefix remain preserved. Root AGENTS records the proxy contract; existing Verification/README/empty child index remain unchanged because commands, ownership and other promises are unchanged. Test-owned loopback requests only, no realHub/Pi/scrape/paid operation. Exact immutable-head hosted checks and merge remain separate gates; no installation, deployment or live adoption claimed.
Evidence: /private/tmp/hub-proxy-independent-review-20261006T1207Z/independent-current-pi-main-proxy-actual-cargo-evidence-qualification.json; /private/tmp/hub-proxy-after-pi-20261006T121550328604Z/integrated-full-cargo-suite.receipt.json.
_________________________________________________________________________________

_________________________________________________________________________________
time: [09:09am] [06-10-26]
agent: [Codex desktop] [GPT-6] [root]
worktree: [codex/use-shared-song-scrape-command; /private/tmp/hub-song-scrape-command-interop-20261006T125019290282Z/repo]
type: [refactor]: Backend song account scrape command interoperability
area: [backend]: Shared TikTok launcher/environment and private diagnostics
entry_id: hub-song-shared-argv-repair-20261006T1308

Actual current-main492/treec145 internal worker imports the song utility and calls scrape_account_videos. Replaced its duplicate PATH-first/forced-browser command policy with existing build_tiktok_cmd; configured proxy/cookies/UA/interpreter and default-off or exact configured impersonation now reach this existing caller. Retained callable legacy explicit target override, 120-second subprocess timeout, finite three account attempts, native-crash refusal, warning/stdout success, dates/parser/output/CLI semantics. Redact actual --proxy/--cookies values from copied stderr and exceptions before truncation/logging/propagation, including Python-repr escaping; actual command values stay unchanged.
Genuine old-main8-case controls:6 expected failures/2 existing passes. Initial12/949 results belong only to historical8b27 source; independent escaped-argv counterexample exposed a real residual and is preserved. Corrected20774/c911858f source passes original independent fixture unchanged and corrected focused14/14 plus full951 collected/946 passed/5 unchanged disposable-PostgreSQL skips under actual existing Python3.10.19. Zero failures/errors/external network; only test-owned loopback. Independent corrected-source review9259/SHA34cca7c6cb75cd8651c385f1965e0260dce4b798c9ee85bbf36c4ba45c80b136 found zero findings; own-head hosted3.11 and merged-main checks remain later gates.
Evidence: /private/tmp/hub-song-scrape-command-interop-20261006T125019290282Z; corrected full3892/SHAb012ba4f5340c3ef61d1548bd436600ccec62345065b8892f0b7f436b2d2123a; independent same-fixture corrected pass2273/SHAf7631a02f7c53f39bc6423c8712f8a6d61b387219a8d6a0f66eb617ee527a523.
Devlog pass: root AGENTS adds the backend shared-command/redacted-diagnostic contract; existing Python discovery already covers tests/test_yt_dlp_runner.py, so verification and empty child index remain accurate. No dependency/workflow/Rust/GUI/caller changes. No actual scraper, live result, deployment, billing, migration, key/caller cutover or posting authorization implied. Original147 draft/new-shell/history and other explicit holds remain.
_________________________________________________________________________________

_________________________________________________________________________________
time: [01:32pm] [10-06-26]; actual UTC: 2026-10-06T17:32:35.841208+00:00
agent: [Codex desktop] [GPT-6] [root release owner]
worktree: [codex/bound-local-gui-ingress] /private/tmp/hub-gui-http-ingress-repair-20261006T153830024513Z/repo; base e09ea0009ea30c32b2eecad552ffc2d5a85ff205
type: [bug report], [refactor]
area: [backend], [testing], [review]
entry-id: hub-gui-bounded-ingress-repair-20261006-root

Bound the existing local yt-scraper GUI HTTP listener before body/action dispatch. tiny_http dependency reads and rejected-body draining could hold unfinished local requests before application guards or cleanup; the retained original finite helper/dependency counterexample is not a full production-GUI execution. Replace its transport with a scoped Hyper HTTP/1 adapter on the same loopback listener: 16 admitted connections and owned task records, one 30s accept/header/decoded-body deadline, 32MiB decoded cap, 5s response-write deadline, no drain on refused/incomplete ingress. Keep admission through complete synchronous handler/logging; acknowledge synchronous write success/cancellation. Existing Host/Origin/Fetch-Site guards, business handlers, Pi/proxy helpers, payloads, HTML and 41 existing tests preserved. Four pinned direct dependencies; all existing locked package versions retained.
Actual corrected offline Rust1.97 suite 2026-10-06T16:42:02.733017Z–16:42:21.561077Z: 53/53 pass, 0 failed/ignored; receipt3367/SHA6a17ee2b5361357e36254feddf6403e7a0f8347da4cf915597ad4009aaba79e2. Earlier45/7 compatibility failure retained; corrected synchronous response acknowledgment, task-record cap, deadline phase race and handler lease were re-reviewed. Independent bounded cached-rustc real-wire fixture 17:26:51–17:26:52Z: 4/4 pass, 0 failures; exact-cap fixed/chunked Expect100, foreign/null/duplicate Origin/cross-site refusals without body/Continue, stalled response completion/recovery and shutdown cancellation. Receipt6999/SHA6c161b0e714fc5e7f5c0ad2a73c06e2610e64c91ed838e7fac8349b9bbc81131. Independent current-source review reports zero remaining findings. Old full-GUI before-control was prepared only, never compiled or executed.
Devlog pass: current e09e root AGENTS local GUI contract and Cargo verification updated; empty child index unchanged, all unrelated owning contracts preserved. Canonical primary dirty checkout/index/foreign events and existing lock retained; this same own entry joins complete private base events before final head freeze. Root exclusively owns frozen branch through publication/review/checks/merge; no documentation-only head advances. Own-head hosted backend/Python/Rust checks and final immutable review remain required. Standalone GUI packaging is documented local Cargo build/run; installed runtime owner/restart unverified, no production GUI, Pi, scrape, credentials, watchdog enablement, migrations or posting actions executed. Draft255 watchdog and other explicit holds remain independent.
_________________________________________________________________________________

_________________________________________________________________________________
time: [3:10pm] [10-07-26] EDT; actual UTC: 2026-10-07T19:10:22Z
agent: [Codex desktop] [GPT-6] [root release owner]
worktree: [codex/local-agent-dispatch-outcome] /Users/risingtidesdev/worktrees/hub-local-agent-dispatch on macmini-ip
type: [bug report]: local scraper dispatch false success and ambiguous response
area: [backend], [testing], [review]
entry-id: hub-local-agent-outcome-20261007-root

The Hub previously treated every HTTP 200 from the local scraper as a successful launch, even when the node returned ok:false after a launchctl failure. The isolated candidate validates the node's action, started flag and exact already-running signal; explicit refusal is failure, malformed/transport outcomes are unknown and instruct reconciliation before retry. It returns normalized successful fields and fixed errors without token-bearing transport diagnostics. No live scrape, POST, publication, or credential change was used for proof.

On code head 37cafedda326976eded1af7f96ba353dfca244e0, focused and adjacent checks passed 31/31; a separate isolated Python 3.13 environment with requirements.txt and requirements-dev.txt passed the full repository pytest suite 952/952 with five PostgreSQL DDL tests skipped because no disposable PostgreSQL fixture was provided. Exact final-head review and hosted checks remain required after this ledger and contract commit. The Hub caller routes still return HTTP 502 for unknown outcomes and the local node has no durable receipt/idempotency key, so ambiguous original attempts must not be retried automatically. Rollback is a revert of the candidate code after checking original local-run status. No push, merge, deployment or live outcome is claimed here.
_________________________________________________________________________________
_________________________________________________________________________________
time: [3:18pm] [10-07-26] EDT; actual UTC: 2026-10-07T19:18:55Z
agent: [Codex desktop delegating to AC Mac mini] [GPT-6] [builder]
worktree: [codex/issue-124-scheduler-lease] /Users/risingtidesdev/hub-issue-124-scheduler on macmini-ip; base 5874b62102d275761ec1b064691862f0665cb67d
type: [issues]: Risingtides-dev/risingtides-campaign-hub #124 concurrent cron scrapes
area: [backend], [frontend], [testing]
entry-id: hub-cron-cross-worker-lease-20261007

The observed manual campaign refresh and APScheduler campaign refresh could overlap because only the manual trigger checked an in-process set. The candidate moves a nonblocking same-type gate into the campaign_refresh and internal_scrape job bodies, shared by Hub scheduler, manual and on-demand entrypoints. PostgreSQL uses a dedicated session advisory lock per job type; before persisted scrape results the worker checks that its backend session still owns the lock. Local SQLite/file-mode uses a same-host OS file lock. A duplicate skips before creating a run log. Manual /api/cron/trigger now records a durable queued cron_log receipt and returns accepted plus log_id; the worker CAS-transitions it to running or records skipped/failed, and the janitor fails orphaned queued requests without replaying them. The on-demand UI distinguishes a skipped duplicate from a completed scrape.

On rebased code head c120100c2fc41aabe7578ac53b416c8dcfbf60a4, the full Python suite passed 966 with 5 existing disposable-PostgreSQL DDL tests skipped; frontend TypeScript/Vite build and changed-file ESLint passed. Separate local PostgreSQL checks used only a test-owned connection in the postgres database: another connection could not claim the same job key, the distinct job key stayed runnable, release cleared the lock, and terminating the test-owned backend made the lease fail closed. No scrape, local-node POST, paid request or publication was triggered for verification.

This is a held candidate, not a delivered fix. The Mac local-agent /api/run-now path and its launchd runner do not share the Hub database lock; the runner has its own host-local guard and currently uses --no-proxy. Campaign and internal jobs still have distinct locks, so their 06:00/06:02 overlap and possible shared-capacity contention remain. Exact-head independent review, hosted checks, merge, intended deployment and live outcome proof remain open. Rollback is a revert of the Hub candidate; reconcile any accepted queued/running receipts before repeating work. Root AGENTS records the current lock and receipt contract; child index remains empty because ownership stays at root.
_________________________________________________________________________________


_________________________________________________________________________________
time: [3:30pm] [10-07-26] EDT; actual UTC: 2026-10-07T19:30:31Z
agent: [Codex desktop delegating to AC Mac mini] [GPT-6] [builder]
worktree: [codex/issue-124-scheduler-lease] /Users/risingtidesdev/hub-issue-124-scheduler on macmini-ip; base 5874b62102d275761ec1b064691862f0665cb67d
type: [issues]: Risingtides-dev/risingtides-campaign-hub #124 follow-up
area: [backend], [frontend], [testing], [review]
entry-id: hub-cron-shared-capacity-delegated-receipt-20261007

Independent review found that the first candidate allowed distinct 06:00 campaign and 06:02 internal Hub jobs to compete for shared scraper capacity, configured manual local delegation lacked a durable receipt, and the Mac node ignored requested slugs. This follow-up gives distinct Hub job types one shared advisory capacity lease with a queued receipt, bounded wait/backoff and explicit timeout failure; same-type duplicates still skip. The janitor preserves active queued waiters. Configured manual local dispatch now writes a receipt before the node POST and records delegated/skipped/failed/unknown dispatch outcomes. Scoped local requests are refused before POST, and the UI distinguishes node acknowledgment from scrape completion.

Focused Python checks passed 73/73; full repository Python suite passed 975/975 with 6 opt-in PostgreSQL tests skipped; separate disposable PostgreSQL targeted checks passed 26/26, and frontend TypeScript/Vite build plus changed-file ESLint passed. A test-owned local PostgreSQL connection confirmed that distinct job types can hold their own keys while the shared capacity key admits one backend, rejects another, and releases afterward. No live scrape, node POST, paid request, publication, push, merge or deployment was used. Exact-head independent review and hosted checks remain required. The Mac runner has a separate host-local guard rather than the Hub DB lease; cross-host exclusion and node outcome parity remain explicit holds. Rollback is a revert of this Hub branch after reconciling queued/delegated/unknown receipts.
_________________________________________________________________________________


_________________________________________________________________________________
time: [3:35pm] [10-07-26] EDT; actual UTC: 2026-10-07T19:35:25Z
agent: [Codex desktop delegating to AC Mac mini] [GPT-6] [builder]
worktree: [codex/issue-124-scheduler-lease] /Users/risingtidesdev/hub-issue-124-scheduler on macmini-ip
type: [issues]: Risingtides-dev/risingtides-campaign-hub #124 crash window repair
area: [backend], [testing], [review]
entry-id: hub-local-dispatch-crash-receipt-20261007

Independent exact-head review identified a crash window after the local-node POST: a merely queued receipt could be reaped as never started even though the irreversible dispatch may have reached the node. The revised caller atomically commits dispatching before sending; if reservation fails it refuses to POST. The janitor closes stale dispatching receipts as unknown with explicit original-attempt reconciliation rather than failed-never-started. Synthetic crash-after-POST and reservation-failure tests exercise both boundaries without a live node POST. Focused checks passed 28/28 with disposable local PostgreSQL; full repository Python suite passed 979/979 with six opt-in PostgreSQL tests skipped, and the earlier frontend build/changed-file ESLint remained clean. Fresh independent exact-head rereview remains required. No push, merge, deployment or live scrape is claimed.
_________________________________________________________________________________


_________________________________________________________________________________
time: [3:37pm] [10-07-26] EDT; actual UTC: 2026-10-07T19:37:11Z
agent: [Codex desktop delegating to AC Mac mini] [GPT-6] [builder]
worktree: [codex/issue-124-scheduler-lease] /Users/risingtidesdev/hub-issue-124-scheduler on macmini-ip
type: [issues]: Risingtides-dev/risingtides-campaign-hub #124 local runner status alignment
area: [backend], [testing], [review]
entry-id: hub-local-runner-skip-20261007

Exact-head review found that the Mac active-campaign runner treated a Hub same-type duplicate skip as a failed scrape process. The runner now records skipped and the explicit scrape outcome, exits successfully for the exact already-running no-op, and does not run the queue export that belongs to a completed scrape. An isolated fake-DB/fake-scheduler test confirms no scrape or export is invoked, report and exit semantics are accurate, and the local lock is released. No live scrape or local runner replacement was used. The production Mac service is still on its existing installed checkout; this candidate does not claim rollout parity.
_________________________________________________________________________________


_________________________________________________________________________________
time: [3:40pm] [10-07-26] EDT; actual UTC: 2026-10-07T19:40:51Z
agent: [Codex desktop delegating to AC Mac mini] [GPT-6] [builder]
worktree: [codex/issue-124-scheduler-lease] /Users/risingtidesdev/hub-issue-124-scheduler on macmini-ip
type: [issues]: Risingtides-dev/risingtides-campaign-hub #124 wrapper status correction
area: [backend], [testing], [review]
entry-id: hub-hourly-wrapper-skip-status-20261007

Independent review found the local child could exit zero on a duplicate skip while the installed hourly wrapper wrote SCRAPER_STATUS stage completed, misrepresenting a no-op as a scrape. The child now uses reserved exit 76 only for the exact already-running skip; the wrapper maps that code to a neutral skipped stage and exits zero, while other nonzero results remain failures. The child's report still records skipped and omits export. The janitor now marks a stale local dispatching receipt unknown even if an unrelated same-type Hub job holds its database lock. Focused synthetic child and actual-wrapper-footer checks covered no-op, failure and completion exit paths; zsh syntax passed. Full repository Python suite passed 981/981 with six opt-in PostgreSQL tests skipped; disposable PostgreSQL focused checks passed 31/31. Independent exact-head rereview remains required. No live scraper, launchd restart, node POST, push, merge or deployment occurred.
_________________________________________________________________________________


_________________________________________________________________________________
time: [3:44pm] [10-07-26] EDT; actual UTC: 2026-10-07T19:44:28Z
agent: [Codex desktop delegating to AC Mac mini] [GPT-6] [builder]
worktree: [codex/issue-124-scheduler-lease] /Users/risingtidesdev/hub-issue-124-scheduler on macmini-ip
type: [bug report]: Risingtides-dev/risingtides-campaign-hub local export failure classification
area: [backend], [testing], [review]
entry-id: hub-hourly-export-failure-stage-20261007

Read-only production evidence showed the 19:00 Mac child completed Hub cron_log 982 but its later queue export failed; the hourly wrapper wrote scrape-exit, obscuring the successful core scrape. This candidate preserves the child's completed scrape outcome, records failure_stage export and reserves exit 77 only when the core scrape was healthy; a degraded core scrape remains a scrape failure even when export also fails. The wrapper maps only code 77 to export-exit; no original scrape is retried. Isolated child-report and actual wrapper-footer tests cover core success with export failure, non-benign request_expired remains a failure, and the 0/1/76/77 mappings. The export script itself is owned by a separate worker and remains untouched here. No live run, installed-script replacement, push, merge or deployment occurred. Full exact-head checks and independent review remain required.

_________________________________________________________________________________
time: [4:15pm] [10-07-26] EDT; actual UTC: 2026-10-07T20:15:49.582725+00:00
agent: [Codex desktop] [GPT-6] [root release owner]
worktree: [codex/hub-queue-export-url] /Users/risingtidesdev/worktrees/hub-queue-export-url on macmini-ip
type: [bug report]: completed Mac scrape followed by failed Hub queue export
area: [backend], [testing], [review]
entry-id: hub-queue-export-origin-20261007-root

The original 2026-10-07 19:00 UTC Mac run completed Hub cron_log 982 (37 campaigns refreshed, 35 new matches) but queue export failed HTTP 404 against the obsolete Railway fallback URL. The isolated code candidate changes exporter, Pi ops helper and internal-groups CLI defaults to the verified canonical Hub origin. The exporter validates configured origin and limit and reports bounded HTTP/transport/JSON errors before output creation; it never retries the completed scrape. Read-only GET to the canonical queue endpoint returned HTTP 200. Code head 648fec10259d83cd925c98c704d55457c4d2e0eb passed 962 Python tests with five optional PostgreSQL DDL skips; ten focused origin/failure tests passed. Independent exact-code-head review found no blocker for the URL correction and noted the pre-existing unbounded response read as a follow-up. This entry and owning contract precede final-head review/checks. No live export, scrape, post, push, merge or deployment is claimed here. Rollback requires reconciling original export and setting CAMPAIGN_HUB_API_URL to a verified origin rather than restoring the dead default.
_________________________________________________________________________________

_________________________________________________________________________________
time: [04:19pm] [07-10-26] EDT UTC-04:00
agent: [Codex] [GPT-6] [root release owner]
worktree: [codex/hub258-crm-repair -> PR258] [/private/tmp/hub258-crm-repair-20261007/repo]
type: [bug report]
area: [backend] [testing] [review]

Repair draft258 minuteCRMdiscovery so Clients after the first50 are reached through one bounded query page per tick and cursor wrap/retry. Reuse current property parser to distinguish unknown from explicit empty categories; discovery creates new campaigns only and skips every existing slug, preserving stored exact-page identity/categories/captions rather than transferring same-title CRM ownership. Remove minuteall-linked refresh duplication; existing active exact-page15minute refresh owns updates. Integrated actual GitHubmain5874b621 preserving native local-agent acknowledgment contract; scheduler bytes remain identical originalPR e1b94c and db/models/localagent match currentmain. Full existing Python3.10 backend968passed,5existing disposablePostgreSQLDDLskips; meaningful16CRMcases and4RPAconsumercases verified in preparation. Private integrationc401a384/tree791f69f6 precedes this finalledger/freeze; independent final-head review and fresh requiredhostedchecks remain necessary after expected-originalhead lease push. Keep258draft; no deployment/jobenable/campaigncreate/Notionwrite or productionoutcome claim. Existing manualwebhook behavior outside scope is not claimed repaired. Devlog pass adds concise root discovery/refreshownership contract and preserves all unrelated contracts; emptychildindex unchanged. Canonicalledgerappend respects existing lockfile/inode and preserves primarydirtycheckout/head/index.

_________________________________________________________________________________
time: [4:32pm] [10-07-26] EDT; actual UTC: 2026-10-07T20:32:00Z
agent: [Codex desktop] [GPT-6] [root release owner]
worktree: [codex/issue-124-scheduler-lease] /Users/risingtidesdev/hub-issue-124-scheduler on macmini-ip
type: [gh actions]: Risingtides-dev/risingtides-campaign-hub PR #261 hosted test parity
area: [testing], [review]
entry-id: hub-issue124-hosted-test-portability-20261007

The first exact-head hosted backend run failed in test fixtures: five janitor tests constructed stale timestamps using the runner local timezone while the production ledger uses America/New_York naive values, and the Mac zsh wrapper test invoked /bin/zsh on Linux. The fixtures now construct stale timestamps in the ledger timezone. The wrapper executes on the Mac release host; environments without zsh explicitly skip that platform-specific subprocess check. Under TZ=UTC, 13 focused local tests passed. The owning AGENTS.md contract is unchanged because production behavior did not change. The prior code head passed 994 Python tests, 28 tests against a disposable PostgreSQL 16 cluster, and the frontend build. This test-fix head requires independent review and new exact-head hosted verification. No live scrape, node POST or posting was triggered.
_________________________________________________________________________________

_________________________________________________________________________________
time: [04:40pm] [07-10-26] EDT; actual UTC: 2026-10-07T20:40:01.220018+00:00
agent: [Codex] [GPT-6] [delegated Hub258 release owner]
worktree: [codex/hub258-crm-repair -> PR258] /private/tmp/hub258-crm-repair-20261007/repo
type: [bug report]
area: [backend] [testing] [review]
entry-id: hub258-atomic-creation-race-correction-20261007

Correct the earlier draft258 preparation claim: skipping existing slugs before persistence did not prevent a manual creation between discovery's precheck and save. Independent actual SQLite reproduction overwrote the new campaign's identity, categories and stats, then cleared its creators. save_campaign now offers an optional create-only insert using existing unique constraints; discovery uses it and treats known unique races as conflict, while unrelated integrity failures still raise and ordinary manual upserts remain unchanged. Remove the unnecessary empty creator replacement so attachment immediately after creation survives. Both new race controls fail on original29ea9 source; repaired focused19/19 and full971/971 Python3.10 checks passed with five existing optional PostgreSQL fixture skips. Independent creation-race review passed actual SQLite and synthetic PostgreSQL23505 handling; integrated current-main reviewer passed89 CRM/DB/webhook checks.

Integrated actual GitHub main fad83b11696862dad9041637139a70c0ffa8cfbf, preserving native job/capacity leases, dispatch receipts, export contract and append-only history. Source changes remain limited to CRM discovery, the existing save_campaign function, regression tests and root discovery contract; no lease/model/local-agent edits. Existing scheduler registration from the original draft is retained, not enabled or deployed. This corrective canonical and versioned ledger entry precedes final freeze, independent exact-head review and full backend verification. Push requires the unchanged original draft head e1b94c425507712a6f8ba7654317ddb25360b329 with an explicit lease. Keep draft; no merge, deployment, production CRM request, campaign creation, scraper launch or publication claim. Root contract and empty child index were checked; only the concise discovery contract changed.
_________________________________________________________________________________
_________________________________________________________________________________
time: [4:43pm] [10-07-26] EDT; actual UTC: 2026-10-07T20:43:00Z
agent: [Codex desktop delegating to AC Mac mini] [GPT-6] [root release owner]
worktree: [codex/hub-export-bounded] /Users/risingtidesdev/worktrees/hub-export-bounded on macmini-ip
type: [bug report]: bounded Hub queue export response and deadline
area: [backend], [testing], [review]
entry-id: hub-export-bounded-response-20261007

The production queue export previously read the whole HTTP response without a byte cap. In an isolated follow-up to PR #260, code head 95e4a228014c18bdae359c8542d63d273c8179b3 caps the response at 32 MiB, applies a 45-second whole-exchange POSIX main-thread deadline, and rejects an incomplete declared body before writing an output directory or completed SQLite receipt. Synthetic oversize, incomplete and stalled responses plus a loopback HTTP success/receipt test passed; 14 focused tests and 998 repository Python tests passed, with six optional PostgreSQL cases skipped. Independent code-head review found no blocker for the standalone Mac CLI, but noted that a pre-existing ITIMER_REAL alarm can be delayed and other-thread/non-POSIX callers have no strict whole-exchange deadline. The root AGENTS.md records those scope limits; no child AGENTS exists. No live export, scrape, paid request, post, push, merge or deployment was triggered. Rollback is a revert of this one focused change after checking export receipts; final-head review and hosted checks remain required.
_________________________________________________________________________________
_________________________________________________________________________________
time: [04:58pm] [10-07-26]
agent: [codex] [gpt-6.1-sol]
worktree: [codex/hub-janitor-receipt-owner-20261007] /tmp/hub-janitor-receipt-owner
type: [bug report]: Hub cron receipt janitor ownership
area: [backend]: PostgreSQL scrape lease reconciliation

A stale queued/running receipt could remain open indefinitely when a newer same-type run held the advisory lock, because the janitor knew only the job type. This candidate binds PostgreSQL receipts to the exact lease backend PID and start time before the shared-capacity wait. The janitor preserves the matching receipt, reaps stale mismatches, and conservatively handles pre-deployment unbound receipts. The final full Python suite passed 1002 tests with seven optional PostgreSQL skips. A disposable real PostgreSQL 16 cluster passed two advisory-lock integration tests, including reuse of a backend PID with a different start time; the cluster was stopped and removed. The pre-deployment fallback is capped at 24 hours; internal lease identity is excluded from public cron log reads. No scrape, publication, PR, deployment, or live outcome is claimed. Rollback is a revert after reconciling any open cron receipts; no schema migration is involved.
_________________________________________________________________________________
_________________________________________________________________________________
time: [05:05pm] [10-07-26]
agent: [codex] [gpt-6.1-sol]
worktree: [codex/hub-janitor-receipt-owner-20261007] /Users/risingtidesdev/worktrees/hub-janitor-receipt-owner
type: [bug report]: janitor binding race found in independent review
area: [backend], [testing], [review]

Independent review of be6f319 found that the janitor could cache a stale unbound ORM row while another session bound it, then fail the now-live receipt. The revision locks stale rows during janitor reconciliation, serializing with the binding write, and adds a disposable PostgreSQL interleaving regression. The new regression failed against the prior unlocked janitor and passed with the fix; three disposable PostgreSQL 16 lock tests passed. The final full Python suite passed 1002 tests with eight optional PostgreSQL skips; the disposable cluster was stopped and removed. The 24-hour compatibility cap can mark a pre-deployment receipt failed while its original worker remains active; that receipt is not evidence the worker stopped and its effects require reconciliation before retry. An active-owner lookup currently reads all open rows of affected job types; indexing or a targeted lookup is a later performance follow-up. No scrape, publication, push, PR, deployment or live outcome is claimed.
_________________________________________________________________________________
_________________________________________________________________________________
time: [05:16pm] [10-07-26] EDT; actual UTC: 2026-10-07T21:16:00Z
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/hub-issue46-round-isolation] /Users/smathdaddy-macbook/hub-issue46-round-isolation
type: [bug report]: cross-round same-sound post attribution and report totals
area: [backend], [testing]

Same-sound internal posts previously auto-attached to the latest active campaign regardless of post date, and the client report summed raw historical matched rows. This candidate selects only rounds eligible on the post date and scopes campaign-level stats plus report headline, top-post, creator, and Cobrand outcome totals to eligible stored matches. Historical rows are preserved; missing or malformed post dates do not auto-attach or count in a dated report. A campaign without a start date keeps its legacy report behavior. Focused scheduler/report/stat tests passed 55/55. The full Python suite passed 1004 tests, with eight optional PostgreSQL cases skipped. No scrape, post, PR, merge or deployment occurred. Rollback is a code revert; existing stored rows require no migration.
_________________________________________________________________________________
_________________________________________________________________________________
time: [05:23pm] [10-07-26] EDT; actual UTC: 2026-10-07T21:23:40Z
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/hub-issue46-round-isolation] /Users/smathdaddy-macbook/hub-issue46-round-isolation
type: [bug report]: issue #46 independent-review follow-up
area: [backend], [testing], [review]

Independent review found two further round-integrity leaks: a URL-less eligible matched row could join an unrelated URL-less Cobrand outcome, and a dated round with no newly attached URLs could retain contaminated campaign totals. The candidate now requires nonempty normalized URLs for Cobrand outcome joins and reconciles every touched dated round. The same date-eligibility helper scopes scheduled and manual scrape candidates, campaign totals, creator counts, scrape-log counts, response counts, and the scheduled snapshot call arguments. Historical stored rows remain untouched, and no-start legacy behavior remains. Five focused regressions passed; the full Python suite passed 1007 tests with eight optional PostgreSQL tests skipped. The scheduled snapshot call remains best-effort and currently invokes an unimplemented db.save_stats_snapshot method; its side effect is not verified. No live scrape, post, PR, merge or deployment occurred. Rollback is a code revert; no migration is involved.
_________________________________________________________________________________
_________________________________________________________________________________
time: [05:33pm] [10-07-26] EDT; actual UTC: 2026-10-07T21:33:15Z
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/hub-issue46-round-isolation] /Users/smathdaddy-macbook/hub-issue46-round-isolation
type: [bug report]: issue #46 exclusive same-sound round windows
area: [backend], [testing], [review]

Independent review found that a lower-bound-only round filter let later-round posts remain visible and uploadable in the earlier round. This revision derives an exclusive end boundary from the next campaign sharing an exact primary or additional sound, including completed rounds; same-day ties use creation time then slug. DB-backed scheduled/manual scrapes, internal attachment, stored aggregates, campaign detail/list/links/creator views, client report, Cobrand untracked queue/bulk tracking, Cobrand sideload upload batch, and Chartmetric post events now use the bounded window. Historical rows remain stored. Invalid or undated posts cannot prove dated-round membership; campaigns without a start date retain legacy behavior. File-mode cross-worker upper boundaries remain unverified because there is no authoritative all-campaign roster. Focused tests passed 108/108; the full Python suite passed 1013 with eight optional PostgreSQL cases skipped. The scheduled snapshot call remains a best-effort call to an unimplemented db.save_stats_snapshot method and is not durable proof. No live scrape, external upload, post, PR, merge or deployment occurred. Rollback is a code revert; no migration is involved.
_________________________________________________________________________________
_________________________________________________________________________________
time: [05:37pm] [10-07-26] EDT; actual UTC: 2026-10-07T21:37:23Z
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/hub-issue46-round-isolation] /Users/smathdaddy-macbook/hub-issue46-round-isolation
type: [bug report]: issue #46 partial sound-overlap review repair
area: [backend], [testing], [review]

Independent review found that a campaign-wide upper boundary discarded valid later posts on an unaffected secondary sound when only the primary sound moved to a new round. The boundary is now resolved by each video's exact campaign-owned sound ID. A missing or foreign sound ID after a partial-overlap boundary uses the earliest successor cutoff and logs its URL for reconciliation, avoiding an uncertain duplicate Cobrand upload; the stored row is retained. Scheduled and manual matching, report aggregates, Cobrand queue and sideload upload, and Chartmetric post events have partial-overlap regressions. Focused tests passed 110/110; the full Python suite passed 1015 with eight optional PostgreSQL cases skipped. No live scrape, Cobrand upload, publication, PR, merge or deployment occurred. Rollback remains a code revert with no migration.
_________________________________________________________________________________
_________________________________________________________________________________
time: [05:40pm] [10-07-26] EDT; actual UTC: 2026-10-07T21:40:32Z
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/hub-issue46-round-isolation] /Users/smathdaddy-macbook/hub-issue46-round-isolation
type: [bug report]: safe ambiguous-post reconciliation reference
area: [backend], [testing], [review]

Independent review found that ambiguity warnings logged raw matched URLs, which may contain query tokens, and that ORM queue, bulk, sideload, and Chartmetric filters omitted URL identity entirely from their eligibility dictionaries. Those call sites now carry URL and row ID to the shared filter. The warning emits only a stable SHA-256 prefix of the query/fragment-stripped URL, or a row ID when URL is absent, so the excluded row can be reconciled without exposing the token. Focused token-redaction and Cobrand queue identity regressions passed with 110 focused tests; the full Python suite passed 1015 with eight optional PostgreSQL tests skipped. No external upload, scrape, publication, PR, merge or deployment occurred. Rollback is a code revert; no migration is involved.
_________________________________________________________________________________

_________________________________________________________________________________
time: [05:52pm] [07-10-26] EDT UTC-04:00
agent: [Codex] [GPT-6] [hub258_finish]
worktree: [codex/hub-no-start-attachment-20261007] [/private/tmp/hub-no-start-repair-20261007/repo]
type: [bug report]
area: [backend]: Restore internal attachment for campaigns without a start date

On authoritative GitHub main 4daca326, six regressions reproduced skipped exact-sound internal posts with absent/malformed dates for sole or mixed no-start campaigns. Reused existing video_in_round membership in _attach_internal_to_campaigns, restoring the current legacy no-start contract while retaining dated/invalid-start exclusions, completed filtering, sound boundaries, creation/slug ties and historical rows. Added six original-failing/new-passing cases and three dated exclusion cases; focused round/report/scrape/Cobrand/Chartmetric/stats checks passed 163, full Python3.10.19 suite passed 1024 with eight existing disposable-PostgreSQL skips. Independent source review found no issue; AGENTS.md unchanged because this restores its existing contract. No real scrape, upload, publication or deployment occurred in this repair.

Root observed predecessor PR264 head a425205e hosted Backend run37691175906/job113031441150 success and merge4daca326 at21:43:42UTC, Railway deployment6921624606 success, and both canonical sombr report routes HTTP200 around21:46UTC with18 headline posts and ten dated top-post URLs each in their respective rounds; this proves those report outputs only, not all stored dates or attachment/scrape/Cobrand execution or publication.
_________________________________________________________________________________
time: [05:58pm] [10-07-26] EDT; actual UTC: 2026-10-07T21:58:12Z
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/hub-stats-snapshot-persistence] /Users/smathdaddy-macbook/hub-stats-snapshot-persistence
base: [origin/main] 4daca3262b78b9696e90c21c7d265426884c039b
type: [bug report]: dead scheduled stats-snapshot call
area: [backend], [testing], [review]

The scheduler called db.save_stats_snapshot after each campaign refresh, but no such DB function, model, table, API reader, or active frontend consumer exists; every call produced a swallowed warning and stored no history. The call entered with an April matching change without a schema. The closed September attribution report says Chartmetric supplies history without local daily snapshots, and separate creator-history work leaves capture as an explicit design decision. Removed the dead best-effort call and its misleading monkeypatched test assertion. Scheduled round-scoped campaign/creator/scrape-log aggregates remain verified, and the test checks no snapshot-failure warning is emitted. A new durable time-series feature needs an explicit writer, reader, migration, timezone, and retention contract; no historical snapshot data can be backfilled from this removed call. Focused tests passed 53/53; the full Python suite passed 1015 with eight optional PostgreSQL cases skipped. After PR #265 merged, the prepared source change was rebased onto its current main with both chronological ledger entries preserved. No scrape, publication, PR, merge or deployment occurred for this cleanup. Rollback is a revert of this deletion; no schema changes.
_________________________________________________________________________________
_________________________________________________________________________________
time: [06:12pm] [10-07-26] EDT
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/instagram-total-failure-degraded] /Users/smathdaddy-macbook/campaign-hub-instagram-degraded
base: [origin/main] 1f1654e82b89f1c59898b9790bd04335edcc83b7
type: [bug report]: classify complete Instagram scrape failure in campaign refresh
area: [backend], [testing], [review]

Natural cron log id 982 showed 18 Instagram creator errors from missing APIFY_API_TOKEN while the run recorded degraded=false and Slack said complete. Campaign refresh now marks an all-error or missing-outcome Instagram batch degraded independently of TikTok anomaly thresholds, retains completed as execution status, and persists Instagram total/failure/counts in the summary. Slack reports Instagram counts and an Instagram-specific degraded explanation without claiming TikTok rate limiting. Synthetic tests reproduce 18/18 failure and 17/18 partial failure, verify the persisted summary and notice dispatch, and check actual Slack wording. Backend verification: 955 passed, 8 PostgreSQL-only tests skipped because TEST_POSTGRES_DATABASE_URL was unavailable. No scrape, publication, push, PR, merge or deployment performed.
_________________________________________________________________________________
_________________________________________________________________________________
time: [06:16pm] [10-07-26] EDT
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/instagram-total-failure-degraded] /Users/smathdaddy-macbook/campaign-hub-instagram-degraded
type: [bug report]: reconcile requested Instagram creator outcomes
area: [backend], [testing], [review]

Independent review found that a missing Apify outcome map could be called 0 errored in Slack, and an unrelated successful outcome key could mask a complete failure. Instagram accounting now normalizes each requested creator name, counts only those creators, and records unknown or absent entries as missing outcomes. The complete-failure decision requires at least one requested creator and no requested ok/empty outcome. Slack reports missing separately. Synthetic tests cover all-error, partial, empty and extraneous maps plus normalized names. Backend verification: 958 passed, 8 PostgreSQL-only tests skipped without TEST_POSTGRES_DATABASE_URL. No scrape, publication, push, PR, merge or deployment performed.
_________________________________________________________________________________
_________________________________________________________________________________
time: [06:18pm] [10-07-26] EDT
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/instagram-total-failure-degraded] /Users/smathdaddy-macbook/campaign-hub-instagram-degraded
type: [bug report]: preserve uncertainty in Instagram cron outcome reporting
area: [backend], [testing], [review]

Final-head review found that missing-only outcomes were described as all scrapes failed, and conflicting normalized aliases could overwrite each other by map order. Conflicting aliases now count as missing regardless of insertion order. A degraded notice distinguishes all reported Instagram errors from no usable Instagram outcome evidence. Focused regressions cover both alias orders and each notice wording. Backend verification: 960 passed, 8 PostgreSQL-only tests skipped without TEST_POSTGRES_DATABASE_URL. No scrape, publication, push, PR, merge or deployment performed.
_________________________________________________________________________________
_________________________________________________________________________________
time: [06:34pm] [10-07-26] EDT
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/campaign-refresh-schedule-toggle] /Users/smathdaddy-macbook/campaign-hub-schedule-toggle
base: [origin/main] 4a0a0f54adda950da4247c056f3d450fed575bfd
type: [feature-request]: stage campaign-refresh-only scheduler switch
area: [backend], [testing], [review]

Added CAMPAIGN_REFRESH_SCHEDULER_ENABLED, default true, and passed it from app config to APScheduler initialization. False omits automatic campaign_refresh registration and starts the persistent SQLAlchemy scheduler paused, removes any retained campaign_refresh job, then resumes the other jobs. Removal failure stops the scheduler and clears its singleton for readiness retry. Manual and on-demand refresh entrypoints, their leases, and receipts were unchanged. Disposable SQLite tests prove an overdue old job cannot fire, other jobs remain, re-enabling registers campaign_refresh, the app forwards the setting, and removal failure never resumes. Backend verification: 945 passed, 8 PostgreSQL-only tests skipped without TEST_POSTGRES_DATABASE_URL. Transition is staged only: Railway remains unchanged until Mac Apify credential and delivery are approved/verified. Rollback is true plus restart and scheduled-job readback. Local disk held roughly 175 MiB available after removing only this agent's regenerable Content Lab test venv; no production environment, scrape, publication, push, PR, merge or deployment was touched.
_________________________________________________________________________________
_________________________________________________________________________________
time: [01:20pm] [09-10-26] EDT
agent: [claude code], [claude-opus-5-5]
worktree: [claude/issue-257-crm-sync-scheduler] ~/dev/oceanwork/rch-257 on macmini-ip
type: [feature-request]: issue #257 PR #258 brought current with main
area: [backend], [testing]

Merged origin/main cd16752 into the #257 CRM discovery branch without rewriting history. The only code conflict was the scheduler startup log, now reporting both the campaign_refresh toggle and the crm_sync interval; crm_sync registers unconditionally, so CAMPAIGN_REFRESH_SCHEDULER_ENABLED=false keeps the one-minute CRM discovery job, now pinned in the toggle regression. Full Python 3.11 suite: 1055 passed, 8 PostgreSQL-only skips. No deployment, production CRM request or campaign creation occurred; the job runs on Railway after merge and deploy with SCHEDULER_ENABLED=true and no new env vars.
_________________________________________________________________________________
