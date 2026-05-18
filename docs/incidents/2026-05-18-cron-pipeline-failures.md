# 2026-05-18 — Campaign refresh cron pipeline failures

**Status:** Open. Filter bug fix shipped ([PR #125](https://github.com/Risingtides-dev/risingtides-campaign-hub/pull/125)); worker-hang issue identified but unresolved.

**Visible symptom:** Scrape Tasks page is empty / stale every day. No new links flowing in.

**Root cause (data-side, fix shipped):** `_filter_by_date` in `campaign_manager/services/scheduler.py` rejected `datetime` objects with an `isinstance(ts, str)` check, silently dropping every freshly-scraped video. `total_videos_checked: 0` in every cron summary going back to 2026-04-19 (at least).

**Root cause (operational, unresolved):** Cron runs frequently never reach `finish_cron_log()` — the row stays `status='running'` indefinitely. 19 orphaned rows accumulated since 2026-05-06.

## Zero new matches streak

Every completed `campaign_refresh` run for at least 30 days returned `total_new_matches: 0` and `total_videos_checked: 0`. The cron infrastructure ran, but every video was being filtered out before reaching the matcher.

| Day | Completed | Still running | Sum new_matches | Sum videos_checked | Degraded flag set |
|---|---|---|---|---|---|
| 2026-05-18 | 6 | 6 | 0 | 0 | 6 |
| 2026-05-17 | 1 | 0 | 0 | 0 | 1 |
| 2026-05-16 | 1 | 0 | 0 | 0 | 1 |
| 2026-05-15 | 1 | 0 | 0 | 0 | 1 |
| 2026-05-14 | 1 | 0 | 0 | 0 | 1 |
| 2026-05-13 | 1 | 6 | 0 | 0 | 1 |
| 2026-05-12 | 2 | 1 | 0 | 0 | 2 |
| 2026-05-11 | 3 | 0 | 0 | 0 | 3 |
| 2026-05-10 | 1 | 0 | 0 | 0 | 1 |
| 2026-05-08 | 9 | 5 | 0 | 0 | 9 |
| 2026-05-07 | 1 | 0 | 0 | 0 | 0 |
| 2026-05-06 | 3 | 1 | 0 | 0 | 2 |
| 2026-05-05 → 2026-04-19 | 1/day | 0 | 0 | 0 | 0 (flag added later) |

The `degraded` flag was added 2026-05-08 — older runs reported `degraded: 0` because the field didn't exist yet, not because they were healthy.

Existing matches in `matched_videos` come from a separate path (`internal_scrape` + manual / Slack-driven adds), which is why the DB isn't empty.

## Orphaned cron_log rows (status='running', no progress)

19 rows total. None have a `finished_at`. Sampling from the data:

| id | job_type | started_at (server) | hours stuck |
|---|---|---|---|
| 131 | campaign_refresh | 2026-05-06 16:12:49 | 286.8 |
| 141 | campaign_refresh | 2026-05-08 12:22:53 | 242.7 |
| 142 | campaign_refresh | 2026-05-08 12:22:57 | 242.7 |
| 143 | campaign_refresh | 2026-05-08 12:25:46 | 242.6 |
| 144 | campaign_refresh | 2026-05-08 12:33:47 | 242.5 |
| 147 | campaign_refresh | 2026-05-08 13:56:06 | 241.1 |
| 155 | campaign_refresh | 2026-05-12 17:17:40 | 141.7 |
| 160 | campaign_refresh | 2026-05-13 11:10:04 | 123.9 |
| 161 | campaign_refresh | 2026-05-13 11:11:26 | 123.9 |
| 162 | campaign_refresh | 2026-05-13 11:11:28 | 123.9 |
| 163 | campaign_refresh | 2026-05-13 11:11:40 | 123.8 |
| 164 | campaign_refresh | 2026-05-13 12:01:31 | 123.0 |
| 165 | campaign_refresh | 2026-05-13 12:01:37 | 123.0 |
| 176 | campaign_refresh | 2026-05-18 05:50:41 | 9.2 |
| 177 | campaign_refresh | 2026-05-18 06:00:00 | 9.0 |
| 178 | internal_scrape | 2026-05-18 06:02:00 | 9.0 |
| 180 | campaign_refresh | 2026-05-18 06:54:29 | 8.1 |
| 183 | campaign_refresh | 2026-05-18 10:14:22 | 4.8 |
| 184 | campaign_refresh | 2026-05-18 10:55:46 | 4.1 |

Pattern: bursts of orphans appear on days with manual trigger activity (clusters on 5-08, 5-13, 5-18) — consistent with the [CAMP-52](https://linear.app/rising-tides-agents/issue/CAMP-52) race condition (manual + scheduled jobs colliding).

## Today's run timeline (2026-05-18)

| run | start (server) | end | duration | new | checked | notes |
|---|---|---|---|---|---|---|
| 175 | 05:37:21 | 05:44:24 | 7m | 0 | 0 | pre-deploy, completed |
| 176 | 05:50:41 | — | 9h+ | — | — | manual trigger; orphaned |
| 177 | 06:00:00 | — | 9h+ | — | — | scheduled cron; orphaned (collided w/ 176) |
| 178 | 06:02:00 | — | 9h+ | — | — | scheduled internal_scrape; orphaned (collided w/ 176-177) |
| 179 | 06:22:19 | 06:47:23 | 25m | 0 | 0 | completed, buggy code |
| 180 | 06:54:29 | — | 8h+ | — | — | orphaned |
| 181 | 07:10:07 | 07:30:28 | 20m | 0 | 0 | completed, buggy code |
| 182 | 07:42:57 | 08:03:23 | 20m | 0 | 0 | completed, buggy code |
| 183 | 10:14:22 | — | 4.8h+ | — | — | post-deploy of PR #116/#125 — orphaned |
| 184 | 10:55:46 | — | 4.1h+ | — | — | manual re-trigger — also orphaned |

## What was fixed

- **[PR #116](https://github.com/Risingtides-dev/risingtides-campaign-hub/pull/116)** — Restored sound-ID enrichment (deleted in RTA-44). Per-video HTML fetch via Decodo proxy, only on new videos.
- **[PR #125](https://github.com/Risingtides-dev/risingtides-campaign-hub/pull/125)** — `_filter_by_date` now accepts both `datetime` and `str` timestamps. This is the actual root cause of the month-long zero-match streak.

## What's NOT fixed

- **Runs orphan instead of completing.** Two test runs after the deploy (183, 184) hung for 4+ hours. Cannot verify [PR #125](https://github.com/Risingtides-dev/risingtides-campaign-hub/pull/125) end-to-end until a run completes. Working theory: deploys recycle the worker mid-run; APScheduler's `SQLAlchemyJobStore` retains the next scheduled tick, but the in-flight `run_campaign_refresh()` call has no resume / retry behavior on the cron_log side. New triggers land on a fresh worker but appear to hang too — root cause for the hang itself still unclear (proxy bandwidth, DB pool exhaustion, deadlock with `apscheduler_jobs` lock are all candidates; nothing confirmed).
- **[CAMP-52](https://linear.app/rising-tides-agents/issue/CAMP-52)** — Manual + scheduled cron jobs can collide. Confirmed by today's 176/177/178 cluster. Fix not yet shipped.

## Open questions

1. Why do triggered runs hang? Is the trigger endpoint creating the cron_log row but failing to actually invoke `run_campaign_refresh()`? Or is it being invoked, but blocking on something (Decodo proxy, DB connection pool, yt-dlp subprocess)?
2. Is the Railway worker still up? `/health` responds in 96ms — but that's a different code path than the cron job. A hung scheduler thread wouldn't necessarily block the HTTP server.
3. Cleanup: should we have a periodic janitor that marks rows running > N minutes as `failed`? Currently they stay `running` forever and pollute the dashboard.

## Cleanup pending

19 orphaned cron_log rows should be marked `failed` with `summary={"error":"orphaned by worker restart or hang"}`. Not done yet (requires write access to prod DB).

## Files / references

- `campaign_manager/services/scheduler.py` — `_filter_by_date` (fixed), `trigger_job`, `run_campaign_refresh`, `_scrape_creator_accounts_v2`
- `src/scrapers/master_tracker.py` — `enrich_videos_with_sound_ids` (added in PR #116), `scrape_tiktok_account`
- `frontend/src/pages/ScrapeTasks.tsx` — UI; renders queue from `useScrapeTaskQueue` (downstream of `matched_videos.tracked_at IS NULL`)
- [GitHub PR #116](https://github.com/Risingtides-dev/risingtides-campaign-hub/pull/116), [GitHub PR #125](https://github.com/Risingtides-dev/risingtides-campaign-hub/pull/125)
- [Linear CAMP-52](https://linear.app/rising-tides-agents/issue/CAMP-52)
