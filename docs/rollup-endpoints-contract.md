# Rollup Endpoints — Design Contract

> **Ticket:** [RTA-22](https://linear.app/risingtides-dev/issue/RTA-22)
> **Parent:** [RTA-3](https://linear.app/risingtides-dev/issue/RTA-3) — [P2] Per-Creator Rollups + Unified Rising Tides Tracker
> **Status:** Draft → review (Eric, Sage)
> **Last updated:** 2026-05-17

## Purpose

Lock down the response shape of three rollup endpoints before three implementation tickets (RTA-23 / RTA-24 / RTA-25) build against them in parallel. The risk this doc retires: divergent payload shapes across endpoints, and the three frontend tickets (RTA-26 / RTA-27 / RTA-28) having to special-case three different `source` and `stale_since` semantics.

This is a contract, not implementation. It pins down **what each endpoint returns** and **how the four data-source tiers compose into a rollup**. Wiring details (which Postgres queries, which cache, which thread pool) are downstream and live in the implementation tickets.

## What ships with this PR

`docs/rollup-endpoints-contract.md` only. No code changes, no schema changes, no frontend types.

## Endpoints in scope

| # | Endpoint | Implementation ticket | Frontend ticket |
|---|---|---|---|
| 1 | `GET /api/creators/<username>/rollup?days=N` | RTA-23 | RTA-26 |
| 2 | `GET /api/team/<booker_slug>/rollup?days=N` | RTA-24 | RTA-27 |
| 3 | `GET /api/rt-tracker?days=N&limit=N` | RTA-25 | RTA-28 |

## Out of scope (deferred)

- **Time-series buckets** (daily / weekly aggregates over the window). RTA-22's original description floated this as a v2 stretch; it stays v2.
- **Notion-derived breakdowns** (Account Type, Page Type, ContentEngine). These ride a follow-up after P0 (RTA-1) lands clean attribution.
- **RTA-24's "booker → Notion bonus" linkage** (mapping `booker_slug` to a Notion Poster field instead of the local `internal_creator_groups` row). Address in a separate ticket; do not bend this contract to accommodate it.
- **Implementation details** — read-path, caching strategy, threading. The design decisions below set the *defaults* the implementation tickets should adopt, but actual wiring lives in RTA-23 / RTA-24 / RTA-25.

---

## Three load-bearing design decisions

These shape every endpoint below. Two are committed; one is flagged OPEN pending sign-off from Eric in PR review.

### Decision 1 — Read path: live-with-cache (committed)

Rollup endpoints read per-campaign stats by reusing `campaign_manager/services/campaign_stats.get_campaign_stats_bulk()`. They do **not** introduce a new Postgres mirror table for submission rows.

**Why:**

- The four-tier fallback (`api` → `api_cached` → `scraper_fallback` → `empty`) is already implemented and shipped in PR #71 (RTA-43). Reusing it gets source attribution and `stale_since` for free.
- The 30-minute Tides Tracker cron from RTA-42 keeps the upstream public API warm, so within any TTL window the first request pays the live-API cost and subsequent requests hit the in-process cache for free.
- The cache's `TIDES_TRACKER_CACHE_TTL_SECONDS` (default 300s, env-overridable) means a rollup request that fans out across N campaigns pays at most N live calls per worker per TTL window — and in steady state pays zero.

**Tradeoff to surface (not solve here):**

`campaign_stats._cache` is a `dict` guarded by `threading.Lock`. It is local to one gunicorn worker. With W workers, cache locality is per-worker, so worst case is `W × N` live API calls per TTL window for a rollup that touches N campaigns. Today W is small (Railway runs 1–2 gunicorn workers for this service). If we scale W, or if `/api/rt-tracker` becomes a hot polling target, the right next step is one of:

1. Move the cache to Redis (shared across workers), or
2. Materialize per-campaign submissions into a Postgres mirror written by the existing RTA-42 cron, and read from that table.

Both are non-breaking with respect to this contract — the response shape does not change. Picking between (1) and (2) is a separate ticket if it ever becomes necessary.

### Decision 2 — Per-creator unioning across campaigns

> **OPEN — defaults to Option A (iterate via `campaign_stats.get_campaign_stats_bulk`) pending Eric's sign-off in PR review.**

#### Option A — iterate via bulk (default)

A per-creator rollup resolves "which campaigns has this creator appeared in over the last N days" via a single Postgres query against `MatchedVideo`, then calls `get_campaign_stats_bulk(those_slugs)` and filters each campaign's submissions to the rows where `creator_username` matches. Per-creator aggregates are computed in Python from the filtered submission set.

**Why Option A is the implementable default:**

- Query volume is internal-tool-scale. The app today serves ~5 users; even a generous upper bound puts daily rollup requests in the dozens, not thousands.
- N is bounded. A creator typically appears in fewer than 10 campaigns per 7-day window (empirically, based on the `MatchedVideo` distribution Eric showed in Shaboozey Cowgirl tracking).
- The `SELECT DISTINCT campaign_slug FROM matched_videos WHERE creator_username = ? AND first_seen_at >= cutoff` query narrows N **before** any API fan-out, so we never iterate over the full campaign list.
- Cache hits inside the worker make the worst case 0-N live API calls — often 0 if the campaign was touched recently by another request or by the 30-minute cron.
- Option A reuses the existing pattern with zero new infrastructure. Decision 1 already commits us to the same machinery.

#### Option B — denormalized per-creator stats table

Maintain a `creator_rollup_cache` table updated by the RTA-42 cron (or a sibling cron). Endpoints read directly from that table; the per-creator rollup is a single indexed `SELECT` plus a join for the drilldown lists.

**When Option B becomes correct:**

- Leadership dashboards (e.g. `RisingTidesTracker.tsx`) auto-poll every 30 seconds.
- Label clients get read access and use it heavily.
- Either of the above produces sustained query volume that makes Option A's per-request fan-out unaffordable.

#### Why this is OPEN, not committed

Whether the per-creator endpoint lands on an auto-polling leadership dashboard is an Eric decision — he owns the UX assumptions for `/rt-tracker` and the booker dashboards. If Eric wants a 30-second refresh on those pages, Option B becomes the right call.

**Contract consequence: none.** The response shape is identical under either option. The contract below is implementable against either backing strategy. The decision affects only RTA-23's internal implementation, and migrating from A to B later does not require any client changes.

### Decision 3 — Stale-data semantics: roll up per-campaign sources (committed)

Every endpoint returns:

- Top-level `source` field summarizing the rollup as a whole (enum below).
- Top-level `stale_since` field: ISO 8601 UTC string or `null`.
- Top-level `sources_summary` object: per-tier campaign counts.
- Per-campaign `source` and `stale_since` exposed in the drilldown lists, so the frontend can render per-row badges if it chooses.

**Top-level `source` derivation:**

- `api` — every contributing campaign returned `source=api`.
- `api_cached` — at least one contributing campaign returned `source=api_cached`, none returned `scraper_fallback`.
- `scraper_fallback` — at least one contributing campaign returned `source=scraper_fallback`.
- `empty` — no contributing campaigns (creator with no matched videos in window, booker with empty roster, RT tracker with no campaigns active in window).

**Top-level `stale_since` derivation:**

- `null` if and only if top-level `source == "api"`.
- Otherwise, the **earliest** `stale_since` across all contributing campaigns whose source is not `api`.

**Why earliest, not latest:** a rollup is "as stale as its stalest input." If 5 of 7 campaigns are fresh but 2 are 6-hour cached fallbacks, the rollup is 6 hours stale, not 30 seconds fresh. Frontend badges should communicate worst-case staleness, not best-case.

---

## Shared conventions

These apply to all three endpoints unless an endpoint explicitly overrides.

### Campaign scoping (load-bearing assumption — see Open Question 4)

Rollup endpoints operate on **active campaigns only**: campaigns with `completion_status IN ("none", "booked")`. Campaigns marked `completion_status = "completed"` are excluded. This matches the precedent set by the scraper cron after commit `90723e9` (also described in `docs/scrape-tasks-redesign.md`) and the active / finished tab split shipped on 2026-03-12.

This is an **assumption** baked into the contract. The implementation tickets must filter on `completion_status`. If the column is not reliably written end-to-end (UI checkbox → backend persist), this contract still holds — but RTA-23 / RTA-24 / RTA-25 inherit a hard dependency on wiring active-tracking first. See Open Question 4.

### Input validation

- `days` query parameter, integer.
  - Default: `7`.
  - Min: `1`.
  - Max: `90`.
  - Out-of-range or unparseable values return `400` with `{"error": "days must be an integer between 1 and 90"}`.
- `username` and `booker_slug` path parameters are case-insensitive. Server normalizes via `.strip().lstrip("@").lower()` for usernames and `.strip().lower()` for booker slugs.
- Unknown `username` or `booker_slug` returns `404` with `{"error": "Creator '<username>' not found"}` or `{"error": "Booker '<booker_slug>' not found"}`.

**Deliberate divergence from existing endpoints:** the existing `/api/internal/creators/<username>/stats` and `/api/internal/groups/<id>/stats` use `days` default 30 with no max. The new rollup endpoints default to 7 with a max of 90. Rationale: rollup endpoints fan out to N campaigns per request, so unbounded `days` amplifies into proportionally large API and cache pressure. A 7-default keeps the common case fast; a 90-max gives quarterly snapshots without inviting abuse. Implementation tickets should not "fix" this divergence by aligning to the existing 30/unbounded default — the divergence is the point.

### Time window semantics

- The window is a **trailing N days** ending at request time, not a calendar week or month.
- Inclusion criterion: a post is in-window if its `posted_at` (or `upload_date` for scraper-fallback rows) falls within `[now - N days, now]`.
- Posts with no `posted_at` and no `upload_date` are excluded from time-filtered aggregates. They remain in the underlying `MatchedVideo` table; they just do not contribute to rollups.

### Source enum (mirrors `campaign_stats.py`)

```ts
type Source = "api" | "api_cached" | "scraper_fallback" | "empty";

interface SourcesSummary {
  api: number;
  api_cached: number;
  scraper_fallback: number;
  empty: number;
}
```

Semantics:

- `api` — live fetch from Tides Tracker public API succeeded.
- `api_cached` — live fetch failed; serving last-known in-process cache.
- `scraper_fallback` — no cache available; falling back to scraper-derived `matched_videos` rows.
- `empty` — no data at all (campaign has no tracker linked **and** no scraper rows).

### `stale_since` semantics

- ISO 8601 UTC string (e.g. `"2026-05-17T14:23:01+00:00"`) or `null`.
- `null` only when `source == "api"` (no fallback was needed at any layer).
- Otherwise: the earliest timestamp at which a contributing campaign's data was last considered fresh.
  - For `api_cached`, that's the cache entry's `fetched_at`.
  - For `scraper_fallback`, that's the most recent `scrape_logs.last_scrape` for that campaign.

### Error format

All errors return JSON with an `error` string field and an appropriate HTTP status. No nested error objects, no stack traces in production.

```json
{"error": "days must be an integer between 1 and 90"}
```

### JSON casing

`snake_case` for field names. Matches existing endpoints (`campaign_manager/blueprints/*.py`) and the typed `Submission` shape from `tides_tracker.py`.

### Pagination

- Endpoints 1 and 2 do **not** paginate. They return the full per-creator / per-booker dataset for the window — both are bounded by domain (one creator → <50 posts/week; one booker → <500 posts/week even on aggressive forecasts).
- Endpoint 3 (`/api/rt-tracker`) paginates its `top_creators` and `top_campaigns` lists. Default `limit=20`, max `limit=100`. Pagination is included from v1 so the API does not have to break-change when the dataset grows. Today's dataset is small enough that `limit=20` returns nearly everything, but adding pagination later breaks every client.

---

## Endpoint 1 — `GET /api/creators/<username>/rollup`

### Purpose

One creator's combined activity across internal pages (label rosters) and external campaigns (Tides Tracker / scraper) over the trailing N days.

### Inputs

- Path: `username` (case-insensitive, `@` stripped on normalize).
- Query: `days` (default 7, max 90).

### Response shape

```ts
interface CreatorRollupResponse {
  username: string;             // normalized lowercase, no leading @
  days: number;                 // echoed back after validation
  window: {
    start: string;              // ISO 8601 UTC
    end: string;                // ISO 8601 UTC (request time)
  };

  // Provenance — see "Shared conventions"
  source: Source;
  stale_since: string | null;
  sources_summary: SourcesSummary;

  // Top-level aggregates across internal + external
  totals: {
    post_count: number;
    total_views: number;
    total_likes: number;
    total_comments: number;     // 0 for scraper-fallback rows (scraper doesn't capture this)
    total_shares: number;       // 0 for scraper-fallback rows
    campaign_count: number;     // distinct external campaigns the creator appeared in
    internal_page_count: number; // distinct internal pages (warner, atlantic, …) the creator posted on
  };

  // External campaign breakdown — one row per campaign the creator appeared in
  external_campaigns: Array<{
    slug: string;
    title: string;
    artist: string;
    song: string;
    label: string;              // free-form, from campaigns.label

    // Per-campaign rollup for this creator only
    post_count: number;
    total_views: number;
    total_likes: number;
    total_comments: number;
    total_shares: number;

    // Per-campaign provenance — mirrors CampaignStatsResult
    source: Source;
    stale_since: string | null;
    fetched_at: string;         // API's fetched_at; empty string if not from API path
    tracker_id: string;         // empty string when campaign has no Tides Tracker linked

    // Top 10 posts by views for drilldown rendering.
    // Full list is not returned — frontend can hit the campaign-detail endpoint if it wants the rest.
    top_posts: Array<{
      url: string;
      views: number;
      likes: number;
      comments: number;
      shares: number;
      posted_at: string;        // ISO 8601 or empty
    }>;
  }>;

  // Internal page breakdown — one row per label group the creator posts on
  internal_pages: Array<{
    group_slug: string;         // e.g. "warner", "atlantic", "seeno"
    group_title: string;        // e.g. "Warner Pages"
    kind: "label" | "custom";   // never "booked_by" for this endpoint — labels only

    post_count: number;
    total_views: number;
    total_likes: number;

    // Top 10 posts by views from this internal page
    top_posts: Array<{
      url: string;
      song: string;
      artist: string;
      views: number;
      likes: number;
      upload_date: string;      // scraper's date format, often "YYYYMMDD" — pass through as-is
    }>;
  }>;
}
```

### Example response

```json
{
  "username": "onlyupset_",
  "days": 7,
  "window": {
    "start": "2026-05-10T17:30:00+00:00",
    "end": "2026-05-17T17:30:00+00:00"
  },
  "source": "api_cached",
  "stale_since": "2026-05-17T11:14:23+00:00",
  "sources_summary": {"api": 2, "api_cached": 1, "scraper_fallback": 0, "empty": 0},
  "totals": {
    "post_count": 12,
    "total_views": 1842305,
    "total_likes": 87421,
    "total_comments": 1893,
    "total_shares": 12044,
    "campaign_count": 3,
    "internal_page_count": 1
  },
  "external_campaigns": [
    {
      "slug": "shaboozey-cowgirl",
      "title": "Shaboozey — Cowgirl",
      "artist": "Shaboozey",
      "song": "Cowgirl",
      "label": "Empire",
      "post_count": 7,
      "total_views": 1240118,
      "total_likes": 62445,
      "total_comments": 1422,
      "total_shares": 9213,
      "source": "api",
      "stale_since": null,
      "fetched_at": "2026-05-17T17:29:55+00:00",
      "tracker_id": "8f3a-...-2c1d",
      "top_posts": [
        {
          "url": "https://www.tiktok.com/@onlyupset_/video/7484...",
          "views": 421300,
          "likes": 22011,
          "comments": 401,
          "shares": 3401,
          "posted_at": "2026-05-15T14:02:18+00:00"
        }
      ]
    }
  ],
  "internal_pages": [
    {
      "group_slug": "warner",
      "group_title": "Warner Pages",
      "kind": "label",
      "post_count": 3,
      "total_views": 122044,
      "total_likes": 8400,
      "top_posts": [
        {
          "url": "https://www.tiktok.com/@warnerpage1/video/7485...",
          "song": "Cowgirl",
          "artist": "Shaboozey",
          "views": 88200,
          "likes": 5421,
          "upload_date": "20260514"
        }
      ]
    }
  ]
}
```

### Edge cases

- **Creator with zero activity in window** → 200 OK, `source: "empty"`, `totals.post_count: 0`, both arrays empty.
- **Creator only on internal pages, never on external campaigns** → `external_campaigns: []`, `totals.campaign_count: 0`.
- **Creator only on external campaigns, never on internal pages** → `internal_pages: []`, `totals.internal_page_count: 0`.
- **Unknown creator** (no rows in any table for that username) → 404. Returning a known-but-empty shape would be misleading — the frontend should be able to distinguish "no posts this week" from "you typoed the username."

---

## Endpoint 2 — `GET /api/team/<booker_slug>/rollup`

### Purpose

One booker's roster activity. Aggregates Endpoint 1's data across every creator in the booker's `booked_by` group.

### Inputs

- Path: `booker_slug` (case-insensitive). One of `jake_balik`, `john_smathers`, `eric_cromartie`, `sam_hudgens`, etc. — sourced from `internal_creator_groups` where `kind = 'booked_by'`.
- Query: `days` (default 7, max 90).

### Response shape

```ts
interface TeamRollupResponse {
  booker_slug: string;
  booker_title: string;         // e.g. "Eric Cromartie", "John Smathers"
  days: number;
  window: { start: string; end: string };

  source: Source;
  stale_since: string | null;
  sources_summary: SourcesSummary;

  totals: {
    creator_count: number;            // size of booker's roster (regardless of activity)
    active_creator_count: number;     // creators with >=1 post in window
    post_count: number;
    total_views: number;
    total_likes: number;
    total_comments: number;
    total_shares: number;
    external_campaign_count: number;  // distinct external campaigns any roster creator touched
    internal_page_count: number;      // distinct internal pages any roster creator posted on
  };

  // Roster — one row per creator in the booker's group, including zero-activity creators
  creators: Array<{
    username: string;
    post_count: number;
    total_views: number;
    total_likes: number;
    total_comments: number;
    total_shares: number;
    external_campaign_count: number;
    internal_page_count: number;

    // Provenance for this creator's contribution
    source: Source;
    stale_since: string | null;
  }>;

  // External campaigns the roster touched, aggregated across all roster creators
  external_campaigns: Array<{
    slug: string;
    title: string;
    artist: string;
    song: string;
    label: string;
    roster_post_count: number;        // posts by roster creators in this campaign
    roster_creator_count: number;     // distinct roster creators in this campaign
    total_views: number;
    total_likes: number;
    total_comments: number;
    total_shares: number;
    source: Source;
    stale_since: string | null;
  }>;

  // Internal pages the roster posted on, aggregated
  internal_pages: Array<{
    group_slug: string;
    group_title: string;
    kind: "label" | "custom";
    roster_post_count: number;
    roster_creator_count: number;
    total_views: number;
    total_likes: number;
  }>;
}
```

### Edge cases

- **Booker with empty roster** → 200 OK, `creators: []`, `source: "empty"`, all totals zero.
- **Booker who exists in `internal_creator_groups` but whose roster has zero activity in window** → 200 OK, `creators: [...]` (zero-activity rows still included with all-zero stats), `source: "empty"`, totals zero.
- **Unknown booker** → 404.
- **Creator membership:** derived from `internal_creator_group_members` where the group has `kind = 'booked_by'`. Per RTA-5 and RTA-9, label groups (`kind = 'label'`) are not part of the booker roster — they're an orthogonal axis. A creator can simultaneously belong to one booker group and one label group.

### Deferred from this contract

The "booker → Notion" linkage piece in RTA-24's description (booker bonus mapping to Notion's Poster field) is **out of scope here**. It would change the *source* of the `booker_slug → roster` mapping but not the response shape. Treat as a future ticket; flag in the RTA-24 PR.

---

## Endpoint 3 — `GET /api/rt-tracker`

### Purpose

The unified Rising Tides view. Sums across every booker.

### Inputs

- Query: `days` (default 7, max 90).
- Query: `limit` (default 20, max 100) — applies to `top_creators` and `top_campaigns`.

### Response shape

```ts
interface RtTrackerResponse {
  days: number;
  limit: number;
  window: { start: string; end: string };

  source: Source;
  stale_since: string | null;
  sources_summary: SourcesSummary;

  totals: {
    total_views: number;
    total_likes: number;
    total_comments: number;
    total_shares: number;
    post_count: number;
    creator_count: number;          // distinct creators with >=1 post in window
    external_campaign_count: number; // distinct active external campaigns in window
    booker_count: number;           // distinct bookers with >=1 active roster creator
    internal_page_count: number;
  };

  // Per-booker subtotals — one row per booker with any activity in window
  per_booker: Array<{
    booker_slug: string;
    booker_title: string;
    creator_count: number;          // active roster creators (>=1 post in window)
    post_count: number;
    total_views: number;
    total_likes: number;
    source: Source;
    stale_since: string | null;
  }>;

  // Per-label subtotals — one row per label appearing on any active external campaign
  per_label: Array<{
    label: string;                  // free-form, from campaigns.label
    campaign_count: number;
    post_count: number;
    total_views: number;
    total_likes: number;
  }>;

  // Top N creators by views (default 20, max 100)
  top_creators: Array<{
    username: string;
    booker_slug: string | null;     // null if not in any booked_by group
    post_count: number;
    total_views: number;
    total_likes: number;
  }>;

  // Top N campaigns by views (default 20, max 100)
  top_campaigns: Array<{
    slug: string;
    title: string;
    artist: string;
    song: string;
    label: string;
    post_count: number;
    total_views: number;
    total_likes: number;
    source: Source;
    stale_since: string | null;
  }>;
}
```

### Edge cases

- **Zero campaigns active in window** → 200 OK, every list empty, all totals zero, `source: "empty"`.
- **All bookers with zero roster activity** → 200 OK, `per_booker: []`, `top_creators: []`, all totals zero.
- **`limit` larger than available rows** → returns all available; no padding.
- **`limit` out of range** → 400 with `{"error": "limit must be an integer between 1 and 100"}`.

### Note on pagination

Today's dataset is small (~15 active campaigns, ~40 creators across all rosters); `limit=20` returns nearly everything. The decision to include `limit` from v1 is forward-looking — if the dataset grows, the API does not have to break-change. Frontend (RTA-28) should plumb a "show more" interaction even if it never fires in practice for the foreseeable future.

---

## Acceptance criteria for the implementation tickets

When RTA-23 / RTA-24 / RTA-25 PRs land, each should:

- Return the response shape exactly as specified above. Missing fields are a contract violation. Extra fields are tolerated only if they're additive, prefixed with `_` (e.g. internal debug fields), and Eric + Smaths sign off.
- Surface `source` and `stale_since` at the top level **and** per drilldown row.
- Validate `days` (and `limit`, for RTA-25) per the rules in **Shared conventions**. Out-of-range → 400; unknown path param → 404.
- Reuse `campaign_stats.get_campaign_stats_bulk()` for per-campaign reads (Decision 1).
- Pass an integration smoke test that hits each endpoint with `days=7` and asserts:
  - `source` is one of the four enum values
  - `stale_since` is `null` iff `source == "api"`
  - `sources_summary` sums to `external_campaign_count` (Endpoints 1 and 2) or to the number of active campaigns (Endpoint 3)

---

## Open questions for review

1. **Decision 2 (per-creator unioning):** confirm Option A is acceptable for v1, or flag Option B if leadership-dashboard auto-polling is a near-term ask. **Owner: Eric.**
2. **`booker_title` source:** this contract assumes `internal_creator_groups.title` (e.g. "Eric Cromartie") is the human-readable display. If we want this driven by Notion's Poster field, that's the RTA-24 Notion-linkage piece — surface it now or later? **Owner: Smaths.**
3. **`per_label.label` is free-form text from `campaigns.label`.** If we want a canonical label dimension (e.g. always `"Warner"` not `"warner"` / `"Warner Music"` / `"WMG"`), that's a data-cleanup ticket. Flagging here so RTA-25 doesn't accidentally introduce a normalizer that masks the underlying inconsistency. **Owner: Eric.**
4. **Active-campaign filtering — assumption pending confirmation.** This contract assumes rollup endpoints filter to `Campaign.completion_status IN ("none", "booked")`. The active / finished tab UI shipped on 2026-03-12 writes `completion_status` per CLAUDE.md's "Recent Changes" note, and the scraper cron has been filtering on it since commit `90723e9`. But: confirm the UI's checkbox toggle actually persists to the backend column for every code path that touches campaign state, not just the tab view. **Owner: Smaths (recon underway).**

   If the field isn't wired end-to-end, this becomes a hard blocker for RTA-23 / RTA-24 / RTA-25 — wiring active-tracking properly must ship first. The contract still holds; only the dependency chain changes.

   **Bandwidth implication (out of scope for this contract, flagged for follow-up):** operating on truly-active campaigns is also a Decodo / Tides Tracker API quota optimization — the scraper and the cache currently fan out to all 148 campaigns regardless of activity. Filtering at the rollup layer is the cheap first move; filtering at the cron layer (RTA-42's `pull_all_trackers`) is the next.

---

## Sign-off

- [ ] Eric — Decisions 1, 2 (default vs Option B), 3
- [ ] Sage — endpoint shapes review
- [ ] Smaths — author

