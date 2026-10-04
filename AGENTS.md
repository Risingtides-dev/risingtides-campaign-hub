# Campaign Hub

## Purpose

Campaign CRM integration, campaign delivery reporting, and creator operations.

## Ownership

- `campaign_manager/` owns the API and scheduled backend work.
- `frontend/` owns the web interface.
- `tests/backend/` owns backend verification.

## Local Contracts

- Public `/health` reports `db_target` using the same SQLAlchemy URL grammar as database initialization, exposing only the scheme and host. Credentials, port, path and query stay private; absent URLs return an empty target; unparseable URLs or URLs containing multiple raw `@` separators return `set` because the parsed host may contain a password fragment. This conservative diagnostic fallback also applies when the extra `@` is in a query; it never changes the database connection.
- `/health` reports `schema_repair: "ok"` after the required PostgreSQL `campaigns.completion_status` repair succeeds. A failed repair returns `ok: false` with HTTP 503; it does not expose raw database errors, and the campaign scheduler must not start until repair succeeds. Health probes retry repair with bounded exponential backoff and a per-process nonblocking guard, so transient boot-lock contention can recover without a process restart or probe stampede. During expired schema verification, concurrent probes fail closed until reconciliation finishes. When readiness recovers, the health path reconciles scheduler startup under the existing process-wide file lock. Successful state is checked read-only every 30 seconds; detected column/default/NULL drift triggers the migration again. The narrow versioned migration backfills NULL values to `none` and restores the database default so active-campaign exclusions retain existing rows.

- CRM `Content Niche Targets` supplies the declared campaign niches consumed by ShipStream's D1 playlist flow.
- Campaign reads request a background refresh at most every 15 minutes, independent of the scraping scheduler. The refresh reads exact stored Notion page links for existing active campaigns, updates only `content_types` and `internal_captions`, and neither creates campaigns nor sends notifications.
- An unreadable or missing CRM property preserves stored categories; an explicitly empty multi-select clears them.
- CRM `Internal Captions` holds a campaign's text-on-screen lines, typed by staff or submitted on an intake form. The same refresh keeps each active campaign's copy current, verbatim, under the same preserve-or-clear rule; a value too long to read whole counts as unreadable, never as a shorter list. Saving a whole campaign never changes its captions once it exists.
- `GET /api/campaigns/captions` lists every active campaign whose CRM captions have been read, with its sound, for the posting control plane. Finished campaigns and campaigns never read are left out, and the campaign list itself carries no caption text.
- `PUT /api/campaign/<slug>/internal-captions` saves one campaign's captions from the posting control plane, CRM page first, stored here only once the CRM took it. The caller sends `expected`, the value it last saw; a different stored value answers 409 with the current one. When `HUB_WRITE_KEY` is set the `X-Hub-Write-Key` header must match.
- Legacy `POST /api/campaign/<slug>/edit` requires `expected_official_sound` when changing `official_sound` to an HTTP(S) URL. URL identity uses normalized HTTP(S) scheme, host, default port, path, query, and no fragment; duplicate assignments return 409. Database writes use the campaign-sound transaction advisory lock and recheck the expected value before updating. Non-URL sound-ID edits retain their existing behavior. `PUT /api/campaign/<slug>/sound-link` uses the same CAS, canonical uniqueness check, and PostgreSQL advisory lock; it updates `official_sound` and `sound_id` atomically, deriving the ID from TikTok music URLs and clearing stale IDs for other links. Both URL-changing endpoints refuse file-backed writes with 503 because scan-then-write cannot enforce global uniqueness across workers.

## Work Guidance

## Verification

- Backend checks run with `pytest tests/backend`; `.github/workflows/backend-tests.yml` runs the same suite on pull requests and pushes to `main`.
- Run `pytest -q tests/backend/test_health_db_target.py tests/backend/test_smoke.py` for synthetic credential redaction and existing app health contracts; only test-owned SQLite fixtures are used.
- Run `TEST_POSTGRES_DATABASE_URL=... pytest -q tests/backend/test_completion_status_schema.py` against a disposable PostgreSQL database to verify the populated-table repair and readiness failure path. The fixture creates and drops an isolated schema.

## Child devlog Index
