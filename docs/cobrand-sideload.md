# Cobrand Sideload

> **Status:** Design + scaffold (feature-flagged, OFF by default). Not enabled in prod.
> **Owner:** Campaign Hub
> **Related:** `campaign_manager/services/cobrand.py` (read-path), `campaign_manager/blueprints/scrape_tasks.py` (queue + "mark tracked")

## 1. Purpose

Today the team copies matched TikTok links out of the **Scrape Tasks** hub and
pastes them into co:brand's **Add Live Posts** modal, one campaign at a time.
This module ("Sideload") pushes those same per-campaign URL batches into
co:brand's API directly, then records per-URL success/failure back onto our
`MatchedVideo` rows — mirroring the existing **"Mark whole campaign tracked"**
semantics so the queue empties exactly as it would have by hand.

This is a **write path** into co:brand. It is deliberately separate from the
existing read path (`services/cobrand.py`), which only scrapes performance
fields out of public share-page `__NEXT_DATA__` and never authenticates.

## 2. ⚠️ Constraints & open items (read before enabling)

These endpoints are **undocumented, private co:brand endpoints** discovered by
observing the web app. Before this is enabled in production:

1. **ToS / account authorization — BLOCKING.** Confirm Rising Tides' co:brand
   account and contract permit *programmatic* access to these endpoints. Until
   that is confirmed in writing, the feature flag stays OFF. The existing
   read-path integration scrapes only public share pages; this write path uses
   authenticated, internal APIs and is a materially different posture. Do not
   flip the flag on the basis of "it works."
2. **`validate_live_post_url` shape is unconfirmed.** Only the request field
   (`url`) is confirmed. The response shape (and whether validation is even
   required before bulk upload) must be confirmed during implementation. The
   orchestrator treats validation as **optional** and best-effort for this
   reason (see §6).
3. **Idempotency / duplicate risk.** `bulk_upload_live_posts_for_collaboration`
   may create duplicate co:brand records if re-run with the same URLs. We do
   **not** rely on co:brand to dedupe. Our sync ledger (§5) is the source of
   truth for "already pushed"; the orchestrator filters out URLs that already
   have a non-FAILURE ledger row for the target activation, and can optionally
   reconcile against existing tasks returned by the poll endpoint.
4. **Auth specifics unconfirmed.** co:brand is an Auth0 tenant. We support both
   the M2M `client_credentials` grant and the `refresh_token` grant; which one
   our account is provisioned for must be confirmed. Token acquisition is
   isolated in `auth.py` so swapping grants is a config change, not a rewrite.

## 3. co:brand API surface (reverse-engineered)

Base host: `api.cobrand.com`. (`api-v2.cobrand.com` exists with a newer
`cobot/v1/*` namespace — **not used here**.) All four endpoints are **POST**,
JSON in / JSON out. IDs are UUIDv7-style strings.

### 3.1 Resolve activation — `POST /brand/v2/get_promotion`

The UI says "campaign," but the write API keys off **`activation_id`**, not the
`promotion_id` from the share-page URL. Resolution chain:

```
promotion_id (campaign UUID, e.g. 019e7aba-efd2-71ea-a31f-513796f752aa)
  └─ POST /brand/v2/get_promotion { promotion_id }
       └─ response.activations[].id  ==  activation_id
            e.g. 019e7abb-a201-75ff-9a75-a42e4fe6ff69
```

- **POST-only** — a GET returns `405 Method Not Allowed`.
- A promotion can have **multiple activations**. When `count == 1`, take the
  single one. Otherwise match by `activation.name` / `artist.name` against the
  hub campaign; if still ambiguous, **fail loudly** rather than guess.

Request: `{ "promotion_id": string }`
Response: `{ id, name, status, activations: [ { id, name, artist: {id,name}|null, brand } ] }`

### 3.2 Validate a URL — `POST /brand/v2/validate_live_post_url`

Drives the green-check / "N valid" counter in the modal. Called per URL.

Request: `{ "url": string }`  *(exact body/response shape TBD — see §2.2)*

Observed one transient `503` followed by success → must be retried with backoff.

### 3.3 Bulk upload (the sideload) — `POST /brand/v2/bulk_upload_live_posts_for_collaboration`

Request: `{ "activation_id": string, "urls": string[] }`
Response: `{ "group_id": string }`

**Async.** Returns a *group handle*, not the created records. Resolve via §3.4.

### 3.4 Poll status — `POST /brand/v2/list_activation_collaboration_bulk_create_groups`

Request: `{ "activation_id": string, "limit": number, "offset": number }`
(observed UI call used `limit: 99, offset: 0`)
Response: `{ count: number, items: BulkCreateGroup[] }`

Find the item whose `id === group_id` from §3.3; poll until
`pending_count == 0`. Then read per-task results.

### 3.5 Types

```ts
type UUID = string;
type TaskStatus = "PENDING" | "SUCCESS" | "FAILURE";

interface Activation { id: UUID; name: string; artist: { id: UUID; name: string } | null; brand: unknown | null; }
interface GetPromotionResponse { id: UUID; name: string; status: string; activations: Activation[]; }

interface BulkUploadRequest  { activation_id: UUID; urls: string[]; }
interface BulkUploadResponse { group_id: UUID; }

interface ListGroupsRequest  { activation_id: UUID; limit: number; offset: number; }
interface ListGroupsResponse { count: number; items: BulkCreateGroup[]; }

interface BulkCreateGroup {
  id: UUID; activation_id: UUID;
  total_count: number; pending_count: number; success_count: number; failure_count: number;
  tasks: Task[];
}
interface Task { id: UUID; collaboration_id: UUID | null; submission_id: UUID | null; url: string; status: TaskStatus; }
```

The Python module mirrors these as `@dataclass`es in
`cobrand_sideload/types.py`.

## 4. Why Python (not `.ts`)

The reverse-engineered spec was written TS-first, but this module lives in the
**Flask backend**, because:

- It needs **server-side secrets** (Auth0 client secret / refresh token) that
  must never reach the browser bundle.
- The read-path co:brand integration is already Python
  (`services/cobrand.py`).
- The "mark tracked" semantics we mirror live in the Flask backend
  (`MatchedVideo.tracked_at`, `blueprints/scrape_tasks.py`).

The React frontend's role is unchanged for now (later: a "Sideload to co:brand"
button that calls a hub endpoint). File layout mirrors the spec's
`cobrand/client.ts` + `cobrand/sync.ts` intent as a Python subpackage.

## 5. Persistence

Two additions, both self-contained new tables (no ALTER TABLE on existing
tables, so no manual migration in `db.init`):

1. **`cobrand_activation_map`** — caches the resolved
   `promotion_id → activation_id` mapping. Avoids a `get_promotion` call on
   every sync. (The existing `Campaign.cobrand_promotion_id` column supplies
   the input promotion_id.)
2. **`cobrand_sideload_tasks`** — the **sync ledger**. One row per
   `(activation_id, url)`, recording the bulk `group_id`, the resolved
   `collaboration_id` / `submission_id`, `status`, and any error. This is what
   makes the sync idempotent: a URL with an existing non-FAILURE row for an
   activation is skipped on re-run. FAILUREs are eligible for retry.

   ```
   cobrand_sideload_tasks
     id               PK
     campaign_id      FK -> campaigns.id (SET NULL)
     matched_video_id int  (soft ref; survives re-scrape)
     activation_id    str  (indexed)
     url              text
     group_id         str  (the bulk-create group handle)
     status           str  PENDING | SUCCESS | FAILURE
     collaboration_id str
     submission_id    str
     error            text
     created_at / updated_at
     UNIQUE (activation_id, url)
   ```

On a task resolving to **SUCCESS**, the orchestrator also sets
`MatchedVideo.tracked_at` / `tracked_by = "cobrand-sideload"` so the row leaves
the Scrape Tasks queue exactly as a manual "mark tracked" would. FAILURE rows
are left in the queue and surfaced for review.

Both tables register on the shared SQLAlchemy `Base`, so the test suite's
`Base.metadata.create_all` picks them up. In production the orchestrator calls
`ensure_tables(engine)` (checkfirst) at entry rather than relying on the
gunicorn-boot `create_all`.

## 6. Components

```
campaign_manager/services/cobrand_sideload/
  __init__.py     # public exports
  config.py       # env-driven config + feature flag (SideloadConfig.from_env)
  types.py        # dataclasses mirroring §3.5
  models.py       # ledger + activation-map tables, ensure_tables()
  auth.py         # Auth0TokenManager (cache, auto-refresh on 401)
  client.py       # CobrandSideloadClient: typed wrapper for the 4 endpoints
  sync.py         # orchestrator: resolve -> (validate) -> upload -> poll -> record
```

### 6.1 `auth.py` — token manager
- Acquires an access token from `https://{AUTH0_DOMAIN}/oauth/token`.
- Supports `client_credentials` (M2M; uses `AUTH0_CLIENT_ID/SECRET` +
  `AUTH0_AUDIENCE`) and `refresh_token` grants, chosen by which secrets exist.
- Caches the token in memory with an expiry skew; `invalidate()` forces a
  refresh. The client calls `invalidate()` + retries once on a `401`.

### 6.2 `client.py` — typed client
- One method per endpoint: `get_promotion`, `validate_live_post_url`,
  `bulk_upload`, `list_bulk_create_groups`.
- Centralized `_post()` with **exponential backoff** on `429` and `5xx`
  (the observed `503`), bounded retries, and a single `401` →
  token-refresh → retry.
- HTTP session is **injectable** (constructor arg) so tests mock without
  network and without a new test dependency.

### 6.3 `sync.py` — orchestrator
Per hub campaign:
1. Resolve `activation_id`: use cached `cobrand_activation_map`, else
   `get_promotion(promotion_id)` and persist the mapping (§3.1 multi-activation
   rules).
2. Build the URL batch from untracked, non-dismissed `MatchedVideo`s (reusing
   the Scrape Tasks queue's filters, incl. CAMP-42 pre-start-date exclusion).
3. **Filter against the ledger** — drop URLs already pushed (non-FAILURE) for
   this activation (idempotency).
4. *(Optional)* `validate_live_post_url` per URL; record invalids, exclude from
   upload. Skipped if validation disabled / shape unconfirmed.
5. `bulk_upload(activation_id, urls)` → `group_id`; write PENDING ledger rows.
6. Poll `list_bulk_create_groups` until the group's `pending_count == 0`
   (bounded attempts + backoff).
7. Record per-task `SUCCESS`/`FAILURE` (+ `collaboration_id`/`submission_id`)
   to the ledger; on SUCCESS set `MatchedVideo.tracked_at`.
8. Return a structured `SyncReport` (counts + per-URL outcomes).

The orchestrator entrypoint is gated by the feature flag and raises when
disabled (unless `dry_run=True`). It is **dry-run capable** (resolves the
activation and builds the batch but performs no writes to co:brand).

## 7. Config / feature flag

All via env — **never hardcoded**:

| Var | Purpose |
|---|---|
| `COBRAND_SIDELOAD_ENABLED` | Master flag. Default `false`. Orchestrator raises if off (non-dry-run). |
| `COBRAND_API_BASE` | Default `https://api.cobrand.com`. |
| `AUTH0_DOMAIN` | Auth0 tenant domain. |
| `AUTH0_AUDIENCE` | API audience for the access token. |
| `AUTH0_CLIENT_ID` / `AUTH0_CLIENT_SECRET` | M2M `client_credentials` grant. |
| `AUTH0_REFRESH_TOKEN` | Alternative `refresh_token` grant. |
| `COBRAND_SIDELOAD_VALIDATE` | Default `false` until validate shape confirmed. |
| `COBRAND_SIDELOAD_POLL_*` | Poll attempts / interval / backoff tuning. |
| `COBRAND_SIDELOAD_REQUEST_*` | Per-request retry/backoff tuning. |

## 8. Testing

`tests/backend/` (in-memory SQLite, injected fake HTTP session, no new deps):

- **Client:** backoff on `503` then success; `429` retry; `401` → refresh →
  retry; retries-exhausted raises; request/response (de)serialization.
- **Auth:** token cache hit; expiry → refetch; `client_credentials` vs
  `refresh_token` bodies; `invalidate()`; missing-creds raise.
- **Sync:** happy path; **partial-failure** group (some SUCCESS, some FAILURE)
  → ledger + `tracked_at` set only for successes; **idempotent re-run** skips
  already-pushed URLs; async poll loop terminating on `pending_count == 0`;
  multi-activation resolution; `dry_run`; disabled-flag guard.

## 9. Out of scope (first cut)
- Frontend "Sideload" button + hub API endpoint (follow-up once the flag is
  trusted in staging).
- Scheduled/cron sideload (manual/triggered only at first).
- Reconciliation job that backfills the ledger from co:brand history.
