-- Additive quote snapshot. Existing rows intentionally remain NULL: today's
-- editable network roster cannot prove which platform a historical quote used.
-- Reconcile legacy unaccepted quotes before confirmation; do not guess a backfill.
ALTER TABLE outreach_messages ADD COLUMN IF NOT EXISTS platform VARCHAR(20);
