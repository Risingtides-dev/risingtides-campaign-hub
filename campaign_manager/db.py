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

from sqlalchemy import create_engine, desc
from sqlalchemy.orm import Session, sessionmaker

from campaign_manager.models import (
    Base, Campaign, Creator, MatchedVideo, ScrapeLog,
    InboxItem, PaypalMemory, InternalCreator, InternalVideoCache,
    InternalScrapeResult, CronLog,
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
        c.source = meta.get("source", c.source or "manual")
        c.completion_status = meta.get("completion_status", c.completion_status or "none")
        # Use None instead of "" so the unique constraint allows multiple unset values
        raw_notion_id = meta.get("notion_page_id", c.notion_page_id)
        c.notion_page_id = raw_notion_id if raw_notion_id else None
        c.insta_sound = meta.get("insta_sound", c.insta_sound or "")
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
            "songs": result.songs or [],
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
