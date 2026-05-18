-- Drop rogue tables created by the off-main "Tides / XP" gamified-scheduler
-- experiment. None of these are in current models.py, none have ever been
-- in git history, and section 3 of inventory_rogue_data.sql confirmed
-- ZERO gamification columns were added to real (legit) tables.
--
-- The seed inserted into all of these in a single transaction at
-- 2026-05-16 01:06:45 UTC (= 2026-05-15 21:06 ET), which is AFTER the
-- 2026-05-15 20:13 backup, so the backup is unaffected.
--
-- xp_events.event_at and tide_log.day span 2025-04-30 → 2026-05-15:
-- that's backfilled / derived data computed from existing
-- internal_video_cache + matched_videos. The real tables were
-- READ ONLY, never written by this code. Dropping forfeits nothing
-- that can't be regenerated from the source-of-truth tables.
--
-- FK directions confirm safety: every FK on a rogue table points INTO
-- a real table (e.g. xp_events.video_id → internal_video_cache.id).
-- No FK points FROM a real table INTO a rogue table. So dropping
-- these is purely subtractive.

BEGIN;

-- Assert preconditions: counts should match what we already inventoried.
DO $$
DECLARE
  -- Exact COUNT(*) re-verified 2026-05-17 before drop. Yesterday's
  -- 6,910 figure for xp_events came from n_live_tup (an estimate);
  -- today's 6,834 is the actual row count, and latest event_at is
  -- still 2026-05-15 13:00:27 — i.e. no new writes, just a stat
  -- correction.
  expected jsonb := '{
    "xp_events": 6834,
    "slingshot_edges": 1043,
    "captain_leagues": 229,
    "sound_tags": 145,
    "tide_log": 361,
    "squad_members": 12,
    "squads": 1,
    "operators": 12,
    "tracker_hidden": 1
  }'::jsonb;
  tname text;
  actual bigint;
  exp bigint;
BEGIN
  FOR tname IN SELECT jsonb_object_keys(expected) LOOP
    EXECUTE format('SELECT COUNT(*) FROM %I', tname) INTO actual;
    exp := (expected ->> tname)::bigint;
    IF actual <> exp THEN
      RAISE EXCEPTION 'Row count drift in %: expected %, got %. Aborting drop. Re-run scripts/inventory_rogue_data.sql to investigate.',
        tname, exp, actual;
    END IF;
  END LOOP;
END $$;

-- Drop order: rogue tables with intra-rogue FKs last.
DROP TABLE IF EXISTS xp_events;        -- FK → internal_video_cache (real), severed by drop
DROP TABLE IF EXISTS slingshot_edges;
DROP TABLE IF EXISTS captain_leagues;
DROP TABLE IF EXISTS sound_tags;       -- FK → campaigns (real), severed by drop
DROP TABLE IF EXISTS tide_log;
DROP TABLE IF EXISTS squad_members;    -- FKs → squads, operators (rogue)
DROP TABLE IF EXISTS squads;
DROP TABLE IF EXISTS operators;

-- Separate residue: pre-rename test stub from the tracker_archives feature.
-- Single row "test-nonexistent" from 2026-04-16, schema mirrors tracker_archives.
-- Not part of the gamification incident, but cleanup-worthy in the same pass.
DROP TABLE IF EXISTS tracker_hidden;

-- Post-drop sanity: no rogue tables, expected 25 left (24 models + apscheduler_jobs).
DO $$
DECLARE
  leftover text;
BEGIN
  SELECT string_agg(table_name, ', ')
    INTO leftover
    FROM information_schema.tables
   WHERE table_schema = 'public'
     AND table_name IN (
       'tide_log','xp_events','squads','squad_members',
       'captain_leagues','slingshot_edges','operators',
       'sound_tags','tracker_hidden'
     );
  IF leftover IS NOT NULL THEN
    RAISE EXCEPTION 'Drop incomplete, still present: %', leftover;
  END IF;
END $$;

COMMIT;

\echo Done. Run \\dt to confirm the table list matches main-branch models.py.
