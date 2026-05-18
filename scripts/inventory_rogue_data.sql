-- Read-only inventory of suspected rogue tables/columns in prod Postgres.
-- Run via: railway connect Postgres < scripts/inventory_rogue_data.sql
-- Or:      psql "$DATABASE_PUBLIC_URL" -f scripts/inventory_rogue_data.sql

\echo === 1. Rogue tables (not in models.py, not in git history) ===
SELECT relname AS table_name, n_live_tup AS row_count
FROM pg_stat_user_tables
WHERE relname IN (
  'tide_log',
  'xp_events',
  'squads',
  'squad_members',
  'captain_leagues',
  'slingshot_edges',
  'operators',
  'sound_tags',
  'tracker_hidden'
)
ORDER BY relname;

\echo === 2. Schemas of rogue tables ===
SELECT table_name, column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
    'tide_log','xp_events','squads','squad_members',
    'captain_leagues','slingshot_edges','operators',
    'sound_tags','tracker_hidden'
  )
ORDER BY table_name, ordinal_position;

\echo === 3. Any gamification columns on EXISTING tables ===
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name NOT IN (
    'tide_log','xp_events','squads','squad_members',
    'captain_leagues','slingshot_edges','operators',
    'sound_tags','tracker_hidden'
  )
  AND (
    column_name ILIKE '%xp%'
    OR column_name ILIKE '%level%'
    OR column_name ILIKE '%point%'
    OR column_name ILIKE '%badge%'
    OR column_name ILIKE '%streak%'
    OR column_name ILIKE '%achievement%'
    OR column_name ILIKE '%squad%'
    OR column_name ILIKE '%captain%'
    OR column_name ILIKE '%league%'
    OR column_name ILIKE '%slingshot%'
    OR column_name ILIKE '%operator%'
  )
ORDER BY table_name, column_name;

\echo === 4. Foreign keys INTO existing tables (to gauge blast radius before drop) ===
SELECT
  tc.table_name AS from_table,
  kcu.column_name AS from_column,
  ccu.table_name AS to_table,
  ccu.column_name AS to_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND (
    tc.table_name IN ('tide_log','xp_events','squads','squad_members',
                      'captain_leagues','slingshot_edges','operators',
                      'sound_tags','tracker_hidden')
    OR ccu.table_name IN ('tide_log','xp_events','squads','squad_members',
                          'captain_leagues','slingshot_edges','operators',
                          'sound_tags','tracker_hidden')
  );

\echo === 5. Earliest + latest row timestamps in each rogue table (best-effort) ===
-- Best-effort: looks for a created_at column on each, skips if absent.
DO $$
DECLARE
  t text;
  has_ts boolean;
  q text;
  r record;
BEGIN
  FOR t IN SELECT unnest(ARRAY[
    'tide_log','xp_events','squads','squad_members',
    'captain_leagues','slingshot_edges','operators',
    'sound_tags','tracker_hidden'
  ])
  LOOP
    SELECT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema='public' AND table_name=t AND column_name='created_at'
    ) INTO has_ts;
    IF has_ts THEN
      q := format('SELECT %L AS t, MIN(created_at) AS first_row, MAX(created_at) AS last_row, COUNT(*) AS n FROM %I', t, t);
      FOR r IN EXECUTE q LOOP
        RAISE NOTICE 'TIMES % first=% last=% rows=%', r.t, r.first_row, r.last_row, r.n;
      END LOOP;
    ELSE
      RAISE NOTICE 'TIMES % (no created_at column)', t;
    END IF;
  END LOOP;
END $$;
