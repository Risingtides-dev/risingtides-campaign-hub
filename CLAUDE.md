# Campaign Hub

> **Last updated:** 2026-05-21
> **Status:** Frontend and backend deployed. Active development on campaign management features.
> **Handoff:** Read `docs/handoff.md` for next steps and migration plan.

## Team & Repo Routing

**This repo is the canonical home for the `Campaign Hub` Linear team.** Linear issue prefix: `CAMP-NNN`.

Team is the routing primitive — not project. Workspace-wide map:

| Linear team | Canonical GitHub repo |
|---|---|
| Campaign Hub | `Risingtides-dev/risingtides-campaign-hub` *(this repo)* |
| Sales-Agents | `Risingtides-dev/sales-agent` |
| Ocean-OS    | `Risingtides-dev/ocean-os` |
| Content-hub | `KINGMAKER-SYSTEMS/content-posting-lab` |

**Rules for agents working on `CAMP-NNN` issues:**

- Use **only** `Risingtides-dev/risingtides-campaign-hub` for implementation, branches, commits, PRs, and code investigation.
- If a Linear issue mentions or links to a different repo, **flag it as misrouted** and state which repo it should belong to — do not start implementation.
- Before coding, inspect the issue title, description, parent/related issues, existing GitHub links, and recent PRs to confirm repo fit. If still ambiguous, **stop and ask** instead of guessing.
- Post all implementation updates back to the Linear issue: branch name, PR link, merge status, and any required follow-up steps.
- Never open PRs in `sales-agent`, `ocean-os`, or `content-posting-lab` for Campaign Hub work.

**Hard rule:** do not guess the repository. Do not silently switch repositories. If cross-repo work is genuinely required, state that explicitly on the Linear issue before proceeding.

## What This Is

Internal campaign management platform for Rising Tides -- a social media marketing agency running TikTok/Instagram UGC influencer campaigns for major record labels. This app is where we stage campaigns, book creators, scrape for post links, track budgets/payments, and pull live performance data from Cobrand.

## Live Deployments

| Component | URL | Infra |
|---|---|---|
| App (frontend + API) | https://risingtides-campaign-hub-production.up.railway.app | Railway |
| Database | PostgreSQL | Railway plugin |

**Single-surface deploy:** the Dockerfile builds the Vite SPA and bundles it into the same container that runs the Flask API, so Railway serves both. The frontend is at `/`, the API is under `/api/*`. There is no separate Vercel deployment — the old `risingtides-campaign-hub.vercel.app` project was deleted on 2026-05-20 (it had stopped auto-deploying on 2026-04-17 and was returning 404s from a stale state).

## Architecture

**Frontend:** Vite + React + TypeScript + shadcn/ui + Tailwind (served by Railway)
**Backend:** Flask API (Python) + SQLAlchemy + PostgreSQL (Railway)
**Integrations:** Cobrand (live post tracking), Notion CRM (campaign intake via webhook/polling), Slack (booking intake via agent)

### Source of Truth Boundaries

| System | Owns |
|---|---|
| Notion CRM | Client relationships, campaign bookings (client paying us) |
| Campaign Hub (this app) | Creator roster, rates, posts owed, payments, budget allocation, scraping |
| Cobrand | Real-time post performance (views, engagement, submission counts) |

Financial data lives here. Performance data comes from Cobrand. Client data comes from Notion. Do not duplicate sources of truth.

## Project Structure

```
risingtides-campaign-hub/
  campaign_manager/              # Flask backend (API only, 29 endpoints)
    __init__.py                  # App factory (create_app)
    config.py                    # Environment config
    db.py                        # SQLAlchemy data access layer
    models.py                    # Campaign, Creator, MatchedVideo, InboxItem, etc.
    blueprints/
      campaigns.py               # /api/campaigns, /api/campaign/<slug>/*, /api/creators/*
      internal.py                # /api/internal/*
      inbox.py                   # /api/inbox/*
      webhooks.py                # /api/webhooks/notion, /api/webhooks/notion/sync
      health.py                  # /health
    services/
      cobrand.py                 # Fetches live stats from Cobrand share pages (__NEXT_DATA__)
      notion.py                  # Queries Notion CRM for new Client entries
    utils/
      helpers.py                 # slugify, extract_sound_id, TikTok URL resolution, etc.
      budget.py                  # calc_budget, calc_stats
  src/
    scrapers/                    # TikTok/Instagram scraping (yt-dlp based)
      master_tracker.py          # Parallel scraping + sound matching
      scrape_external_accounts_cached.py
    utils/
      get_post_links_by_song.py  # Internal creator scraping
  frontend/                      # React app (Vite + TypeScript)
    src/
      lib/
        api.ts                   # API client (24 endpoint functions)
        types.ts                 # TypeScript interfaces for all API data
        queries.ts               # React Query hooks (24 hooks)
      pages/
        CampaignsList.tsx        # Sortable campaign table + create form
        CampaignDetail.tsx       # Full campaign view with creators, cobrand, stats
        CreatorDatabase.tsx      # Cross-campaign creator roster
        CreatorProfilePage.tsx   # Individual creator history and stats
        InternalTikTok.tsx       # Internal creator scraping tool
        InternalCreatorDetail.tsx # Per-creator video cache
        SlackInbox.tsx           # Booking intake from Slack agent
      components/
        layout/                  # Sidebar, Layout shell (mobile hamburger menu)
        campaigns/               # CampaignsTable, CreatorsTable, CampaignHeader, etc.
        internal/                # CreatorSidebar, ScrapeProgress, SongsResults
        inbox/                   # InboxCard
        ui/                      # shadcn/ui components (table, button, card, badge, etc.)
  docs/
    handoff.md                   # Current state and next steps
    plans/                       # Design docs and implementation plans
  Dockerfile                     # Backend Docker image for Railway

  # Legacy (not used, pending removal after migration confirmed):
  campaign_manager/web_dashboard.py   # Old monolithic Flask app (~1,900 lines)
  campaign_manager/templates/         # Old Jinja HTML templates (6 files)
```

## Data Flow

```
Notion CRM (client books)
  |  webhook / polling sync
  v
Campaign Hub (campaign created)
  |
  +-- Slack Agent --> Inbox --> Jake approves --> Creators added
  |
  +-- Scraper finds posts using sound --> Links collected
  |
  +-- One-click: copy links + open Cobrand upload page
  |
  v  enter Cobrand tracking URL into campaign
Campaign Hub <-- Cobrand (live performance stats)
```

## Git Remotes

| Remote | Repo | Purpose |
|---|---|---|
| `origin` | https://github.com/Risingtides-dev/risingtides-campaign-hub | Deploy fork — where new work lands and Railway deploys from |
| `upstream` | https://github.com/jakebalik-bit/risingtides-campaign-hub | Jake's repo — local emergency fallback. Only gets rebased forward from the fork **after** a change is proven in production. |

Tag `pre-migration-backup` on both remotes points to the old codebase.

**Deploy flow (the only flow for new work):**
1. Branch off `origin/main`
2. Push branch to `origin` (the fork)
3. `gh pr create --repo Risingtides-dev/risingtides-campaign-hub --base main` → open PR against the fork
4. Merge PR → Railway auto-deploys from Risingtides-dev/main

**Do NOT push branches or open PRs to `upstream` (jakebalik-bit) for in-flight work.** Jake's repo is a quick fallback we can revert to locally if the fork breaks. It only gets rebased forward from the fork *after* a feature is fully green in production.

## Environment Variables

### Railway (Backend)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection (auto-set by Railway Postgres plugin) |
| `SECRET_KEY` | Flask session secret |
| `CORS_ORIGINS` | Set to the Railway URL (`https://risingtides-campaign-hub-production.up.railway.app`). Frontend and API share an origin now, so CORS is mostly belt-and-suspenders. |
| `NOTION_API_KEY` | Notion internal integration token |
| `NOTION_CRM_DATABASE_ID` | `1961465b-b829-80c9-a1b5-c4cb3284149a` |
| `PORT` | Auto-set by Railway |

#### Decodo proxy

- `TIKTOK_PROXY` — full URL `http://USER:PASS@gate.decodo.com:PORT`. Consumed by yt-dlp via `src/scrapers/yt_dlp_runner.py:build_tiktok_cmd()` (reads `os.environ["TIKTOK_PROXY"]` and passes to yt-dlp's `--proxy` flag). Required for TikTok scraping in prod. Current rotation uses NA-only IPs with sticky 10-minute sessions on port `10001`.
- `DECODO_API_KEY` — staged for future agent observability (bandwidth checks, sub status, endpoint listing). Not currently consumed by any code path. Decodo API base: `https://api.decodo.com/v2/` — auth via `Authorization: Bearer ${DECODO_API_KEY}`. Reference: TODO — confirm exact endpoint paths from Decodo dashboard docs before wiring up observability.
- `RESIDENTIAL_PROXY_URL` — **dead post-RTA-44.** Do not set. Was used by deleted `extract_sound_id_from_video_robust` in `src/scrapers/master_tracker.py`; no longer read by any code on `origin/main`. If it appears on a Railway service from a pre-RTA-44 deploy, it's safe to unset (cosmetic only).

### Frontend build (Vite)

The SPA is built inside the Railway Dockerfile (`npm run build` in the `frontend/` stage) and copied into the Flask container's static dir. There is no separate frontend deploy. `VITE_API_URL` is empty / unset — the SPA calls the API on the same origin (`/api/*`), no cross-origin wiring required.

## Key Technical Decisions

- **Cobrand integration parses `__NEXT_DATA__` from share page HTML.** No official API -- we scrape the Next.js server-rendered JSON payload. Only performance fields consumed (submissions, comments), never financial (budget, spend).
- **Cobrand share URLs contain auth tokens.** Stored in DB, not exposed beyond what's needed for iframe embed.
- **Scraping runs in background threads.** Both campaign refresh and internal scrape use ThreadPoolExecutor with status polling. Redis + Celery is the upgrade path if needed.
- **Dual storage mode.** db.py supports both Postgres (production) and file-based JSON/CSV (local dev). Production always uses Postgres.
- **Creator database** aggregates stats across all campaigns -- no new DB tables needed, just cross-campaign queries on existing Creator and MatchedVideo models.
- **Internal-group slugs are Notion-derived** (RTA-5). Slugs for `internal_creator_groups` come from `slugify()` applied to Notion's `Group` field (parent label) and `Poster` field (booker). Verify the live label/booker list from the DB (`SELECT slug, title, kind FROM internal_creator_groups`) — it drifts as Notion changes. As of 2026-05-21, real label slugs are `warner`, `atlantic`, `warner_test`, `internal`; booker slugs include the canonical five (`jake_balik`, `john_smathers`, `sam_hudgens`, `eric_cromartie`, `johnny_balik`) plus `seeno_shahrooz` (business manager) and a handful of typo-driven duplicates. Notion also has a `Group ` property *with a trailing space* (mirrored as `notion_subgroup`) used for artist/campaign names — the resolver currently does NOT consult it, which causes sub-labels like `Warner Test UGC` to merge into the parent `warner` group. Old `_pages`-suffixed slugs are deprecated; routes like `/api/internal/groups/warner_pages/stats` return 404 (use `warner`).

## Recent Changes

- **Removed dead `Campaign.status` column** (2026-06-30) -- The `status` field defaulted to `"active"` on every campaign and nothing ever wrote anything else, so a raw `status='active'` count returned all campaigns and looked like "all active." Removed every code reference: the `status=` param on `list_campaigns()` / `list_campaigns_with_creators()`, all `filter_by(status=...)` filters, the model column + `to_dict` field, the API fields, the frontend "Status" column, the local scraper caller (`scripts/pi_active_campaigns_scrape.py`), and stale tests. **The prod DB column is dropped as a DELIBERATE post-deploy step, NOT auto-run in `db.init()`** (auto-running a schema DROP on every connect broke prod on 2026-06-27 — see `scripts/migrations/drop_campaigns_status.sql`; run it only after this deploys). **Active campaigns = `completion_status != 'completed'`** (the Active/Finished tabs already use this). `completion_status` cycles `none → booked → completed → none` via the table checkbox. There is no other active/inactive flag.
- **Notion sync cron** (2026-05-13, RTA-10) -- The APScheduler now runs `run_notion_sync()` on a 15-minute interval (configurable via `NOTION_SYNC_INTERVAL_MINUTES`, clamped 1–1440). Each tick: `sync_master_pages(triggered_by="cron")` → if pages were fetched, `resolve_memberships(triggered_by="cron", sync_log_id=...)` chained onto the same audit row. In-flight guard (`_notion_sync_in_progress` + lock) makes overlapping ticks a no-op; exceptions in either stage are caught + logged so the scheduler thread stays alive. First tick fires one interval after boot (no surprise scrape on deploy). Completes the P0 Notion sync chain.
- **Membership resolver** (2026-05-13, RTA-9) -- New `resolve_memberships()` in `campaign_manager/services/notion_sync.py` reconciles `internal_creator_group_members` against the `notion_master_pages` mirror. Each row resolves to at most one label group (from `notion_group`) and one booker group (from `poster`); missing groups are auto-created with the correct kind. Cleanup pass removes memberships the mirror no longer attests — but ONLY in `kind IN ('label','booked_by')` groups. `kind='custom'` (e.g. `general`) is never touched. Smoke chains both stages: `python scripts/notion_sync_smoke.py --resolve`. RTA-10 (cron) calls sync → resolve every 15 min.
- **Notion → Postgres full sync service** (2026-05-13, RTA-8) -- New `campaign_manager/services/notion_sync.py` mirrors the Notion "🌌 Master Pages" database into `notion_master_pages` and writes one `notion_sync_log` row per run. Idempotent. Reuses the property-extractor helpers from `services/notion.py` (no new SDK dep). Smoke: `NOTION_API_KEY=... DATABASE_URL=... python scripts/notion_sync_smoke.py`. Uses the existing `NOTION_API_KEY` env var (already set on Railway). RTA-9 (membership resolver) builds on this mirror.
- **Slug rename: drop `_pages` suffix on labels** (2026-05-12, RTA-5) -- `warner_pages` → `warner`, `atlantic_pages` → `atlantic`, `warner_test_pages` → `warner_test`. Booker slugs unchanged. Run `python scripts/rename_label_slugs.py` against prod DB to migrate row values. (The script's mapping table still includes a `seeno_pages → seeno` entry; that mapping is harmless but `seeno` is a booker/manager slug, not a label — left in place for idempotency.)
- **Active/Finished campaign tabs** (2026-03-12) -- Campaigns list now splits into Active and Finished tabs. Green check (completion_status: "completed") moves a campaign to the Finished tab. PR #1 to upstream.
- **Completion status cycling** -- Checkbox in campaigns table cycles: none → booked → completed (green check)

## Pending Work

1. **Scraper refinement** -- Original sound matching issues need investigation and fixes
2. **Data migration** -- Import 14 active campaigns from Jake's local disk (campaign.json + creators.csv + matched_videos.json per campaign)
3. **Platform-aware social links** -- Creator profiles should show TikTok/IG links based on which platforms they were booked on
4. **Notion sync test** -- Hit `POST /api/webhooks/notion/sync` with real data and verify campaigns are created correctly
5. **Legacy cleanup** -- Remove `web_dashboard.py` and `templates/` after migration confirmed

## Development Guidelines

- Backend is pure JSON API. No HTML templates, no Jinja rendering.
- Frontend mirrors the original UI design (colors, layout, typography). Don't redesign -- replicate and enhance.
- All tables use TanStack Table for sorting/filtering.
- All API calls use React Query with proper loading/error states.
- No full page refreshes for user actions.
- Mobile layout: sidebar collapses to hamburger, tables scroll horizontally.

## Running Tests

Backend smoke tests live in `tests/`. They run against in-memory SQLite (not Postgres) and bypass `db.init`'s Postgres-only ALTER TABLE migrations -- they cover endpoint behavior, not schema rollouts.

```
pip install -r requirements-dev.txt
python3 -m pytest
```

The conftest registers individual blueprints directly rather than calling `create_app`, so tests don't pull in apscheduler/yt-dlp/slack-bolt. When you add tests for a new blueprint, register it the same way in `tests/conftest.py:_build_test_app`.

## What NOT To Do

- Don't put financial/budget data in Cobrand sync. This app tracks money.
- Don't scrape TikTok for view counts on existing posts. Cobrand handles that.
- Don't add auth yet. Internal tool, small team, no auth for now.
- Don't over-engineer the scraping infrastructure. Threads + polling works.
- Don't delete `web_dashboard.py` or `templates/` until data migration is confirmed working.
