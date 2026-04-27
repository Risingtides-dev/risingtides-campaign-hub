"""Database access layer for the Warner Campaign Manager.

Replaces all JSON/CSV file I/O with Postgres queries via SQLAlchemy.
Falls back to file-based storage if DATABASE_URL is not set.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")

from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import Session, sessionmaker

from campaign_manager.models import (
    Base, Campaign, Creator, MatchedVideo, ScrapeLog,
    InboxItem, PaypalMemory, InternalCreator, InternalVideoCache,
    InternalScrapeResult, CronLog, NetworkCreator, OutreachMessage,
    InternalCreatorGroup, InternalCreatorGroupMember,
    TrackerGroup, TrackerGroupAssignment, TrackerName, TrackerCampaignLink,
    ManyChatMessage,
)

_engine = None
_SessionLocal = None


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

    # Create all tables
    Base.metadata.create_all(_engine)

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

    # manychat_messages table is created by Base.metadata.create_all above.
    # No migration block needed -- it's additive only.

    return True


def is_active() -> bool:
    """Check if database is initialized and active."""
    return _engine is not None


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
        c.status = meta.get("status", "active")
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


def list_campaigns(status: str = "active") -> List[Dict]:
    """List all campaigns with the given status, returning meta dicts."""
    with get_session() as s:
        query = s.query(Campaign)
        if status:
            query = query.filter_by(status=status)
        campaigns = query.all()
        return [c.to_meta_dict() for c in campaigns]


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
    """Replace all matched videos for a campaign (full overwrite)."""
    with get_session() as s:
        c = s.query(Campaign).filter_by(slug=slug).first()
        if not c:
            return

        s.query(MatchedVideo).filter_by(campaign_id=c.id).delete()

        seen = set()
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
    """Merge new videos into cache, dedupe by URL, prune >30 days old."""
    cutoff = datetime.now() - timedelta(days=30)
    uname = username.lower()

    with get_session() as s:
        # Prune old entries
        s.query(InternalVideoCache).filter(
            InternalVideoCache.username == uname,
            InternalVideoCache.cached_at < cutoff,
        ).delete(synchronize_session=False)

        # Get existing URLs
        existing_urls = {v.url for v in
                         s.query(InternalVideoCache).filter_by(username=uname).all()}

        for vd in new_videos:
            url = vd.get("url", "")
            if url and url not in existing_urls:
                s.add(InternalVideoCache(
                    username=uname,
                    url=url,
                    song=vd.get("song", ""),
                    artist=vd.get("artist", ""),
                    account=vd.get("account", ""),
                    views=int(vd.get("views", 0) or 0),
                    likes=int(vd.get("likes", 0) or 0),
                    upload_date=vd.get("upload_date", ""),
                    timestamp=str(vd.get("timestamp", "")),
                    cached_at=datetime.now(),
                ))
                existing_urls.add(url)

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
    """
    group = get_internal_group(group_id)
    if not group:
        return None

    members = get_group_members(group_id)
    if not members:
        return {
            "group": group,
            "days": int(days),
            "total_posts": 0,
            "total_views": 0,
            "total_likes": 0,
            "creators": [],
            "top_songs": [],
        }

    members_lower = [m.lower() for m in members]
    cutoff = _cutoff_yyyymmdd(days)

    with get_session() as s:
        videos = (
            s.query(InternalVideoCache)
            .filter(
                func.lower(InternalVideoCache.username).in_(members_lower),
                InternalVideoCache.upload_date >= cutoff,
            )
            .all()
        )

        # Per-creator rollup
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


def set_tracker_campaign_link(tracker_id: str, campaign_slug: Optional[str]) -> None:
    """Link tracker to a campaign by slug, or clear if slug is None/empty."""
    tid = (tracker_id or "").strip()
    if not tid:
        return
    slug = (campaign_slug or "").strip()
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
        s.commit()


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
