# Campaign Hub -- Handoff Document

Date: 2026-02-23
Session: Full migration from Flask/Jinja monolith to React + Flask API

---

## What Was Built

Migrated the Campaign Hub from a server-rendered Flask/Jinja app to a modern React frontend + Flask JSON API architecture. Added Cobrand live stats integration, Notion CRM sync, a creator database, sortable tables, and mobile responsive layout.

## Current State

### Deployed and Live

| Component | URL | Infra |
|---|---|---|
| Frontend (React) | https://risingtides-campaign-hub.vercel.app | Vercel |
| Backend (Flask API) | https://risingtides-campaign-hub-production.up.railway.app | Railway |
| Database | PostgreSQL (Railway plugin) | Railway |

CORS is configured. Notion API key and CRM database ID are set as Railway env vars. Everything is connected and functional but the database is **empty** -- awaiting data migration.

### Git State

- **Repo (primary):** https://github.com/jakebalik-bit/risingtides-campaign-hub (main branch, up to date)
- **Repo (deploy fork):** https://github.com/Risingtides-dev/risingtides-campaign-hub (Railway deploys from here)
- **Branch:** `main` has all migration work merged
- **Backup tag:** `pre-migration-backup` points to the old codebase pre-migration
- **Remote `origin`:** jakebalik-bit repo
- **Remote `fork`:** Risingtides-dev repo (push here to trigger Railway deploy)

### Railway Env Vars Set

- `DATABASE_URL` (auto from Postgres plugin)
- `SECRET_KEY`
- `CORS_ORIGINS` = `https://risingtides-campaign-hub.vercel.app`
- `NOTION_API_KEY`
- `NOTION_CRM_DATABASE_ID` = `1961465b-b829-80c9-a1b5-c4cb3284149a`

### Vercel Env Vars Set

- `VITE_API_URL` = `https://risingtides-campaign-hub-production.up.railway.app`

---

## What Needs to Happen Next

### Priority 1: Data Migration (needs Jake's local disk)

Jake's local machine has the campaign data in `campaign_manager/campaigns/active/` with per-campaign directories containing:
- `campaign.json` (metadata: title, artist, song, sound_id, budget, dates)
- `creators.csv` (creator roster: usernames, rates, posts owed/done, paypal, paid status)
- `matched_videos.json` (scraped video links with views/likes)
- `scrape_log.json` (last scrape results)

There are **14 active campaigns** to migrate.

**Migration approach:** Write a script that reads each campaign directory and POSTs the data to the new API endpoints. The backend already handles all these data shapes.

**Alternative:** If the old Railway Postgres is still running, we can do a direct database dump/restore into the new Railway Postgres.

**Data also available in GitHub** (partial, for reference only):
- `KINGMAKER-SYSTEMS/jake` (branch `jake`): `config/campaign_sounds.json` has 86 campaign sound IDs/artist/song. `campaign_automation/bookings.json` has booking records. These are incomplete -- missing budgets, matched videos, full creator rosters.

### Priority 2: Platform-Aware Social Links

Creator profile pages currently show "View on TikTok" for everyone. Should be platform-aware:
- If creator was booked for TikTok campaigns: show TikTok link
- If booked for Instagram: show IG link
- If both: show both

Small UI change on `frontend/src/pages/CreatorProfilePage.tsx` and `frontend/src/pages/CreatorDatabase.tsx`.

### Priority 3: Notion Sync Test

The Notion webhook and sync endpoints are built but untested with real data. Once campaigns exist in the database:
1. Hit `POST /api/webhooks/notion/sync` to pull new "Client" entries from the CRM
2. Verify campaigns are created correctly with all mapped fields
3. Set up a recurring sync (n8n automation or background polling)

### Priority 4 (future): Remove Legacy Code

Once migration is confirmed and team is using the new frontend:
- Delete `campaign_manager/web_dashboard.py` (~1,900 lines)
- Delete `campaign_manager/templates/` (6 Jinja HTML files)
- These are dead code -- not served or imported by anything

---

## Architecture Quick Reference

### Backend (Flask API on Railway)

```
campaign_manager/
  __init__.py          # App factory (create_app)
  config.py            # Env var config
  db.py                # SQLAlchemy data access layer
  models.py            # Campaign, Creator, MatchedVideo, InboxItem, etc.
  blueprints/
    campaigns.py       # /api/campaigns, /api/campaign/<slug>/*, /api/creators/*
    internal.py        # /api/internal/*
    inbox.py           # /api/inbox/*
    webhooks.py        # /api/webhooks/notion, /api/webhooks/notion/sync
    health.py          # /health
  services/
    cobrand.py         # Fetches live stats from Cobrand share pages
    notion.py          # Queries Notion CRM for new Client entries
  utils/
    helpers.py         # slugify, extract_sound_id, etc.
    budget.py          # calc_budget, calc_stats
```

29 API endpoints total. All return JSON. No HTML rendering.

### Frontend (React on Vercel)

```
frontend/src/
  App.tsx              # React Router (6 routes)
  lib/
    api.ts             # API client (24 endpoint functions)
    types.ts           # TypeScript interfaces
    queries.ts         # React Query hooks (24 hooks)
  pages/
    CampaignsList.tsx  # Sortable campaign table + create form
    CampaignDetail.tsx # Full campaign view with creators, cobrand, stats
    CreatorDatabase.tsx # Cross-campaign creator roster
    CreatorProfilePage.tsx # Individual creator history
    InternalTikTok.tsx # Internal creator scraping tool
    InternalCreatorDetail.tsx # Per-creator video cache
    SlackInbox.tsx     # Booking intake from Slack agent
  components/
    layout/            # Sidebar, Layout shell
    campaigns/         # CampaignsTable, CreatorsTable, CampaignHeader, etc.
    internal/          # CreatorSidebar, ScrapeProgress, SongsResults
    inbox/             # InboxCard
    ui/                # shadcn/ui components
```

### Key Design Decisions

- **Campaign Hub owns financial data** (rates, payments, budgets). Cobrand owns performance data (views, engagement).
- **Cobrand integration** parses `__NEXT_DATA__` from share page HTML. No official API.
- **Notion sync** polls the CRM database for Pipeline Status = "Client" entries.
- **Scraping** runs in background threads with status polling. Same architecture as the original.
- **Creator database** aggregates creator stats across all campaigns -- no new DB tables needed.

---

## How to Deploy Changes

```bash
# Make changes, then:
cd /Users/risingtidesdev/risingtides-campaign-hub/risingtides-campaign-hub

# Push to both remotes
git push origin main    # Syncs Jake's repo
git push fork main      # Triggers Railway auto-deploy

# Frontend auto-deploys on Vercel when main is pushed to the fork
# Backend auto-deploys on Railway when main is pushed to the fork
```

---

## Files to Read First

1. `CLAUDE.md` -- Project overview, architecture, source of truth boundaries
2. `docs/plans/2026-02-22-campaign-hub-refinement-design.md` -- Full design doc with Cobrand schema, Notion CRM mapping
3. This file (`docs/handoff.md`) -- Current state and next steps
