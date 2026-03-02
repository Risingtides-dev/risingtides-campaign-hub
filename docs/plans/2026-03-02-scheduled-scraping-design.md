# Scheduled Daily Scraping

> **Date:** 2026-03-02
> **Status:** Design approved, pending implementation
> **Depends on:** Apify migration (deployed 2026-03-02)

## Problem

Campaign refreshes and internal scrapes only run when someone manually triggers them. Jake shouldn't have to remember to hit refresh every morning. We need automated daily scraping so match data is always current when the team starts work.

## Scope

Two jobs, both running daily at 6 AM EST:

1. **Campaign refresh** — iterate all active campaigns, scrape their creators via Apify, run matching, update match counts and stats.
2. **Internal scrape** — scrape all internal creators via Apify, update the per-account caches and song groupings.

Both jobs log results to a `cron_logs` DB table and post a summary to Slack.

## Architecture

### Approach: In-Process APScheduler

APScheduler's `BackgroundScheduler` runs inside the Flask/gunicorn process. No new Railway services, no external cron infrastructure, no additional billing.

- Jobs call the same Apify `scrape_profiles()` and matching logic already deployed.
- `SQLAlchemyJobStore` uses the existing Postgres connection for job state and built-in locking (prevents duplicate runs across gunicorn workers).
- Scheduler initializes in `create_app()` gated on `SCHEDULER_ENABLED=true` env var.

### Why not alternatives

- **Railway Cron Service** — $5/mo extra, has to HTTP-call each campaign individually, separate deploy/logs/debugging.
- **GitHub Actions** — can't access internal functions, limited to API surface, harder to add Slack/logging.
- **Celery/Redis** — massive overkill for two daily jobs. Upgrade path if we ever need minute-level scheduling.

## Data Model

New table `cron_log`:

```sql
CREATE TABLE cron_log (
    id          SERIAL PRIMARY KEY,
    job_type    VARCHAR(50) NOT NULL,   -- 'campaign_refresh' | 'internal_scrape'
    status      VARCHAR(20) NOT NULL,   -- 'running' | 'completed' | 'failed'
    started_at  TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    summary     JSON                     -- job-specific results
);

CREATE INDEX idx_cron_log_job_type ON cron_log (job_type);
CREATE INDEX idx_cron_log_started_at ON cron_log (started_at DESC);
```

### Summary JSON shapes

**campaign_refresh:**
```json
{
  "campaigns_total": 14,
  "campaigns_refreshed": 14,
  "campaigns_failed": 0,
  "total_new_matches": 47,
  "total_videos_checked": 2100,
  "discovered_sound_ids": ["760568..."],
  "errors": [],
  "per_campaign": {
    "bruno_mars_cha_cha_cha": { "new_matches": 3, "total_matches": 9 },
    "chezile_another_life": { "new_matches": 5, "total_matches": 29 }
  }
}
```

**internal_scrape:**
```json
{
  "accounts_total": 30,
  "accounts_successful": 22,
  "accounts_failed": 8,
  "total_videos": 101,
  "unique_songs": 53,
  "errors": []
}
```

## API Endpoints

New blueprint: `campaign_manager/blueprints/cron.py`

| Method | Path | Purpose |
|---|---|---|
| `GET /api/cron/status` | Scheduler state, next run times, whether enabled |
| `GET /api/cron/logs` | Paginated cron run history (default last 20) |
| `GET /api/cron/logs/<id>` | Single cron log detail with full summary |
| `POST /api/cron/trigger` | Manually trigger a job now (`{"job_type": "campaign_refresh"}`) |
| `POST /api/cron/toggle` | Enable/disable scheduler (`{"enabled": true}`) |

## Scheduler Jobs

### Job 1: `run_campaign_refresh()`

```
for each active campaign:
    1. Load meta, creators, sound_ids (same as _refresh_stats_inner)
    2. scrape_profiles(usernames, results_per_page=100)
    3. Run matching (musicId fast-path + song/artist + auto-discovery)
    4. Merge matches, update stats, update posts_done
    5. Accumulate per-campaign results
Log to cron_log table
Post Slack summary
```

This reuses the matching logic from `_refresh_stats_inner()` but extracted into a callable function (not tied to a Flask request context). The existing endpoint will still work for manual one-off refreshes.

### Job 2: `run_internal_scrape()`

```
1. Load internal creators list
2. scrape_profiles(creators, results_per_page=50)
3. Filter by time window (last 48h)
4. Merge into per-account caches
5. Group by song, save results
Log to cron_log table
Post Slack summary
```

Same logic as `_run_internal_scrape()` but without the thread-based status polling (not needed for cron — we just log the result).

## Slack Notifications

Uses the existing `slack-bolt` App's `client.chat_postMessage()`. Posts to `SLACK_CRON_CHANNEL` env var (falls back to `SLACK_BOOKING_CHANNEL` if not set).

**Success template:**
```
Daily scrape complete (6:03 AM EST)
Campaigns: 14 refreshed, 47 new matches found
Internal: 30 accounts, 101 videos, 53 unique songs
```

**Failure template:**
```
Daily scrape failed (6:01 AM EST)
Error: Apify API timeout
Campaign refresh: 8/14 completed before failure
```

**Partial failure** (some campaigns fail, others succeed): still posts success summary but includes error count and first 3 error messages.

## Gunicorn Worker Deduplication

APScheduler's `SQLAlchemyJobStore` stores jobs in Postgres. When multiple gunicorn workers start, they all connect to the same jobstore. APScheduler handles locking internally — only one worker executes each job instance. No custom locking code needed.

The `SCHEDULER_ENABLED` env var provides an additional manual kill switch.

## Configuration

New env vars (all optional with sane defaults):

| Variable | Default | Purpose |
|---|---|---|
| `SCHEDULER_ENABLED` | `false` | Set to `true` to activate the scheduler |
| `SLACK_CRON_CHANNEL` | (falls back to `SLACK_BOOKING_CHANNEL`) | Channel for cron notifications |
| `CRON_HOUR` | `6` | Hour to run (EST, 24h format) |
| `CRON_MINUTE` | `0` | Minute to run |

## File Changes

| File | Action | What |
|---|---|---|
| `campaign_manager/services/scheduler.py` | **CREATE** | Scheduler init, job functions, Slack posting |
| `campaign_manager/blueprints/cron.py` | **CREATE** | API endpoints for status/logs/trigger/toggle |
| `campaign_manager/__init__.py` | **MODIFY** | Init scheduler in `create_app()` |
| `campaign_manager/config.py` | **MODIFY** | Add scheduler env vars |
| `campaign_manager/db.py` | **MODIFY** | Add `CronLog` table + CRUD helpers |
| `campaign_manager/models.py` | **MODIFY** | Add `CronLog` SQLAlchemy model |
| `requirements.txt` | **MODIFY** | Add `APScheduler>=3.10.0` |
| `Dockerfile` | No change | APScheduler is pure Python, no system deps |

## Apify Cost Impact

No change in per-run cost. Just automated. At current volume (14 campaigns + 30 internal creators), each daily run is ~44 profile scrapes at ~100 results each = ~4,400 videos. Well within the estimated $50-90/mo Apify budget.

## Testing

1. **Local:** Set `SCHEDULER_ENABLED=true`, set `CRON_HOUR` to current hour + 1 minute, verify job fires.
2. **Manual trigger:** `POST /api/cron/trigger {"job_type": "campaign_refresh"}`, verify results match manual refresh.
3. **Slack:** Verify notification posts to configured channel.
4. **Logs:** `GET /api/cron/logs` returns the run history.
5. **Deploy:** Push to fork, set `SCHEDULER_ENABLED=true` on Railway, verify 6 AM run the next morning.
