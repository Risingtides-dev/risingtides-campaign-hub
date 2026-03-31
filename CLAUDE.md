# Campaign Hub

> **Last updated:** 2026-03-12
> **Status:** Frontend and backend deployed. Active development on campaign management features.
> **Handoff:** Read `docs/handoff.md` for next steps and migration plan.

## What This Is

Internal campaign management platform for Rising Tides -- a social media marketing agency running TikTok/Instagram UGC influencer campaigns for major record labels. This app is where we stage campaigns, book creators, scrape for post links, track budgets/payments, and pull live performance data from Cobrand.

## Live Deployments

| Component | URL | Infra |
|---|---|---|
| Frontend (React) | https://risingtides-campaign-hub.vercel.app | Vercel |
| Backend (Flask API) | https://risingtides-campaign-hub-production.up.railway.app | Railway |
| Database | PostgreSQL | Railway plugin |

## Architecture

**Frontend:** Vite + React + TypeScript + shadcn/ui + Tailwind (Vercel)
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
| `origin` | https://github.com/jakebalik-bit/risingtides-campaign-hub | Jake's repo (primary) |
| `fork` | https://github.com/Risingtides-dev/risingtides-campaign-hub | Deploy fork (Railway + Vercel deploy from here) |

Push to `origin`, then open PR to `fork` (Risingtides-dev) to trigger deploys. Tag `pre-migration-backup` on both remotes points to the old codebase.

**Deploy flow:** `git push origin main` → `gh pr create --repo Risingtides-dev/risingtides-campaign-hub` → merge PR → Railway + Vercel auto-deploy from Risingtides-dev/main.

## Environment Variables

### Railway (Backend)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection (auto-set by Railway Postgres plugin) |
| `SECRET_KEY` | Flask session secret |
| `CORS_ORIGINS` | `https://risingtides-campaign-hub.vercel.app` |
| `NOTION_API_KEY` | Notion internal integration token |
| `NOTION_CRM_DATABASE_ID` | `1961465b-b829-80c9-a1b5-c4cb3284149a` |
| `PORT` | Auto-set by Railway |

### Vercel (Frontend)

| Variable | Purpose |
|---|---|
| `VITE_API_URL` | `https://risingtides-campaign-hub-production.up.railway.app` |

## Key Technical Decisions

- **Cobrand integration parses `__NEXT_DATA__` from share page HTML.** No official API -- we scrape the Next.js server-rendered JSON payload. Only performance fields consumed (submissions, comments), never financial (budget, spend).
- **Cobrand share URLs contain auth tokens.** Stored in DB, not exposed beyond what's needed for iframe embed.
- **Scraping runs in background threads.** Both campaign refresh and internal scrape use ThreadPoolExecutor with status polling. Redis + Celery is the upgrade path if needed.
- **Dual storage mode.** db.py supports both Postgres (production) and file-based JSON/CSV (local dev). Production always uses Postgres.
- **Creator database** aggregates stats across all campaigns -- no new DB tables needed, just cross-campaign queries on existing Creator and MatchedVideo models.

## Recent Changes

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

## What NOT To Do

- Don't put financial/budget data in Cobrand sync. This app tracks money.
- Don't scrape TikTok for view counts on existing posts. Cobrand handles that.
- Don't add auth yet. Internal tool, small team, no auth for now.
- Don't over-engineer the scraping infrastructure. Threads + polling works.
- Don't delete `web_dashboard.py` or `templates/` until data migration is confirmed working.
