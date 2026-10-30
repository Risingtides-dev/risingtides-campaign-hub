-- Creator payout system — Round 1 (2026-10-30)
--
-- Record of the schema change. You do NOT need to run this by hand: the same
-- statements run on every boot via db._self_heal_payout_columns(), and the
-- audit table is created by Base.metadata.create_all(). Expand-only and
-- idempotent; safe to re-run.

ALTER TABLE creator_profiles ADD COLUMN IF NOT EXISTS payout_method VARCHAR(20) DEFAULT '';
ALTER TABLE creator_profiles ADD COLUMN IF NOT EXISTS payout_destination VARCHAR(255) DEFAULT '';
ALTER TABLE creator_profiles ADD COLUMN IF NOT EXISTS payout_token VARCHAR(64) NULL;
ALTER TABLE creator_profiles ADD COLUMN IF NOT EXISTS payout_updated_at TIMESTAMP NULL;
ALTER TABLE creator_profiles ADD COLUMN IF NOT EXISTS payout_confirmed_by_creator BOOLEAN DEFAULT FALSE;
ALTER TABLE creator_profiles ADD COLUMN IF NOT EXISTS payout_change_flagged BOOLEAN DEFAULT FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS ix_creator_profiles_payout_token ON creator_profiles (payout_token);

CREATE TABLE IF NOT EXISTS creator_payout_events (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    event VARCHAR(32) NOT NULL,
    source VARCHAR(32) NOT NULL,
    old_method VARCHAR(20) DEFAULT '',
    old_destination VARCHAR(255) DEFAULT '',
    new_method VARCHAR(20) DEFAULT '',
    new_destination VARCHAR(255) DEFAULT '',
    client_ip VARCHAR(64) DEFAULT '',
    created_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_creator_payout_events_username ON creator_payout_events (username);
CREATE INDEX IF NOT EXISTS ix_creator_payout_events_created_at ON creator_payout_events (created_at);
