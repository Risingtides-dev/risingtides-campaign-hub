"""Database access layer for the Warner Campaign Manager.

Replaces all JSON/CSV file I/O with Postgres queries via SQLAlchemy.
Falls back to file-based storage if DATABASE_URL is not set.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import Session, selectinload, sessionmaker

from campaign_manager.models import (
    Base, Campaign, Creator, MatchedVideo, ScrapeLog,
    InboxItem, PaypalMemory, InternalCreator, InternalVideoCache,
    InternalScrapeResult, CronLog, NetworkCreator, OutreachMessage,
    InternalCreatorGroup, InternalCreatorGroupMember,
    InternalVideoGroupAttribution,
    TrackerGroup, TrackerGroupAssignment, TrackerName, TrackerCampaignLink,
    TrackerArchive,
    ManyChatMessage,
    NotionMasterPage, NotionSyncLog,
    TidesTrackerSyncLog,
)

_engine = None
_SessionLocal = None


def _sync_columns():
    """Add any model column missing from its live table (idempotent, additive).

    Guards the class of failure where a model column has no ALTER migration, or
    where a column is dropped out-of-band: the next boot re-adds it instead of
    every SELECT 500ing. New columns are added nullable / with the model default;
    existing columns and data are never touched. Postgres-only; per-column
    failures are swallowed so one bad column can't abort startup.
    """
    from sqlalchemy import inspect, text
    insp = inspect(_engine)
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all already made it with the full current schema
        have = {col["name"] for col in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = col.type.compile(_engine.dialect)
            try:
                with _SessionLocal() as s:
                    s.execute(text(
                        f'ALTER TABLE {table.name} '
                        f'ADD COLUMN IF NOT EXISTS "{col.name}" {ddl}'
                    ))
                    s.commit()
            except Exception:
                pass


def init(database_url: Optional[str] = None):
    """Initialize the database connection and create tables."""
    global _engine, _SessionLocal

    url = database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        return False

    # Railway uses postgres:// but SQLAlchemy 2.x needs postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)
    _SessionLocal = sessionmaker(bind=_engine)

    # Create all tables.
    #
    # `create_all` does a reflection pass and only issues CREATE for tables
    # that look missing — but gunicorn boots 4 workers in parallel, all of
    # which call into here, and the reflection / CREATE window is racy.
    # Two workers can both observe a new table as missing and both try to
    # CREATE it; the loser crashes with `DuplicateTable` /
    # `pg_class_relname_nsp_index` and gunicorn marks the worker dead.
    #
    # We swallow that specific failure mode so worker N+1 boots fine when
    # worker N already won the create race. Anything else still raises
    # so a genuinely broken migration surfaces loudly.
    try:
        Base.metadata.create_all(_engine)
    except Exception as exc:
        msg = str(exc)
        if "already exists" in msg or "pg_class_relname_nsp_index" in msg:
            pass
        else:
            raise

    # Reconcile columns. create_all() creates missing *tables* but NEVER adds a
    # new column to a table that already exists — and it can't restore a column
    # that was dropped out-of-band. Any model column the live table lacks makes
    # every SELECT of that model throw UndefinedColumn -> 500 (this is what took
    # /api/campaigns down when `campaigns.status` went missing). Auto-add any
    # model column the table is missing so the schema self-heals on boot,
    # instead of relying on the hand-maintained ALTER blocks below.
    # NOTE: the dead `status` column is dropped as a DELIBERATE one-time
    # migration AFTER this code deploys (so no running code references it),
    # NOT here. Auto-running schema DROPs on every db.init() broke prod once
    # already — see scripts/migrations/drop_campaigns_status.sql.
    _sync_columns()

    # Add completion_status column if missing (create_all won't add columns to existing tables)
    try:
        with _SessionLocal() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS completion_status VARCHAR(20) DEFAULT 'none'"
                )
            )
            s.commit()
    except Exception:
        pass

    # Add tracker columns if missing
    try:
        with _SessionLocal() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS tracker_campaign_id VARCHAR(100)"
                )
            )
            s.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS tracker_url TEXT DEFAULT ''"
                )
            )
            s.commit()
    except Exception:
        pass

    # Fix: null out empty notion_page_id values so unique constraint works
    try:
        with _SessionLocal() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "UPDATE campaigns SET notion_page_id = NULL WHERE notion_page_id = ''"
                )
            )
            s.commit()
    except Exception:
        pass

    # One-time cleanup: delete pre-EST-fix scrape results (saved as UTC)
    try:
        with _SessionLocal() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "DELETE FROM internal_scrape_results "
                    "WHERE scraped_at < '2026-02-25'"
                )
            )
            s.commit()
    except Exception:
        pass

    # Add niches column to creators if missing
    try:
        with _SessionLocal() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE creators ADD COLUMN IF NOT EXISTS niches JSONB DEFAULT '[]'::jsonb"
                )
            )
            s.commit()
    except Exception:
        pass

    # Add display_name + niche to internal_creators
    try:
        with _SessionLocal() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE internal_creators ADD COLUMN IF NOT EXISTS display_name VARCHAR(255) DEFAULT ''"
                )
            )
            s.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE internal_creators ADD COLUMN IF NOT EXISTS niche VARCHAR(100) DEFAULT ''"
                )
            )
            s.commit()
    except Exception:
        pass

    # Add TikTok scraper label fields to campaigns
    try:
        with _SessionLocal() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS tt_artist_label VARCHAR(255) DEFAULT ''"
                )
            )
            s.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS tt_track_name VARCHAR(255) DEFAULT ''"
                )
            )
            s.commit()
    except Exception:
        pass

    # Add match_strategy field to campaigns. "fuzzy" preserves existing
    # behavior; "strict" disables fuzzy fallback for original sound campaigns
    # where multiple campaigns share an artist (Stella Lefty I-Know-I-Know
    # vs Boston) — fuzzy fallback was causing cross-campaign false positives.
    try:
        with _SessionLocal() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS match_strategy VARCHAR(20) DEFAULT 'fuzzy'"
                )
            )
            s.commit()
    except Exception:
        pass

    # Add tracking-workflow + match metadata to matched_videos.
    # - first_seen_at: when the cron first matched this video (used by
    #   the Scrape Tasks tab to show "new since" filtering)
    # - tracked_at: set when a human marks "I copied this into Cobrand"
    # - tracked_by: optional audit trail
    # - match_strategy: how the match was found (sound_id|fuzzy|internal_creator)
    try:
        with _SessionLocal() as s:
            sa = __import__("sqlalchemy")
            s.execute(sa.text(
                "ALTER TABLE matched_videos "
                "ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP NULL"
            ))
            s.execute(sa.text(
                "ALTER TABLE matched_videos "
                "ADD COLUMN IF NOT EXISTS tracked_at TIMESTAMP NULL"
            ))
            s.execute(sa.text(
                "ALTER TABLE matched_videos "
                "ADD COLUMN IF NOT EXISTS tracked_by VARCHAR(100) DEFAULT ''"
            ))
            s.execute(sa.text(
                "ALTER TABLE matched_videos "
                "ADD COLUMN IF NOT EXISTS match_strategy VARCHAR(50) DEFAULT ''"
            ))
            s.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS idx_matched_videos_tracked_at "
                "ON matched_videos (tracked_at)"
            ))

            # Soft-dismiss columns for false-positive matches (issue #32).
            # Dismissed rows are hidden from the tracking queue and excluded
            # from campaign view/engagement totals.
            s.execute(sa.text(
                "ALTER TABLE matched_videos "
                "ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMP NULL"
            ))
            s.execute(sa.text(
                "ALTER TABLE matched_videos "
                "ADD COLUMN IF NOT EXISTS dismissed_by VARCHAR(100) DEFAULT ''"
            ))
            s.execute(sa.text(
                "ALTER TABLE matched_videos "
                "ADD COLUMN IF NOT EXISTS dismissed_reason TEXT DEFAULT ''"
            ))
            s.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS idx_matched_videos_dismissed_at "
                "ON matched_videos (dismissed_at)"
            ))

            # Explicit cluster -> TidesTracker link (CAMP cluster work).
            # A cluster of pages maps 1:1 to a Cobrand sheet / tracker UUID.
            s.execute(sa.text(
                "ALTER TABLE internal_creator_groups "
                "ADD COLUMN IF NOT EXISTS tracker_id VARCHAR(64) NULL"
            ))
            # Enforce the 1:1 invariant in the schema: no two clusters may pin
            # the same tracker. Partial so the many NULL (unpinned) groups are
            # exempt -- only set tracker_ids must be unique.
            s.execute(sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_internal_groups_tracker_id "
                "ON internal_creator_groups (tracker_id) WHERE tracker_id IS NOT NULL"
            ))

            # Backfill first_seen_at for any pre-existing row that doesn't
            # have one yet. Idempotent because the WHERE clause only catches
            # NULLs, and once stamped a row never goes back.
            s.execute(sa.text(
                "UPDATE matched_videos "
                "SET first_seen_at = NOW() "
                "WHERE first_seen_at IS NULL"
            ))
            # NOTE: the previous boot-time auto-track UPDATE was removed.
            # It marked any untracked row older than 5 minutes as tracked
            # on EVERY boot — which nuked the Scrape Tasks queue every
            # deploy. The original "fresh deploy starts with a clean
            # queue" goal was only relevant the day the feature shipped;
            # leaving it in turned every redeploy into a queue-wipe.
            s.commit()
    except Exception:
        pass

    # manychat_messages table is created by Base.metadata.create_all above.
    # No migration block needed -- it's additive only.

    # Notion mirror tables (RTA-6, RTA-7). create_all above handles fresh
    # creation; the explicit CREATE TABLE IF NOT EXISTS + CREATE INDEX IF
    # NOT EXISTS below pin the exact schema (verbatim from the tickets)
    # so the deploy is idempotent even if the SQLAlchemy DDL drifts.
    # Password is deliberately NOT mirrored from Notion (security).
    try:
        with _SessionLocal() as s:
            sa = __import__("sqlalchemy")
            s.execute(sa.text(
                "CREATE TABLE IF NOT EXISTS notion_master_pages ("
                "  notion_page_id        UUID PRIMARY KEY,"
                "  account_username      TEXT NOT NULL,"
                "  notion_group          TEXT,"
                "  notion_subgroup       TEXT,"
                "  poster                TEXT,"
                "  account_type          TEXT,"
                "  page_type             TEXT,"
                "  content_engine        TEXT,"
                "  pipeline              TEXT,"
                "  status                TEXT,"
                "  page_url              TEXT,"
                "  email                 TEXT,"
                "  notes                 TEXT,"
                "  go_live_date          DATE,"
                "  is_complete           BOOLEAN DEFAULT FALSE,"
                "  notion_last_edited_at TIMESTAMPTZ,"
                "  synced_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()"
                ")"
            ))
            s.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS idx_notion_master_account_username "
                "ON notion_master_pages (LOWER(account_username))"
            ))
            s.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS idx_notion_master_group "
                "ON notion_master_pages (notion_group)"
            ))
            s.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS idx_notion_master_poster "
                "ON notion_master_pages (poster)"
            ))

            s.execute(sa.text(
                "CREATE TABLE IF NOT EXISTS notion_sync_log ("
                "  id                  BIGSERIAL PRIMARY KEY,"
                "  started_at          TIMESTAMPTZ NOT NULL,"
                "  finished_at         TIMESTAMPTZ,"
                "  sync_type           TEXT NOT NULL,"
                "  pages_fetched       INTEGER,"
                "  pages_added         INTEGER,"
                "  pages_updated       INTEGER,"
                "  pages_deleted       INTEGER,"
                "  memberships_added   INTEGER,"
                "  memberships_removed INTEGER,"
                "  errors              JSONB,"
                "  triggered_by        TEXT"
                ")"
            ))
            s.commit()
    except Exception:
        pass

    # RTA-13: durable point-in-time attribution of scraped videos to groups.
    # Snapshots the group membership of an account AT scrape time so that
    # re-tagging an account later does not silently rewrite historical
    # attribution.
    try:
        with _SessionLocal() as s:
            sa = __import__("sqlalchemy")
            s.execute(sa.text(
                "CREATE TABLE IF NOT EXISTS internal_video_group_attribution ("
                "  id          BIGSERIAL PRIMARY KEY,"
                "  video_id    BIGINT NOT NULL REFERENCES internal_video_cache(id) ON DELETE CASCADE,"
                "  group_id    BIGINT NOT NULL REFERENCES internal_creator_groups(id),"
                "  resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                "  CONSTRAINT uq_ivga_video_group UNIQUE (video_id, group_id)"
                ")"
            ))
            s.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS idx_ivga_video "
                "ON internal_video_group_attribution (video_id)"
            ))
            s.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS idx_ivga_group "
                "ON internal_video_group_attribution (group_id)"
            ))
            s.commit()
    except Exception:
        pass

    # Index the hot matched_videos columns the creator-aggregation and
    # sound-matcher paths group by (account, extracted_sound_id). The model
    # marks them index=True so fresh DBs get them via create_all; this adds
    # them to the existing prod table. Not CONCURRENTLY here — runs inside the
    # app's init transaction; for a huge table apply CONCURRENTLY out-of-band.
    try:
        import sqlalchemy as sa
        with _SessionLocal() as s:
            s.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS ix_matched_videos_account "
                "ON matched_videos (account)"
            ))
            s.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS ix_matched_videos_extracted_sound_id "
                "ON matched_videos (extracted_sound_id)"
            ))
            s.commit()
    except Exception:
        pass

    # Backfill stale tracker_url hosts (CAMP-41 / View-Tracker bug). Some
    # campaigns stored tracker_url with the old frontend-tidestracker.vercel.app
    # host, which pins to stale deploys — "View Tracker" sent users to a dead
    # page. Rewrite to the canonical risingtides-tracker.com, preserving the
    # UUID path. Idempotent: the WHERE clause matches nothing once fixed.
    try:
        import sqlalchemy as sa
        with _SessionLocal() as s:
            # Cover both stale hosts the serve-time canonicalizer treats as
            # stale, keeping stored data consistent with the served link.
            # Order matters: 'frontend-tidestracker.vercel.app' CONTAINS
            # 'tidestracker.vercel.app', so replace the longer host first (inner
            # REPLACE) before the bare one (outer) — otherwise the bare swap
            # would leave a broken 'frontend-risingtides-tracker.com' prefix.
            s.execute(sa.text(
                "UPDATE campaigns "
                "SET tracker_url = REPLACE(REPLACE(tracker_url, "
                "  'frontend-tidestracker.vercel.app', 'risingtides-tracker.com'), "
                "  'tidestracker.vercel.app', 'risingtides-tracker.com') "
                "WHERE tracker_url LIKE '%tidestracker.vercel.app%'"
            ))
            s.commit()
    except Exception:
        pass

    return True


def is_active() -> bool:
    """Check if database is initialized and active."""
    return _engine is not None


# ── Tides Tracker stats cache (CAMP-9) — Postgres L2 ──────────────────────
def get_tides_stats_cache(tracker_id: str):
    """Return (submissions_json, api_fetched_at, fetched_at) for a tracker, or
    None. submissions_json is the raw JSONB list (list[dict])."""
    if not tracker_id or not is_active():
        return None
    try:
        from campaign_manager.models import TidesTrackerStatsCache
        with _SessionLocal() as s:
            row = s.get(TidesTrackerStatsCache, tracker_id)
            if row is None:
                return None
            return (row.submissions_json, row.api_fetched_at or "", row.fetched_at)
    except Exception:
        return None


def upsert_tides_stats_cache(tracker_id: str, submissions_json, api_fetched_at: str, fetched_at):
    """Write-through upsert of one tracker's cached submissions. Best-effort —
    a cache write must never break the request that produced the data."""
    if not tracker_id or not is_active():
        return
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from campaign_manager.models import TidesTrackerStatsCache
        with _SessionLocal() as s:
            stmt = pg_insert(TidesTrackerStatsCache.__table__).values(
                tracker_id=tracker_id,
                submissions_json=submissions_json,
                api_fetched_at=api_fetched_at or "",
                fetched_at=fetched_at,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["tracker_id"],
                set_={
                    "submissions_json": stmt.excluded.submissions_json,
                    "api_fetched_at": stmt.excluded.api_fetched_at,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            s.execute(stmt)
            s.commit()
    except Exception:
        pass


def get_session() -> Session:
    """Get a new database session."""
    if not _SessionLocal:
        raise RuntimeError("Database not initialized. Call db.init() first.")
    return _SessionLocal()


# ── Campaign CRUD ─────────────────────────────────────────────────────

def get_campaign(slug: str) -> Optional[Dict]:
    """Get campaign metadata as a dict (matches old campaign.json format)."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            return None
        return c.to_meta_dict()


def get_campaign_obj(slug: str) -> Optional[Campaign]:
    """Get the Campaign ORM object (for updates)."""
    with get_session() as s:
        return s.query(Campaign).filter_by(slug=slug).first()


def save_campaign(slug: str, meta: Dict):
    """Create or update a campaign from a meta dict."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            c = Campaign(slug=slug)
            s.add(c)

        c.title = meta.get("title", "")
        c.name = meta.get("name", meta.get("title", ""))
        c.artist = meta.get("artist", "")
        c.song = meta.get("song", "")
        c.official_sound = meta.get("official_sound", "")
        c.sound_id = meta.get("sound_id", "")
        c.additional_sounds = meta.get("additional_sounds", [])
        c.cobrand_link = meta.get("cobrand_link", "")
        c.start_date = meta.get("start_date", "")
        c.budget = float(meta.get("budget", 0))
        c.platform = meta.get("platform", "tiktok")

        c.cobrand_share_url = meta.get("cobrand_share_url", c.cobrand_share_url or "")
        c.cobrand_upload_url = meta.get("cobrand_upload_url", c.cobrand_upload_url or "")
        c.cobrand_promotion_id = meta.get("cobrand_promotion_id", c.cobrand_promotion_id or "")
        c.cobrand_status = meta.get("cobrand_status", c.cobrand_status or "")
        c.tracker_campaign_id = meta.get("tracker_campaign_id", c.tracker_campaign_id)
        c.tracker_url = meta.get("tracker_url", c.tracker_url or "")
        c.source = meta.get("source", c.source or "manual")
        c.completion_status = meta.get("completion_status", c.completion_status or "none")
        # Use None instead of "" so the unique constraint allows multiple unset values
        raw_notion_id = meta.get("notion_page_id", c.notion_page_id)
        c.notion_page_id = raw_notion_id if raw_notion_id else None
        c.insta_sound = meta.get("insta_sound", c.insta_sound or "")
        c.tt_artist_label = meta.get("tt_artist_label", c.tt_artist_label or "")
        c.tt_track_name = meta.get("tt_track_name", c.tt_track_name or "")
        c.campaign_stage = meta.get("campaign_stage", c.campaign_stage or "")
        c.round = meta.get("round", c.round or "")
        c.label = meta.get("label", c.label or "")
        c.project_lead = meta.get("project_lead", c.project_lead or [])
        c.client_email = meta.get("client_email", c.client_email or "")
        c.platform_split = meta.get("platform_split", c.platform_split or {})
        c.content_types = meta.get("content_types", c.content_types or [])

        stats = meta.get("stats", {})
        c.total_views = int(stats.get("total_views", 0))
        c.total_likes = int(stats.get("total_likes", 0))
        last_scrape = stats.get("last_scrape", "")
        if last_scrape:
            try:
                c.last_scrape = datetime.fromisoformat(str(last_scrape))
            except (ValueError, TypeError):
                pass

        created_at = meta.get("created_at", "")
        if created_at and not c.created_at:
            try:
                c.created_at = datetime.fromisoformat(str(created_at))
            except (ValueError, TypeError):
                pass

        c.updated_at = datetime.now()
        s.commit()


def update_campaign_fields(slug: str, fields: Dict):
    """Update specific fields on a campaign by slug."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if c:
            for key, value in fields.items():
                if hasattr(c, key):
                    setattr(c, key, value)
            c.updated_at = datetime.now()
            s.commit()


def update_campaign_stats(slug: str, total_views: int, total_likes: int):
    """Update just the stats fields on a campaign."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if c:
            c.total_views = total_views
            c.total_likes = total_likes
            c.last_scrape = datetime.now()
            c.updated_at = datetime.now()
            s.commit()


def list_campaigns(exclude_completed: bool = False) -> List[Dict]:
    """List all campaigns, returning meta dicts.

    `exclude_completed=True` filters out campaigns whose completion_status
    is "completed". The cron, internal-creator attach, and slack-sounds
    poster pass this so they stop touching finished campaigns. Frontend
    list endpoints leave it False — the UI's Active/Finished tabs filter
    client-side and need both sets.
    """
    with get_session() as s:
        query = s.query(Campaign)
        if exclude_completed:
            query = query.filter(Campaign.completion_status != "completed")
        campaigns = query.all()
        return [c.to_meta_dict() for c in campaigns]


def list_campaigns_with_creators(
    *,
    with_matched_videos: bool = False,
    completion: Optional[str] = None,
) -> List[Tuple[Dict, List[Dict], List[Dict]]]:
    """List campaigns with their creators (and optionally matched_videos)
    eagerly loaded.

    Replaces the per-campaign N+1 of calling `get_creators(slug)` (and
    optionally `get_matched_videos(slug)`) in a loop. Issues 2 queries
    when `with_matched_videos=False`, 3 when True — independent of the
    campaign count.

    `completion` pushes the active/finished split DOWN INTO THE QUERY:
      "active"   -> completion_status != 'completed'
      "finished" -> completion_status == 'completed'
      None       -> everything (the old behaviour)

    This matters a lot more than it looks. The campaigns list endpoint
    used to load every campaign, then filter to the active ones in
    Python — so the default page load dragged all ~285 completed
    campaigns and the ~15.7k matched_videos hanging off them out of
    Postgres, built a dict for each, and threw ~90% of it away. The
    selectinload for creators/matched_videos is driven by the campaign
    IDs this query returns, so filtering here shrinks the child fetches
    too. See CAMP-40 for the original N+1 pass.

    Returns a list of (meta_dict, creators_list, matched_videos_list)
    tuples. When `with_matched_videos=False`, the third element is an
    empty list.
    """
    options = [selectinload(Campaign.creators)]
    if with_matched_videos:
        options.append(selectinload(Campaign.matched_videos))
    with get_session() as s:
        query = s.query(Campaign).options(*options)
        if completion == "active":
            query = query.filter(Campaign.completion_status != "completed")
        elif completion == "finished":
            query = query.filter(Campaign.completion_status == "completed")
        campaigns = query.all()
        return [
            (
                c.to_meta_dict(),
                [cr.to_dict() for cr in c.creators],
                [mv.to_dict() for mv in c.matched_videos] if with_matched_videos else [],
            )
            for c in campaigns
        ]


def campaign_exists(slug: str) -> bool:
    with get_session() as s:
        return s.query(Campaign).filter_by(slug=slug).count() > 0


def get_campaign_id(slug: str) -> Optional[int]:
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        return c.id if c else None


# ── Creators ──────────────────────────────────────────────────────────

def get_creators(slug: str) -> List[Dict]:
    """Get all creators for a campaign as a list of dicts."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            return []
        return [cr.to_dict() for cr in c.creators]


def save_creators(slug: str, creators_data: List[Dict]):
    """Replace all creators for a campaign."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            return

        # Delete existing creators
        s.query(Creator).filter_by(campaign_id=c.id).delete()

        # Insert new ones
        for cd in creators_data:
            cr = Creator(
                campaign_id=c.id,
                username=cd.get("username", ""),
                posts_owed=int(cd.get("posts_owed", 0) or 0),
                posts_done=int(cd.get("posts_done", 0) or 0),
                posts_matched=int(cd.get("posts_matched", 0) or 0),
                total_rate=float(cd.get("total_rate", 0) or 0),
                per_post_rate=float(cd.get("per_post_rate", 0) or 0),
                paypal_email=cd.get("paypal_email", ""),
                paid=cd.get("paid", "no"),
                payment_date=cd.get("payment_date", ""),
                platform=cd.get("platform", "tiktok"),
                added_date=cd.get("added_date", ""),
                status=cd.get("status", "active"),
                notes=cd.get("notes", ""),
                niches=cd.get("niches", []),
            )
            s.add(cr)

        s.commit()


# ── Matched Videos ────────────────────────────────────────────────────

def get_matched_videos(slug: str) -> List[Dict]:
    """Get all matched videos for a campaign."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            return []
        videos = s.query(MatchedVideo).filter_by(campaign_id=c.id)\
            .order_by(desc(MatchedVideo.upload_date)).all()
        return [v.to_dict() for v in videos]


def save_matched_videos(slug: str, videos: List[Dict]):
    """Save matched videos, deduplicating by URL."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            return

        # Get existing URLs
        existing = {v.url for v in s.query(MatchedVideo).filter_by(campaign_id=c.id).all()}

        seen = set(existing)
        for vd in videos:
            url = vd.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)

            mv = MatchedVideo(
                campaign_id=c.id,
                url=url,
                song=vd.get("song", ""),
                artist=vd.get("artist", ""),
                account=vd.get("account", ""),
                views=int(vd.get("views", 0) or 0),
                likes=int(vd.get("likes", 0) or 0),
                upload_date=vd.get("upload_date", ""),
                timestamp=str(vd.get("timestamp", "")),
                music_id=vd.get("music_id", ""),
                platform=vd.get("platform", "tiktok"),
                extracted_sound_id=vd.get("extracted_sound_id", ""),
                extracted_song_title=vd.get("extracted_song_title", ""),
            )
            s.add(mv)

        s.commit()


def replace_matched_videos(slug: str, videos: List[Dict]):
    """Upsert matched videos for a campaign by URL.

    NOTE: This used to do a full delete + reinsert, which destroyed
    `tracked_at` and other tracking-workflow state on every cron run.
    Now it upserts by URL — existing rows get stat updates and keep
    their tracked_at, while new URLs are inserted with first_seen_at=NOW().

    URLs in the existing matched_videos table that are NOT in the new
    `videos` list are LEFT ALONE — they continue to exist (so the human's
    tracking history doesn't get wiped if the scraper temporarily fails).
    """
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            return

        # Index existing rows by URL
        existing_rows = s.query(MatchedVideo).filter_by(campaign_id=c.id).all()
        existing_by_url = {row.url: row for row in existing_rows}

        seen = set()
        now = datetime.now()
        for vd in videos:
            url = vd.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)

            row = existing_by_url.get(url)
            if row is not None:
                # UPDATE — refresh stats + match metadata, preserve tracked_at
                row.song = vd.get("song", row.song)
                row.artist = vd.get("artist", row.artist)
                row.account = vd.get("account", row.account)
                row.views = int(vd.get("views", row.views) or 0)
                row.likes = int(vd.get("likes", row.likes) or 0)
                row.upload_date = vd.get("upload_date", row.upload_date)
                row.timestamp = str(vd.get("timestamp", row.timestamp))
                if vd.get("music_id"):
                    row.music_id = vd.get("music_id")
                if vd.get("extracted_sound_id"):
                    row.extracted_sound_id = vd.get("extracted_sound_id")
                if vd.get("extracted_song_title"):
                    row.extracted_song_title = vd.get("extracted_song_title")
                if vd.get("match_strategy"):
                    row.match_strategy = vd.get("match_strategy")

                # If the cron determined this video is now in Cobrand and the
                # row hasn't been marked tracked yet, auto-mark it. Don't
                # overwrite a human's existing tracked_at (preserves audit).
                incoming_tracked = vd.get("tracked_at")
                if incoming_tracked and row.tracked_at is None:
                    if isinstance(incoming_tracked, str):
                        try:
                            row.tracked_at = datetime.fromisoformat(incoming_tracked)
                        except Exception:
                            pass
                    elif isinstance(incoming_tracked, datetime):
                        row.tracked_at = incoming_tracked
                    if vd.get("tracked_by") and not row.tracked_by:
                        row.tracked_by = vd.get("tracked_by")
            else:
                # INSERT new — honor incoming tracked_at if the cron already
                # determined this video is in Cobrand (cross-check at scrape
                # time means the row never enters the Scrape Tasks queue).
                incoming_tracked = vd.get("tracked_at")
                if isinstance(incoming_tracked, str) and incoming_tracked:
                    try:
                        tracked_at_val = datetime.fromisoformat(incoming_tracked)
                    except Exception:
                        tracked_at_val = None
                elif isinstance(incoming_tracked, datetime):
                    tracked_at_val = incoming_tracked
                else:
                    tracked_at_val = None

                mv = MatchedVideo(
                    campaign_id=c.id,
                    url=url,
                    song=vd.get("song", ""),
                    artist=vd.get("artist", ""),
                    account=vd.get("account", ""),
                    views=int(vd.get("views", 0) or 0),
                    likes=int(vd.get("likes", 0) or 0),
                    upload_date=vd.get("upload_date", ""),
                    timestamp=str(vd.get("timestamp", "")),
                    music_id=vd.get("music_id", ""),
                    platform=vd.get("platform", "tiktok"),
                    extracted_sound_id=vd.get("extracted_sound_id", ""),
                    extracted_song_title=vd.get("extracted_song_title", ""),
                    match_strategy=vd.get("match_strategy", ""),
                    first_seen_at=now,
                    tracked_at=tracked_at_val,
                    tracked_by=vd.get("tracked_by", ""),
                )
                s.add(mv)

        s.commit()


# ── Scrape Logs ───────────────────────────────────────────────────────

def get_scrape_log(slug: str) -> Dict:
    """Get the latest scrape log for a campaign."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            return {}
        log = s.query(ScrapeLog).filter_by(campaign_id=c.id)\
            .order_by(desc(ScrapeLog.last_scrape)).first()
        if not log:
            return {}
        return {
            "last_scrape": log.last_scrape.isoformat() if log.last_scrape else "",
            "accounts_scraped": log.accounts_scraped,
            "videos_checked": log.videos_checked,
            "new_matches": log.new_matches,
            "total_matches": log.total_matches,
        }


def save_scrape_log(slug: str, log_data: Dict):
    """Save a scrape log entry."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            return

        log = ScrapeLog(
            campaign_id=c.id,
            last_scrape=datetime.now(),
            accounts_scraped=int(log_data.get("accounts_scraped", 0)),
            videos_checked=int(log_data.get("videos_checked", 0)),
            new_matches=int(log_data.get("new_matches", 0)),
            total_matches=int(log_data.get("total_matches", 0)),
        )
        s.add(log)
        s.commit()


# ── PayPal Memory ─────────────────────────────────────────────────────

def get_paypal(username: str) -> str:
    """Look up a PayPal email by username."""
    with get_session() as s:
        p = s.query(PaypalMemory).filter_by(username=username.lower()).first()
        return p.email if p else ""


def save_paypal(username: str, email: str):
    """Save or update a PayPal email for a username."""
    if not username or not email:
        return
    with get_session() as s:
        p = s.query(PaypalMemory).filter_by(username=username.lower()).first()
        if p:
            p.email = email
        else:
            s.add(PaypalMemory(username=username.lower(), email=email))
        s.commit()


def get_all_paypal() -> Dict[str, str]:
    """Get the full paypal memory as a dict."""
    with get_session() as s:
        return {p.username: p.email for p in s.query(PaypalMemory).all()}


# ── Inbox ─────────────────────────────────────────────────────────────

def get_inbox(status: Optional[str] = None) -> List[Dict]:
    """Get inbox items, optionally filtered by status."""
    with get_session() as s:
        query = s.query(InboxItem).order_by(desc(InboxItem.created_at))
        if status and status != "all":
            query = query.filter_by(status=status)
        return [i.to_dict() for i in query.all()]


def save_inbox_item(item_data: Dict):
    """Create a new inbox item."""
    with get_session() as s:
        item = InboxItem(
            id=item_data["id"],
            created_at=datetime.fromisoformat(item_data.get("created_at", datetime.now().isoformat())),
            status=item_data.get("status", "pending"),
            source=item_data.get("source", "slack"),
            raw_message=item_data.get("raw_message", ""),
            campaign_name=item_data.get("campaign_name", ""),
            campaign_slug=item_data.get("campaign_slug", ""),
            campaign_suggested=item_data.get("campaign_suggested", False),
            creators=item_data.get("creators", []),
            notes=item_data.get("notes", ""),
        )
        s.add(item)
        s.commit()


def update_inbox_item(item_id: str, updates: Dict):
    """Update fields on an inbox item."""
    with get_session() as s:
        item = s.query(InboxItem).filter_by(id=item_id).first()
        if not item:
            return False

        for key, val in updates.items():
            if hasattr(item, key):
                setattr(item, key, val)

        s.commit()
        return True


def get_inbox_item(item_id: str) -> Optional[Dict]:
    """Get a single inbox item."""
    with get_session() as s:
        item = s.query(InboxItem).filter_by(id=item_id).first()
        return item.to_dict() if item else None


# ── Internal Creators ─────────────────────────────────────────────────

def get_internal_creators() -> List[str]:
    """Get all internal creator usernames."""
    with get_session() as s:
        return sorted([ic.username for ic in s.query(InternalCreator).all()])


def save_internal_creators(usernames: List[str]):
    """Replace the full list of internal creators."""
    with get_session() as s:
        s.query(InternalCreator).delete()
        for u in sorted(set(usernames)):
            s.add(InternalCreator(username=u))
        s.commit()


def add_internal_creators(usernames: List[str]) -> List[str]:
    """Add new internal creators, returning list of actually added ones."""
    with get_session() as s:
        existing = {ic.username.lower() for ic in s.query(InternalCreator).all()}
        added = []
        for u in usernames:
            u = u.strip().lstrip("@").strip()
            if u and u.lower() not in existing:
                s.add(InternalCreator(username=u))
                existing.add(u.lower())
                added.append(u)
        s.commit()
        return added


def remove_internal_creator(username: str):
    """Remove an internal creator."""
    with get_session() as s:
        s.query(InternalCreator).filter(
            InternalCreator.username.ilike(username)
        ).delete(synchronize_session=False)
        s.commit()


# ── Internal Video Cache ──────────────────────────────────────────────

def get_internal_cache(username: str) -> List[Dict]:
    """Get cached videos for an internal creator."""
    with get_session() as s:
        videos = s.query(InternalVideoCache)\
            .filter_by(username=username.lower())\
            .all()
        return [v.to_dict() for v in videos]


def merge_internal_cache(username: str, new_videos: List[Dict]) -> List[Dict]:
    """Merge new videos into cache, dedupe by URL, prune >30 days old.

    For each newly-inserted video, also writes one
    `InternalVideoGroupAttribution` row per group the account currently
    belongs to. This snapshots group membership at scrape time so later
    re-tagging of the account does not rewrite historical attribution
    (RTA-13).
    """
    cutoff = datetime.now() - timedelta(days=30)
    uname = username.lower()

    with get_session() as s:
        # Prune old entries
        s.query(InternalVideoCache).filter(
            InternalVideoCache.username == uname,
            InternalVideoCache.cached_at < cutoff,
        ).delete(synchronize_session=False)

        # Existing rows by URL — keep the objects so we can REFRESH their stats
        # (sweep #5 fix: previously only new URLs were inserted and existing
        # rows were never updated, so an internal video's views/likes were
        # frozen at first-scrape value forever — internal song-discovery /
        # reporting off this cache showed stale numbers). Refresh with max()
        # since views/likes are monotonic, same rule as merge_matched_videos.
        existing_by_url = {v.url: v for v in
                           s.query(InternalVideoCache).filter_by(username=uname).all()}

        new_rows: List[InternalVideoCache] = []
        for vd in new_videos:
            url = vd.get("url", "")
            if not url:
                continue
            fresh_views = int(vd.get("views", 0) or 0)
            fresh_likes = int(vd.get("likes", 0) or 0)
            if url in existing_by_url:
                row = existing_by_url[url]
                row.views = max(int(row.views or 0), fresh_views)
                row.likes = max(int(row.likes or 0), fresh_likes)
                row.cached_at = datetime.now()
            else:
                row = InternalVideoCache(
                    username=uname,
                    url=url,
                    song=vd.get("song", ""),
                    artist=vd.get("artist", ""),
                    account=vd.get("account", ""),
                    views=fresh_views,
                    likes=fresh_likes,
                    upload_date=vd.get("upload_date", ""),
                    timestamp=str(vd.get("timestamp", "")),
                    cached_at=datetime.now(),
                )
                s.add(row)
                new_rows.append(row)
                existing_by_url[url] = row

        # Flush so new_rows get their PK ids before we write attribution.
        if new_rows:
            s.flush()

            # Resolve the account's CURRENT group memberships once.
            group_ids = [
                gid
                for (gid,) in s.query(InternalCreatorGroupMember.group_id)
                .filter(func.lower(InternalCreatorGroupMember.username) == uname)
                .all()
            ]

            if group_ids:
                # One attribution row per (new video × current group).
                # Idempotent: dedup against any existing rows by the
                # (video_id, group_id) unique constraint.
                existing_pairs = set()
                new_video_ids = [r.id for r in new_rows]
                if new_video_ids:
                    existing_pairs = {
                        (vid, gid)
                        for (vid, gid) in s.query(
                            InternalVideoGroupAttribution.video_id,
                            InternalVideoGroupAttribution.group_id,
                        ).filter(
                            InternalVideoGroupAttribution.video_id.in_(new_video_ids)
                        ).all()
                    }
                for row in new_rows:
                    for gid in group_ids:
                        if (row.id, gid) in existing_pairs:
                            continue
                        s.add(InternalVideoGroupAttribution(
                            video_id=row.id,
                            group_id=gid,
                        ))

        s.commit()

        # Return all current cached videos
        all_cached = s.query(InternalVideoCache).filter_by(username=uname).all()
        return [v.to_dict() for v in all_cached]


# ── Internal Scrape Results ───────────────────────────────────────────

def get_internal_results() -> Dict:
    """Get the latest internal scrape results."""
    with get_session() as s:
        result = s.query(InternalScrapeResult)\
            .order_by(desc(InternalScrapeResult.scraped_at)).first()
        if not result:
            return {}
        return {
            "scraped_at": result.scraped_at.isoformat() if result.scraped_at else "",
            "hours": result.hours,
            "start_dt": result.start_dt.isoformat() if result.start_dt else "",
            "end_dt": result.end_dt.isoformat() if result.end_dt else "",
            "accounts_total": result.accounts_total,
            "accounts_successful": result.accounts_successful,
            "accounts_failed": result.accounts_failed,
            "total_videos": result.total_videos,
            "total_videos_unfiltered": result.total_videos_unfiltered,
            "unique_songs": result.unique_songs,
            "songs": [
                {
                    "key": s.get("key", ""),
                    "song": s.get("song", ""),
                    "artist": s.get("artist", ""),
                    "total_views": s.get("total_views", sum(v.get("views", 0) for v in s.get("videos", []))),
                    "total_likes": s.get("total_likes", sum(v.get("likes", 0) for v in s.get("videos", []))),
                    "accounts": s.get("accounts", sorted(set(v.get("account", "") for v in s.get("videos", [])))),
                    "videos": s.get("videos", []),
                }
                for s in (result.songs or [])
            ],
        }


def save_internal_results(data: Dict):
    """Save internal scrape results."""
    with get_session() as s:
        result = InternalScrapeResult(
            scraped_at=datetime.now(EST).replace(tzinfo=None),
            hours=data.get("hours", 48),
            start_dt=datetime.fromisoformat(data["start_dt"]) if data.get("start_dt") else None,
            end_dt=datetime.fromisoformat(data["end_dt"]) if data.get("end_dt") else None,
            accounts_total=data.get("accounts_total", 0),
            accounts_successful=data.get("accounts_successful", 0),
            accounts_failed=data.get("accounts_failed", 0),
            total_videos=data.get("total_videos", 0),
            total_videos_unfiltered=data.get("total_videos_unfiltered", 0),
            unique_songs=data.get("unique_songs", 0),
            songs=data.get("songs", []),
        )
        s.add(result)
        s.commit()


# ── Cobrand Cache ─────────────────────────────────────────────────────

def update_cobrand_cache(slug: str, stats: dict):
    """Update cached Cobrand stats for a campaign."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if c:
            c.cobrand_promotion_id = stats.get("promotion_id", "")
            c.cobrand_live_submissions = stats.get("live_submission_count", 0)
            c.cobrand_comments = stats.get("comment_count", 0)
            c.cobrand_status = stats.get("status", "")
            c.cobrand_last_sync = datetime.now()
            s.commit()


# ── Notion Sync ───────────────────────────────────────────────────────

def get_synced_notion_ids() -> set:
    """Get all Notion page IDs that have already been synced."""
    with get_session() as s:
        results = s.query(Campaign.notion_page_id).filter(
            Campaign.notion_page_id.isnot(None),
            Campaign.notion_page_id != "",
        ).all()
        return {r[0] for r in results}


# ── Cron Logs ────────────────────────────────────────────────────────

def create_cron_log(job_type: str) -> int:
    """Create a new cron log entry with status 'running'. Returns the log ID."""
    with get_session() as s:
        log = CronLog(
            job_type=job_type,
            status="running",
            started_at=datetime.now(EST).replace(tzinfo=None),
        )
        s.add(log)
        s.commit()
        return log.id


def finish_cron_log(log_id: int, status: str, summary: dict):
    """Mark a cron log as completed or failed with summary data."""
    with get_session() as s:
        log = s.query(CronLog).filter_by(id=log_id).first()
        if log:
            log.status = status
            log.finished_at = datetime.now(EST).replace(tzinfo=None)
            log.summary = summary
            s.commit()


def get_cron_logs(limit: int = 20, offset: int = 0) -> List[Dict]:
    """Get paginated cron log history, newest first."""
    with get_session() as s:
        logs = s.query(CronLog)\
            .order_by(desc(CronLog.started_at))\
            .offset(offset).limit(limit).all()
        return [l.to_dict() for l in logs]


def get_cron_log_by_id(log_id: int) -> Optional[Dict]:
    """Get a single cron log entry by ID."""
    with get_session() as s:
        log = s.query(CronLog).filter_by(id=log_id).first()
        return log.to_dict() if log else None


def reap_orphaned_cron_logs(threshold_minutes: int = 30) -> List[int]:
    """Mark cron_log rows stuck in 'running' beyond threshold as 'failed'.

    Daemon threads spawned by /api/cron/trigger die on worker recycle, leaving
    the cron_log row at status='running' forever. This sweeps those and
    surfaces them in the cron logs view as failures rather than lying about
    in-flight work.
    """
    threshold = datetime.now(EST).replace(tzinfo=None) - timedelta(
        minutes=threshold_minutes,
    )
    reaped: List[int] = []
    with get_session() as s:
        stale = (
            s.query(CronLog)
            .filter(CronLog.status == "running", CronLog.started_at < threshold)
            .all()
        )
        for row in stale:
            row.status = "failed"
            row.finished_at = datetime.now(EST).replace(tzinfo=None)
            row.summary = {
                "error": "orphaned: worker recycle killed the daemon thread",
                "threshold_minutes": threshold_minutes,
            }
            reaped.append(row.id)
        if reaped:
            s.commit()
    return reaped


# ── Network Creators ─────────────────────────────────────────────────

def get_network_creators() -> List[Dict]:
    """Get all creators in the network roster."""
    with get_session() as s:
        creators = s.query(NetworkCreator).order_by(NetworkCreator.username).all()
        return [c.to_dict() for c in creators]


def get_network_creator(username: str) -> Optional[Dict]:
    """Get a single network creator by username."""
    with get_session() as s:
        c = s.query(NetworkCreator).filter(
            NetworkCreator.username.ilike(username)
        ).first()
        return c.to_dict() if c else None


def add_network_creator(data: Dict) -> Dict:
    """Add a creator to the network. Returns the created record."""
    with get_session() as s:
        c = NetworkCreator(
            username=data["username"].strip().lstrip("@").lower(),
            platform=data.get("platform", "tiktok"),
            default_rate=float(data.get("default_rate", 0)),
            default_posts=int(data.get("default_posts", 1)),
            paypal_email=data.get("paypal_email", ""),
            manychat_subscriber_id=data.get("manychat_subscriber_id", ""),
            niches=data.get("niches", []),
            notes=data.get("notes", ""),
            added_at=datetime.now(),
        )
        s.add(c)
        s.commit()
        s.refresh(c)
        return c.to_dict()


def update_network_creator(username: str, data: Dict) -> Optional[Dict]:
    """Update a network creator's fields."""
    with get_session() as s:
        c = s.query(NetworkCreator).filter(
            NetworkCreator.username.ilike(username)
        ).first()
        if not c:
            return None
        for key, val in data.items():
            if hasattr(c, key) and key not in ("id", "added_at"):
                setattr(c, key, val)
        s.commit()
        s.refresh(c)
        return c.to_dict()


def remove_network_creator(username: str) -> bool:
    """Remove a creator from the network."""
    with get_session() as s:
        count = s.query(NetworkCreator).filter(
            NetworkCreator.username.ilike(username)
        ).delete(synchronize_session=False)
        s.commit()
        return count > 0


# ── Outreach Messages ────────────────────────────────────────────────

def get_outreach_messages(campaign_id: int) -> List[Dict]:
    """Get all outreach messages for a campaign."""
    with get_session() as s:
        msgs = s.query(OutreachMessage).filter_by(campaign_id=campaign_id)\
            .order_by(OutreachMessage.id).all()
        return [m.to_dict() for m in msgs]


def get_outreach_message(campaign_id: int, username: str) -> Optional[Dict]:
    """Get a single outreach message."""
    with get_session() as s:
        m = s.query(OutreachMessage).filter_by(
            campaign_id=campaign_id, username=username.lower()
        ).first()
        return m.to_dict() if m else None


def add_outreach_messages(campaign_id: int, creators: List[Dict]) -> List[Dict]:
    """Add draft outreach messages for a list of creators."""
    added = []
    with get_session() as s:
        for cr in creators:
            username = cr["username"].strip().lstrip("@").lower()
            existing = s.query(OutreachMessage).filter_by(
                campaign_id=campaign_id, username=username
            ).first()
            if existing:
                continue
            m = OutreachMessage(
                campaign_id=campaign_id,
                username=username,
                rate_offered=float(cr.get("rate", 0)),
                posts_offered=int(cr.get("posts", 1)),
                status="draft",
            )
            s.add(m)
            added.append(m)
        s.commit()
        return [m.to_dict() for m in added]


def remove_outreach_message(campaign_id: int, username: str) -> bool:
    """Remove a draft outreach message."""
    with get_session() as s:
        count = s.query(OutreachMessage).filter_by(
            campaign_id=campaign_id, username=username.lower(), status="draft"
        ).delete(synchronize_session=False)
        s.commit()
        return count > 0


def update_outreach_message(campaign_id: int, username: str, updates: Dict) -> Optional[Dict]:
    """Update an outreach message."""
    with get_session() as s:
        m = s.query(OutreachMessage).filter_by(
            campaign_id=campaign_id, username=username.lower()
        ).first()
        if not m:
            return None
        for key, val in updates.items():
            if hasattr(m, key) and key not in ("id", "campaign_id"):
                setattr(m, key, val)
        s.commit()
        s.refresh(m)
        return m.to_dict()


def mark_outreach_sent(campaign_id: int, usernames: List[str], message_text: str) -> List[str]:
    """Mark draft messages as sent. Returns list of sent usernames."""
    sent = []
    with get_session() as s:
        for username in usernames:
            m = s.query(OutreachMessage).filter_by(
                campaign_id=campaign_id, username=username.lower(), status="draft"
            ).first()
            if m:
                m.status = "sent"
                m.message_text = message_text
                m.sent_at = datetime.now()
                sent.append(m.username)
        s.commit()
    return sent


def confirm_outreach(campaign_id: int, username: str) -> Optional[Dict]:
    """Confirm an outreach (mark as accepted and add creator to campaign)."""
    with get_session() as s:
        m = s.query(OutreachMessage).filter_by(
            campaign_id=campaign_id, username=username.lower()
        ).first()
        if not m:
            return None
        m.status = "accepted"
        m.responded_at = datetime.now()

        # Add creator to campaign if not already there
        existing = s.query(Creator).filter_by(
            campaign_id=campaign_id, username=m.username
        ).first()
        if not existing:
            cr = Creator(
                campaign_id=campaign_id,
                username=m.username,
                posts_owed=m.posts_offered,
                total_rate=m.rate_offered,
                per_post_rate=m.rate_offered / max(m.posts_offered, 1),
                platform="tiktok",
                added_date=datetime.now().strftime("%Y-%m-%d"),
                status="active",
            )
            # Copy paypal and niches from network creator if available
            nc = s.query(NetworkCreator).filter(
                NetworkCreator.username.ilike(m.username)
            ).first()
            if nc:
                if nc.paypal_email:
                    cr.paypal_email = nc.paypal_email
                if nc.niches:
                    cr.niches = nc.niches
            s.add(cr)

        s.commit()
        return m.to_dict()


# ── Internal Creator Groups ───────────────────────────────────────────
#
# Groups bucket internal creators by who books them, label, niche, or
# any custom criteria. A creator can belong to many groups.

def _group_to_dict(group: "InternalCreatorGroup", member_count: int) -> Dict:
    return {
        "id": group.id,
        "slug": group.slug or "",
        "title": group.title or "",
        "kind": group.kind or "custom",
        "sort_order": group.sort_order or 0,
        "tracker_id": getattr(group, "tracker_id", None) or "",
        "created_at": group.created_at.isoformat() if group.created_at else "",
        "member_count": member_count,
    }


def list_internal_groups() -> List[Dict]:
    """List all internal creator groups with member counts."""
    with get_session() as s:
        rows = (
            s.query(
                InternalCreatorGroup,
                func.count(InternalCreatorGroupMember.username).label("n"),
            )
            .outerjoin(
                InternalCreatorGroupMember,
                InternalCreatorGroupMember.group_id == InternalCreatorGroup.id,
            )
            .group_by(InternalCreatorGroup.id)
            .order_by(InternalCreatorGroup.sort_order, InternalCreatorGroup.title)
            .all()
        )
        return [_group_to_dict(g, int(n or 0)) for g, n in rows]


def get_internal_group(identifier) -> Optional[Dict]:
    """Get a group by id or slug."""
    with get_session() as s:
        q = s.query(InternalCreatorGroup)
        if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
            g = q.filter_by(id=int(identifier)).first()
        else:
            g = q.filter_by(slug=str(identifier)).first()
        if not g:
            return None
        n = s.query(func.count(InternalCreatorGroupMember.username))\
            .filter_by(group_id=g.id).scalar() or 0
        return _group_to_dict(g, int(n))


def create_internal_group(slug: str, title: str, kind: str = "custom",
                          sort_order: int = 0) -> Optional[Dict]:
    """Create a new group. Returns the group dict, or None if slug already exists."""
    slug = (slug or "").strip().lower()
    title = (title or "").strip()
    if not slug or not title:
        return None
    with get_session() as s:
        if s.query(InternalCreatorGroup).filter_by(slug=slug).first():
            return None
        g = InternalCreatorGroup(
            slug=slug,
            title=title,
            kind=(kind or "custom").strip().lower(),
            sort_order=int(sort_order or 0),
        )
        s.add(g)
        s.commit()
        s.refresh(g)
        return _group_to_dict(g, 0)


def update_internal_group(group_id: int, fields: Dict) -> Optional[Dict]:
    """Update mutable fields on a group (title, kind, sort_order)."""
    with get_session() as s:
        g = s.query(InternalCreatorGroup).filter_by(id=group_id).first()
        if not g:
            return None
        if "title" in fields and fields["title"]:
            g.title = str(fields["title"]).strip()
        if "kind" in fields and fields["kind"]:
            g.kind = str(fields["kind"]).strip().lower()
        if "sort_order" in fields:
            try:
                g.sort_order = int(fields["sort_order"])
            except (TypeError, ValueError):
                pass
        if "tracker_id" in fields:
            # "" / None clears the link; any other value pins the UUID.
            tid = fields["tracker_id"]
            g.tracker_id = (str(tid).strip() or None) if tid else None
        s.commit()
        n = s.query(func.count(InternalCreatorGroupMember.username))\
            .filter_by(group_id=g.id).scalar() or 0
        return _group_to_dict(g, int(n))


def delete_internal_group(group_id: int) -> bool:
    """Delete a group and all its memberships. Returns True if deleted."""
    with get_session() as s:
        g = s.query(InternalCreatorGroup).filter_by(id=group_id).first()
        if not g:
            return False
        s.delete(g)  # cascade removes members
        s.commit()
        return True


def get_group_members(group_id: int) -> List[str]:
    """List usernames belonging to a group."""
    with get_session() as s:
        rows = s.query(InternalCreatorGroupMember.username)\
            .filter_by(group_id=group_id)\
            .order_by(InternalCreatorGroupMember.username)\
            .all()
        return [r[0] for r in rows]


def add_group_members(group_id: int, usernames: List[str]) -> List[str]:
    """Add usernames to a group. Returns list of actually-added usernames.

    Unknown usernames are silently skipped (so the caller can add creators
    independently). Already-member usernames are also skipped.
    """
    cleaned = [u.strip().lstrip("@").strip().lower() for u in usernames if u]
    cleaned = [u for u in cleaned if u]
    if not cleaned:
        return []
    with get_session() as s:
        if not s.query(InternalCreatorGroup).filter_by(id=group_id).first():
            return []
        # Skip usernames that don't exist in internal_creators.
        known = {
            r[0].lower() for r in s.query(InternalCreator.username)
            .filter(func.lower(InternalCreator.username).in_(cleaned)).all()
        }
        # Skip already-members.
        already = {
            r[0].lower() for r in s.query(InternalCreatorGroupMember.username)
            .filter(InternalCreatorGroupMember.group_id == group_id,
                    func.lower(InternalCreatorGroupMember.username).in_(cleaned))
            .all()
        }
        added = []
        for u in cleaned:
            if u in known and u not in already:
                s.add(InternalCreatorGroupMember(group_id=group_id, username=u))
                added.append(u)
                already.add(u)
        s.commit()
        return added


def remove_group_member(group_id: int, username: str) -> bool:
    """Remove a single username from a group."""
    uname = username.strip().lstrip("@").lower()
    with get_session() as s:
        n = s.query(InternalCreatorGroupMember).filter(
            InternalCreatorGroupMember.group_id == group_id,
            func.lower(InternalCreatorGroupMember.username) == uname,
        ).delete(synchronize_session=False)
        s.commit()
        return n > 0


def get_groups_for_creator(username: str) -> List[Dict]:
    """List all groups a creator belongs to."""
    uname = username.strip().lstrip("@").lower()
    with get_session() as s:
        groups = (
            s.query(InternalCreatorGroup)
            .join(
                InternalCreatorGroupMember,
                InternalCreatorGroupMember.group_id == InternalCreatorGroup.id,
            )
            .filter(func.lower(InternalCreatorGroupMember.username) == uname)
            .order_by(InternalCreatorGroup.sort_order, InternalCreatorGroup.title)
            .all()
        )
        return [_group_to_dict(g, 0) for g in groups]


# ── Internal Creator Stats ────────────────────────────────────────────
#
# Stats pull directly from InternalVideoCache, which already holds a
# 30-day rolling window of scraped posts. We filter by upload_date (stored
# as a YYYYMMDD string, which sorts lexicographically), so "last N days"
# is a simple string comparison.

def _cutoff_yyyymmdd(days: int) -> str:
    return (datetime.now() - timedelta(days=int(days or 30))).strftime("%Y%m%d")


def get_creator_stats(username: str, days: int = 30) -> Dict:
    """Stats for a single internal creator over the last N days.

    Returns: { username, days, total_posts, total_views, total_likes,
               posts_by_song: [{song, artist, posts, views}], top_posts: [...] }
    """
    uname = username.strip().lstrip("@").lower()
    cutoff = _cutoff_yyyymmdd(days)

    with get_session() as s:
        videos = (
            s.query(InternalVideoCache)
            .filter(
                func.lower(InternalVideoCache.username) == uname,
                InternalVideoCache.upload_date >= cutoff,
            )
            .all()
        )

        total_posts = len(videos)
        total_views = sum(int(v.views or 0) for v in videos)
        total_likes = sum(int(v.likes or 0) for v in videos)

        # Group by (song, artist)
        by_song: Dict[tuple, Dict] = {}
        for v in videos:
            key = ((v.song or "").strip(), (v.artist or "").strip())
            slot = by_song.setdefault(key, {"song": key[0], "artist": key[1],
                                            "posts": 0, "views": 0, "likes": 0})
            slot["posts"] += 1
            slot["views"] += int(v.views or 0)
            slot["likes"] += int(v.likes or 0)

        posts_by_song = sorted(by_song.values(), key=lambda r: r["views"], reverse=True)

        top_posts = sorted(
            (v.to_dict() for v in videos),
            key=lambda p: p.get("views", 0),
            reverse=True,
        )[:10]

        return {
            "username": uname,
            "days": int(days),
            "cutoff": cutoff,
            "total_posts": total_posts,
            "total_views": total_views,
            "total_likes": total_likes,
            "posts_by_song": posts_by_song,
            "top_posts": top_posts,
        }


def get_group_stats(group_id: int, days: int = 30) -> Optional[Dict]:
    """Aggregate stats for a group over the last N days.

    Returns: { group: {...}, days, total_posts, total_views, total_likes,
               creators: [{username, posts, views, likes}], top_songs: [...] }

    Source of attribution (RTA-13):
      1. Videos with rows in `internal_video_group_attribution` for this
         group are attributed via the side-table (point-in-time, durable
         against later re-tagging).
      2. Videos with NO side-table rows at all (historical, pre-RTA-13)
         fall back to runtime membership join against
         `internal_creator_group_members`.

      As all videos get attribution rows on new scrapes, the fallback
      shrinks over time. Backfill of historical videos is out of scope
      for this ticket.
    """
    group = get_internal_group(group_id)
    if not group:
        return None

    members = get_group_members(group_id)
    cutoff = _cutoff_yyyymmdd(days)

    with get_session() as s:
        # (1) Side-table-attributed videos for this group.
        attributed_videos = (
            s.query(InternalVideoCache)
            .join(
                InternalVideoGroupAttribution,
                InternalVideoGroupAttribution.video_id == InternalVideoCache.id,
            )
            .filter(
                InternalVideoGroupAttribution.group_id == group_id,
                InternalVideoCache.upload_date >= cutoff,
            )
            .all()
        )

        # (2) Runtime-join fallback for historical (un-attributed) videos.
        # Anti-join: videos whose username currently belongs to the group
        # but which have NO row in `internal_video_group_attribution` at
        # all. Once a video has any attribution row, it's owned by the
        # side-table — we don't double-count it through the fallback.
        legacy_videos: List[InternalVideoCache] = []
        members_lower = [m.lower() for m in members] if members else []
        if members_lower:
            attributed_ids_subq = (
                s.query(InternalVideoGroupAttribution.video_id).subquery()
            )
            legacy_videos = (
                s.query(InternalVideoCache)
                .filter(
                    func.lower(InternalVideoCache.username).in_(members_lower),
                    InternalVideoCache.upload_date >= cutoff,
                    ~InternalVideoCache.id.in_(s.query(attributed_ids_subq.c.video_id)),
                )
                .all()
            )

        # Union — videos are disjoint by construction (attributed set
        # excludes legacy set via the anti-join above).
        videos = list(attributed_videos) + list(legacy_videos)

        if not videos and not members:
            return {
                "group": group,
                "days": int(days),
                "total_posts": 0,
                "total_views": 0,
                "total_likes": 0,
                "creators": [],
                "top_songs": [],
            }

        # Per-creator rollup. Seed slots for current members so a
        # zero-post member still surfaces in the response.
        per_creator: Dict[str, Dict] = {
            m: {"username": m, "posts": 0, "views": 0, "likes": 0} for m in members_lower
        }
        # Per-song rollup
        by_song: Dict[tuple, Dict] = {}

        for v in videos:
            uname = (v.username or "").lower()
            slot = per_creator.setdefault(
                uname, {"username": uname, "posts": 0, "views": 0, "likes": 0}
            )
            slot["posts"] += 1
            slot["views"] += int(v.views or 0)
            slot["likes"] += int(v.likes or 0)

            key = ((v.song or "").strip(), (v.artist or "").strip())
            s_slot = by_song.setdefault(
                key, {"song": key[0], "artist": key[1], "posts": 0, "views": 0}
            )
            s_slot["posts"] += 1
            s_slot["views"] += int(v.views or 0)

        creators_ranked = sorted(
            per_creator.values(), key=lambda r: r["views"], reverse=True
        )
        top_songs = sorted(
            by_song.values(), key=lambda r: r["views"], reverse=True
        )[:10]

        return {
            "group": group,
            "days": int(days),
            "cutoff": cutoff,
            "total_posts": sum(c["posts"] for c in creators_ranked),
            "total_views": sum(c["views"] for c in creators_ranked),
            "total_likes": sum(c["likes"] for c in creators_ranked),
            "creators": creators_ranked,
            "top_songs": top_songs,
        }


# ===================================================================
# TidesTrackers (folder overlay)
# ===================================================================
#
# Tracker data lives in TidesTracker (Supabase). The helpers below only
# manage local groups and the join from a TidesTracker UUID to a group.

def list_tracker_groups() -> List[Dict]:
    """List all tracker groups with assignment counts."""
    with get_session() as s:
        rows = (
            s.query(
                TrackerGroup,
                func.count(TrackerGroupAssignment.tracker_id).label("n"),
            )
            .outerjoin(
                TrackerGroupAssignment,
                TrackerGroupAssignment.group_id == TrackerGroup.id,
            )
            .group_by(TrackerGroup.id)
            .order_by(TrackerGroup.sort_order, TrackerGroup.title)
            .all()
        )
        return [g.to_dict(int(n or 0)) for g, n in rows]


def create_tracker_group(slug: str, title: str, sort_order: int = 0) -> Optional[Dict]:
    """Create a tracker group. Returns the group dict, or None on conflict."""
    slug = (slug or "").strip().lower()
    title = (title or "").strip()
    if not slug or not title:
        return None
    with get_session() as s:
        if s.query(TrackerGroup).filter_by(slug=slug).first():
            return None
        g = TrackerGroup(slug=slug, title=title, sort_order=int(sort_order or 0))
        s.add(g)
        s.commit()
        s.refresh(g)
        return g.to_dict(0)


def delete_tracker_group(group_id: int) -> bool:
    """Delete a tracker group and all its assignments."""
    with get_session() as s:
        g = s.query(TrackerGroup).filter_by(id=group_id).first()
        if not g:
            return False
        s.delete(g)
        s.commit()
        return True


# ── ManyChat Message Log ──────────────────────────────────────────────
#
# Every DM to/from a ManyChat subscriber is stored verbatim. Messages
# are deduplicated by (subscriber_id, manychat_message_id) so replaying
# the same webhook is idempotent. Inbound messages arrive via the
# /api/manychat/webhook endpoint; outbound messages are logged by the
# outreach send path when a ManyChat API call succeeds.

def log_manychat_message(
    subscriber_id: str,
    direction: str,
    text: str,
    *,
    username: str = "",
    platform: str = "tiktok",
    manychat_message_id: str = "",
    flow_ns: str = "",
    campaign_slug: str = "",
) -> Optional[Dict]:
    """Insert a single DM into the message log. Returns the stored row, or
    None if a duplicate (same subscriber_id + manychat_message_id) already
    exists.
    """
    direction = (direction or "").strip().lower()
    if direction not in ("in", "out"):
        return None
    subscriber_id = (subscriber_id or "").strip()
    if not subscriber_id:
        return None

    with get_session() as s:
        # Dedupe on (subscriber_id, manychat_message_id) when an ID is present.
        if manychat_message_id:
            existing = (
                s.query(ManyChatMessage)
                .filter_by(
                    subscriber_id=subscriber_id,
                    manychat_message_id=manychat_message_id,
                )
                .first()
            )
            if existing:
                return existing.to_dict()

        msg = ManyChatMessage(
            subscriber_id=subscriber_id,
            username=(username or "").lstrip("@").strip(),
            platform=(platform or "tiktok").strip().lower(),
            direction=direction,
            text=text or "",
            manychat_message_id=manychat_message_id or "",
            flow_ns=flow_ns or "",
            campaign_slug=campaign_slug or "",
            received_at=datetime.now(),
        )
        s.add(msg)
        s.commit()
        s.refresh(msg)
        return msg.to_dict()


def set_message_intent(
    message_id: int,
    intent: str,
    confidence: float = 0.0,
    extracted: Optional[Dict] = None,
) -> bool:
    """Attach Claude classification results to a logged message."""
    with get_session() as s:
        msg = s.query(ManyChatMessage).filter_by(id=message_id).first()
        if not msg:
            return False
        msg.intent = (intent or "").strip().lower()
        msg.intent_confidence = float(confidence or 0.0)
        msg.extracted = extracted or {}
        msg.classified_at = datetime.now()
        s.commit()
        return True


def get_tracker_assignments() -> Dict[str, int]:
    """Return {tracker_id: group_id} for every assigned tracker."""
    with get_session() as s:
        rows = s.query(TrackerGroupAssignment.tracker_id, TrackerGroupAssignment.group_id).all()
        return {tid: gid for tid, gid in rows}


def set_tracker_assignment(tracker_id: str, group_id: Optional[int]) -> None:
    """Assign a tracker to a group, or clear its assignment if group_id is None."""
    tid = (tracker_id or "").strip()
    if not tid:
        return
    with get_session() as s:
        existing = s.query(TrackerGroupAssignment).filter_by(tracker_id=tid).first()
        if group_id is None:
            if existing:
                s.delete(existing)
                s.commit()
            return
        if existing:
            existing.group_id = int(group_id)
        else:
            s.add(TrackerGroupAssignment(tracker_id=tid, group_id=int(group_id)))
        s.commit()


def get_tracker_names() -> Dict[str, str]:
    """Return {tracker_id: display_name} for every tracker with a local rename."""
    with get_session() as s:
        rows = s.query(TrackerName.tracker_id, TrackerName.display_name).all()
        return {tid: name for tid, name in rows}


def set_tracker_name(tracker_id: str, display_name: Optional[str]) -> None:
    """Set or clear a local display-name override for a tracker."""
    tid = (tracker_id or "").strip()
    if not tid:
        return
    cleaned = (display_name or "").strip()
    with get_session() as s:
        existing = s.query(TrackerName).filter_by(tracker_id=tid).first()
        if not cleaned:
            if existing:
                s.delete(existing)
                s.commit()
            return
        if existing:
            existing.display_name = cleaned
        else:
            s.add(TrackerName(tracker_id=tid, display_name=cleaned))
        s.commit()


def get_tracker_campaign_links() -> Dict[str, str]:
    """Return {tracker_id: campaign_slug} for every linked tracker."""
    with get_session() as s:
        rows = s.query(TrackerCampaignLink.tracker_id, TrackerCampaignLink.campaign_slug).all()
        return {tid: slug for tid, slug in rows}


def get_tracker_id_for_campaign(slug: str) -> str:
    """Return the TidesTracker UUID linked to this campaign, or empty string.

    Checks two sources in order:
        1. campaigns.tracker_campaign_id (newer canonical field)
        2. tracker_campaign_links overlay table (legacy manual mapping)

    The unification work folds these into one — until then, both are checked.
    """
    if not slug:
        return ""
    with get_session() as s:
        # Source 1 — campaigns row
        c = s.query(Campaign).filter_by(slug=slug).first()
        if c and (c.tracker_campaign_id or "").strip():
            return c.tracker_campaign_id

        # Source 2 — overlay table
        row = s.query(TrackerCampaignLink).filter_by(campaign_slug=slug).first()
        if row:
            return row.tracker_id or ""
    return ""


def get_campaign_to_tracker_map() -> Dict[str, str]:
    """Return {campaign_slug: tracker_id} for every campaign that has a
    tracker (from either source). Used by the cron to look up trackers in
    bulk without hitting the DB once per campaign.
    """
    result: Dict[str, str] = {}
    with get_session() as s:
        # Source 1
        for c in s.query(Campaign.slug, Campaign.tracker_campaign_id).all():
            slug, tid = c[0], (c[1] or "").strip()
            if slug and tid:
                result[slug] = tid
        # Source 2 — fill in gaps without overwriting source 1
        for row in s.query(TrackerCampaignLink.campaign_slug, TrackerCampaignLink.tracker_id).all():
            slug, tid = row[0], (row[1] or "").strip()
            if slug and tid and slug not in result:
                result[slug] = tid
    return result


def set_tracker_campaign_link(
    tracker_id: str,
    campaign_slug: Optional[str],
    display_name: Optional[str] = None,
) -> None:
    """Link tracker to a campaign by slug, or clear if slug is None/empty.

    When ``display_name`` is provided and no ``tracker_names`` row exists
    for this tracker yet, populate one in the same transaction. Existing
    name overrides are never clobbered — users can rename freely without
    fear of a re-link wiping their label.

    Atomic: the link row and the name row land in one commit. This is the
    forward fix for RTA-41 (tracker_names population gap).
    """
    tid = (tracker_id or "").strip()
    if not tid:
        return
    slug = (campaign_slug or "").strip()
    cleaned_name = (display_name or "").strip()
    with get_session() as s:
        existing = s.query(TrackerCampaignLink).filter_by(tracker_id=tid).first()
        if not slug:
            if existing:
                s.delete(existing)
                s.commit()
            return
        if existing:
            existing.campaign_slug = slug
        else:
            s.add(TrackerCampaignLink(tracker_id=tid, campaign_slug=slug))

        # Ensure tracker_names has a row for this tracker. Only fill it
        # in when the caller supplied a name and no override exists —
        # never overwrite a manual rename.
        if cleaned_name:
            existing_name = s.query(TrackerName).filter_by(tracker_id=tid).first()
            if not existing_name:
                s.add(TrackerName(tracker_id=tid, display_name=cleaned_name))

        s.commit()


def get_tracker_archives() -> Dict[str, datetime]:
    """Return {tracker_id: archived_at} for every archived (soft-deleted) tracker."""
    with get_session() as s:
        rows = s.query(TrackerArchive.tracker_id, TrackerArchive.archived_at).all()
        return {tid: ts for tid, ts in rows}


def archive_tracker(tracker_id: str) -> bool:
    """Soft-delete a tracker by recording an archived_at timestamp.

    Idempotent: if the tracker is already archived, the existing timestamp
    is preserved. Returns True if a row was inserted or already existed.
    """
    tid = (tracker_id or "").strip()
    if not tid:
        return False
    with get_session() as s:
        existing = s.query(TrackerArchive).filter_by(tracker_id=tid).first()
        if existing:
            return True
        s.add(TrackerArchive(tracker_id=tid, archived_at=datetime.now()))
        s.commit()
        return True


def unarchive_tracker(tracker_id: str) -> bool:
    """Clear the archive flag for a tracker. Returns True if a row was removed."""
    tid = (tracker_id or "").strip()
    if not tid:
        return False
    with get_session() as s:
        existing = s.query(TrackerArchive).filter_by(tracker_id=tid).first()
        if not existing:
            return False
        s.delete(existing)
        s.commit()
        return True


def is_tracker_archived(tracker_id: str) -> bool:
    """Check whether a tracker has been soft-deleted."""
    tid = (tracker_id or "").strip()
    if not tid:
        return False
    with get_session() as s:
        return s.query(TrackerArchive).filter_by(tracker_id=tid).first() is not None


def get_inbox_messages(
    intent: str = "",
    direction: str = "",
    days: int = 30,
    limit: int = 200,
) -> List[Dict]:
    """List messages in the inbox, newest first, with optional filters."""
    cutoff = datetime.now() - timedelta(days=int(days or 30))
    with get_session() as s:
        q = s.query(ManyChatMessage).filter(ManyChatMessage.received_at >= cutoff)
        if intent:
            q = q.filter(ManyChatMessage.intent == intent.strip().lower())
        if direction:
            q = q.filter(ManyChatMessage.direction == direction.strip().lower())
        q = q.order_by(desc(ManyChatMessage.received_at)).limit(int(limit or 200))
        return [m.to_dict() for m in q.all()]


def get_subscriber_thread(subscriber_id: str, limit: int = 200) -> List[Dict]:
    """Return the full conversation with one subscriber, oldest first."""
    with get_session() as s:
        q = (
            s.query(ManyChatMessage)
            .filter_by(subscriber_id=subscriber_id)
            .order_by(ManyChatMessage.received_at)
            .limit(int(limit or 200))
        )
        return [m.to_dict() for m in q.all()]


def get_unclassified_messages(limit: int = 50) -> List[Dict]:
    """Return inbound messages that haven't been classified by Claude yet."""
    with get_session() as s:
        q = (
            s.query(ManyChatMessage)
            .filter(
                ManyChatMessage.direction == "in",
                ManyChatMessage.classified_at.is_(None),
            )
            .order_by(ManyChatMessage.received_at)
            .limit(int(limit or 50))
        )
        return [m.to_dict() for m in q.all()]


def inbox_intent_counts(days: int = 30) -> Dict[str, int]:
    """Count messages by intent over the last N days (for dashboard widgets)."""
    cutoff = datetime.now() - timedelta(days=int(days or 30))
    with get_session() as s:
        rows = (
            s.query(ManyChatMessage.intent, func.count(ManyChatMessage.id))
            .filter(
                ManyChatMessage.direction == "in",
                ManyChatMessage.received_at >= cutoff,
            )
            .group_by(ManyChatMessage.intent)
            .all()
        )
        return {(intent or "unclassified"): int(n) for intent, n in rows}
