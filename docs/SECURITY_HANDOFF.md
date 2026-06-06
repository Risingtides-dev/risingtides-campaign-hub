# Security Handoff — Campaign Hub (2026-06-06)

> One-page consolidation of discovery sweep #6's security findings, what's
> already fixed, and the decisions waiting on John. Tracked in **CAMP-96**
> (auth, Urgent), **CAMP-97** (share-token), **CAMP-93** (scraper cost).

## TL;DR — the one question that determines everything

**Is this app behind any network-level access control** (Cloudflare Access,
Railway private networking, a VPN/IP allowlist)?

- **If YES** → the "no auth" finding drops from critical to a hardening nice-to-have. Most of CAMP-96 relaxes.
- **If NO** (what the code implies — public Railway deploy, gunicorn `--bind 0.0.0.0`, public `/health`) → the API is wide open to anyone with the URL, and the umbrella auth gate (PR #185) should be enabled soon.

The code can't see your infra, so this is yours to confirm. Everything below assumes the worst case (no infra protection) until you say otherwise.

## What's already FIXED + shipped (safe, autonomous, no auth-model decision needed)

These were the *standalone-dangerous* endpoints — each patched narrowly without touching the broader auth model:

| Fix | What it closed | PR |
|---|---|---|
| **notion_sync delete-floor** (CAMP-94) | A truncated Notion fetch could mass-delete the attribution mirror + group memberships. Now aborts on truncation + refuses to delete >50% of rows. | #186 |
| **/api/cron/diag gate** | Fired a live scrape + proxy fetch on every unauthenticated GET (cost DoS) and leaked proxy stderr. Now the live tests + stderr need `?run=1`; cheap diagnostics stay always-on. | #187 |
| **/api/migrate/campaign-full overwrite guard** | Unauthenticated `save_campaign` UPSERT — anyone could silently overwrite any campaign's budget/creators by slug. Now 409s unless `?overwrite=1`. | #188 |

## STAGED but NOT enabled — the umbrella fix (needs John)

**PR #185 — app-wide API auth gate. Ships INERT.**

- `campaign_manager/auth.py` + a `before_request` hook. **Total no-op unless `APP_API_KEY` is set** in the env — merging/deploying it changes nothing, so it can't lock anyone out.
- When `APP_API_KEY` IS set: every `/api/*` request needs the key via `X-API-Key` header (or `?api_key=`), constant-time compared. Exempt: `/health`, the SPA + non-`/api/` static, and `/api/share/` (the intentional public surface — CAMP-97).
- Verified both states (OFF: no change; ON: 401 without key, 200 with, exemptions correct).

**This single gate neutralizes ALL the remaining exposures below at once** — which is why they were deliberately NOT patched one-by-one (per-endpoint patches wouldn't even cover the IDOR on the detail endpoint).

### Remaining exposures the gate covers (do NOT need individual patches)
- **IDOR — `GET /api/campaign/<slug>`**: returns budget, every creator's `total_rate`, `per_post_rate`, **`paypal_email`**, paid status. Slug is the only "credential" and slugs are guessable (artist-song). Anyone can harvest creator PayPal emails + negotiated rates across the whole campaign book. *(The dedicated client report `campaign_report.py` correctly strips all this — the problem is the full-detail endpoint being reachable.)*
- **`POST /api/cron/trigger` / `/api/cron/toggle`**: unauthenticated — launch unbounded scrapes (cost/DoS) or disable the daily scheduler.
- **`POST /api/webhooks/notion`**: unauthenticated campaign creation (insert-only, 409s on dup, but anyone can inject).
- **`GET /api/campaign/<slug>/cobrand/raw`**: unauthenticated debug hatch dumping the full Cobrand promotion object.

## To ENABLE auth (the coordinated rollout — John drives, with John present)

These MUST ship together, with John watching the deploy to confirm access:

1. **Decide the model.** Shared `APP_API_KEY` is what's staged (simplest). SSO is a bigger build if you want per-user auth.
2. **Merge PR #185** (it's inert until step 3).
3. **Set `APP_API_KEY`** on Railway (a long random string).
4. **Wire the frontend** to send `X-API-Key` on every API call (one change in `frontend/src/lib/api.ts`'s `request()` — reads the key from a build-time env / a login prompt). This and step 3 must deploy together.
5. **Confirm** you can still load the app + all data after enabling.
6. **CAMP-97**: implement the secure share path (`/api/share/<token>` → `build_report()`, financials stripped) so "Share with Client" works through the one carved-out public surface.

## Verified NOT vulnerable (don't chase these)
- **Slack webhook signature verification IS real** — slack-bolt's `SlackRequestHandler` checks the signature + timestamp; event forgery isn't possible.
- **TidesTracker SERVICE KEY** is never logged, echoed in an error, or returned in JSON — only sent as the `x-service-key` request header.
- **The client report (`campaign_report.py`)** correctly excludes budget/rates/payment.

## Other open decisions (not security)
- **CAMP-93** — the internal scrape enriches each creator's *entire* history via per-video proxy fetches (the RTA-44 docstrings claim this was removed). It's a cost-vs-matching-quality tradeoff on the live scraper — your call on whether to bound the lookback or keep it.
