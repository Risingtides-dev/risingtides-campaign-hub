-- One-time backfill of the tides_tracker_stats_cache aggregate columns
-- (agg_views/likes/comments/shares/post_count) from the existing
-- submissions_json blobs.
--
-- Why: _cache_set writes aggregates on every new cache write, but the
-- tides_tracker_pull cron only refreshes ACTIVE campaigns' trackers —
-- finished campaigns' rows would stay NULL (legacy) forever, and the
-- campaigns list would keep parsing their blobs per request. Run once
-- AFTER the deploy that adds the columns (db._sync_columns adds them on
-- boot). Idempotent; safe to re-run.
UPDATE tides_tracker_stats_cache t
SET
  agg_views = agg.views,
  agg_likes = agg.likes,
  agg_comments = agg.comments,
  agg_shares = agg.shares,
  agg_post_count = agg.post_count
FROM (
  SELECT
    tracker_id,
    COALESCE(SUM(COALESCE((e->>'views')::bigint, 0)), 0)    AS views,
    COALESCE(SUM(COALESCE((e->>'likes')::bigint, 0)), 0)    AS likes,
    COALESCE(SUM(COALESCE((e->>'comments')::bigint, 0)), 0) AS comments,
    COALESCE(SUM(COALESCE((e->>'shares')::bigint, 0)), 0)   AS shares,
    COUNT(e)                                                AS post_count
  FROM tides_tracker_stats_cache
  LEFT JOIN LATERAL jsonb_array_elements(submissions_json) AS e ON true
  GROUP BY tracker_id
) agg
WHERE agg.tracker_id = t.tracker_id
  AND t.agg_post_count IS NULL;
