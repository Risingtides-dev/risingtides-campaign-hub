-- One-time migration: add `platform` column to outreach_messages.
--
-- WHY: confirm_outreach previously hardcoded platform='tiktok' when creating a
-- Creator row, losing the intended platform for Instagram outreach. The new
-- column stores the platform at the time the outreach draft is created so that
-- confirm_outreach can book the creator under the correct platform.
--
-- SAFE TO RE-RUN — ADD COLUMN IF NOT EXISTS is idempotent. Existing rows get
-- the default 'tiktok', which matches the old hardcoded behaviour, so no data
-- is corrupted by the backfill.
--
-- ORDER: deploy the app code first, then run this migration. The app reads the
-- column only after it exists; it does NOT crash on missing columns because
-- SQLAlchemy reads column values by name and falls back to the Python default.
-- (The column is nullable-equivalent via DEFAULT so INSERT without it still
-- works on the old schema briefly during the rollout window.)
--
-- RUN: psql "$DATABASE_URL" -f scripts/migrations/add_outreach_platform.sql

ALTER TABLE outreach_messages
    ADD COLUMN IF NOT EXISTS platform VARCHAR(20) NOT NULL DEFAULT 'tiktok';
