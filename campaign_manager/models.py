"""SQLAlchemy models for the Warner Campaign Manager."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, create_engine
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    name = Column(String(500))
    artist = Column(String(255), default="")
    song = Column(String(255), default="")
    official_sound = Column(Text, default="")
    sound_id = Column(String(50), default="")
    additional_sounds = Column(JSONB, default=list)
    cobrand_link = Column(Text, default="")
    start_date = Column(String(20), default="")
    budget = Column(Float, default=0.0)
    status = Column(String(20), default="active", index=True)
    platform = Column(String(20), default="tiktok")
    total_views = Column(Integer, default=0)
    total_likes = Column(Integer, default=0)
    last_scrape = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Cobrand integration
    cobrand_share_url = Column(Text, default="")
    cobrand_upload_url = Column(Text, default="")
    cobrand_promotion_id = Column(String(100), default="")
    cobrand_last_sync = Column(DateTime, nullable=True)
    cobrand_live_submissions = Column(Integer, default=0)
    cobrand_comments = Column(Integer, default=0)
    cobrand_status = Column(String(50), default="")

    # TidesTracker integration
    tracker_campaign_id = Column(String(100), nullable=True)
    tracker_url = Column(Text, default="")

    # Completion tracking (none -> booked -> completed, cycles)
    completion_status = Column(String(20), default="none")

    # Source tracking
    source = Column(String(20), default="manual")

    # Notion CRM integration
    notion_page_id = Column(String(100), nullable=True, unique=True)

    # Extended campaign metadata (from Notion CRM)
    insta_sound = Column(Text, default="")
    campaign_stage = Column(String(50), default="")
    round = Column(String(20), default="")
    label = Column(String(255), default="")
    project_lead = Column(JSONB, default=list)
    client_email = Column(String(255), default="")
    platform_split = Column(JSONB, default=dict)
    content_types = Column(JSONB, default=list)

    creators = relationship("Creator", back_populates="campaign", cascade="all, delete-orphan")
    matched_videos = relationship("MatchedVideo", back_populates="campaign", cascade="all, delete-orphan")
    scrape_logs = relationship("ScrapeLog", back_populates="campaign", cascade="all, delete-orphan")

    def to_meta_dict(self):
        """Return a dict matching the old campaign.json format for template compatibility."""
        return {
            "title": self.title or "",
            "name": self.name or self.title or "",
            "slug": self.slug,
            "artist": self.artist or "",
            "song": self.song or "",
            "official_sound": self.official_sound or "",
            "sound_id": self.sound_id or "",
            "additional_sounds": self.additional_sounds or [],
            "cobrand_link": self.cobrand_link or "",
            "start_date": self.start_date or "",
            "budget": self.budget or 0.0,
            "status": self.status or "active",
            "platform": self.platform or "tiktok",
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "stats": {
                "total_views": self.total_views or 0,
                "total_likes": self.total_likes or 0,
                "last_scrape": self.last_scrape.isoformat() if self.last_scrape else "",
            },
            "cobrand_share_url": self.cobrand_share_url or "",
            "cobrand_upload_url": self.cobrand_upload_url or "",
            "cobrand_promotion_id": self.cobrand_promotion_id or "",
            "cobrand_last_sync": self.cobrand_last_sync.isoformat() if self.cobrand_last_sync else "",
            "cobrand_live_submissions": self.cobrand_live_submissions or 0,
            "cobrand_comments": self.cobrand_comments or 0,
            "cobrand_status": self.cobrand_status or "",
            "tracker_campaign_id": self.tracker_campaign_id or "",
            "tracker_url": self.tracker_url or "",
            "source": self.source or "manual",
            "completion_status": self.completion_status or "none",
            "notion_page_id": self.notion_page_id or "",
            "insta_sound": self.insta_sound or "",
            "campaign_stage": self.campaign_stage or "",
            "round": self.round or "",
            "label": self.label or "",
            "project_lead": self.project_lead or [],
            "client_email": self.client_email or "",
            "platform_split": self.platform_split or {},
            "content_types": self.content_types or [],
        }


class Creator(Base):
    __tablename__ = "creators"
    __table_args__ = (
        UniqueConstraint("campaign_id", "username", name="uq_campaign_creator"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    posts_owed = Column(Integer, default=0)
    posts_done = Column(Integer, default=0)
    posts_matched = Column(Integer, default=0)
    total_rate = Column(Float, default=0.0)
    per_post_rate = Column(Float, default=0.0)
    paypal_email = Column(String(255), default="")
    paid = Column(String(10), default="no")
    payment_date = Column(String(20), default="")
    platform = Column(String(20), default="tiktok")
    added_date = Column(String(20), default="")
    status = Column(String(20), default="active")
    notes = Column(Text, default="")

    campaign = relationship("Campaign", back_populates="creators")

    def to_dict(self):
        return {
            "username": self.username or "",
            "posts_owed": self.posts_owed or 0,
            "posts_done": self.posts_done or 0,
            "posts_matched": self.posts_matched or 0,
            "total_rate": self.total_rate or 0.0,
            "per_post_rate": self.per_post_rate or 0.0,
            "paypal_email": self.paypal_email or "",
            "paid": self.paid or "no",
            "payment_date": self.payment_date or "",
            "platform": self.platform or "tiktok",
            "added_date": self.added_date or "",
            "status": self.status or "active",
            "notes": self.notes or "",
        }


class MatchedVideo(Base):
    __tablename__ = "matched_videos"
    __table_args__ = (
        UniqueConstraint("campaign_id", "url", name="uq_campaign_video"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(Text, nullable=False)
    song = Column(String(500), default="")
    artist = Column(String(255), default="")
    account = Column(String(255), default="")
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    upload_date = Column(String(20), default="")
    timestamp = Column(String(30), default="")
    music_id = Column(String(50), default="")
    platform = Column(String(20), default="tiktok")
    extracted_sound_id = Column(String(50), default="")
    extracted_song_title = Column(String(500), default="")

    campaign = relationship("Campaign", back_populates="matched_videos")

    def to_dict(self):
        return {
            "url": self.url or "",
            "song": self.song or "",
            "artist": self.artist or "",
            "account": self.account or "",
            "views": self.views or 0,
            "likes": self.likes or 0,
            "upload_date": self.upload_date or "",
            "timestamp": self.timestamp or "",
            "music_id": self.music_id or "",
            "platform": self.platform or "tiktok",
            "extracted_sound_id": self.extracted_sound_id or "",
            "extracted_song_title": self.extracted_song_title or "",
        }


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    last_scrape = Column(DateTime, nullable=False)
    accounts_scraped = Column(Integer, default=0)
    videos_checked = Column(Integer, default=0)
    new_matches = Column(Integer, default=0)
    total_matches = Column(Integer, default=0)

    campaign = relationship("Campaign", back_populates="scrape_logs")


class InboxItem(Base):
    __tablename__ = "inbox_items"

    id = Column(String(50), primary_key=True)
    created_at = Column(DateTime, default=datetime.now)
    status = Column(String(20), default="pending", index=True)
    source = Column(String(50), default="slack")
    raw_message = Column(Text, default="")
    campaign_name = Column(String(500), default="")
    campaign_slug = Column(String(255), default="")
    campaign_suggested = Column(Boolean, default=False)
    creators = Column(JSONB, default=list)
    notes = Column(Text, default="")
    approved_at = Column(DateTime, nullable=True)
    dismissed_at = Column(DateTime, nullable=True)
    creators_added = Column(JSONB, default=list)

    def to_dict(self):
        d = {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "status": self.status or "pending",
            "source": self.source or "slack",
            "raw_message": self.raw_message or "",
            "campaign_name": self.campaign_name or "",
            "campaign_slug": self.campaign_slug or "",
            "campaign_suggested": self.campaign_suggested or False,
            "creators": self.creators or [],
            "notes": self.notes or "",
        }
        if self.approved_at:
            d["approved_at"] = self.approved_at.isoformat()
            d["creators_added"] = self.creators_added or []
        if self.dismissed_at:
            d["dismissed_at"] = self.dismissed_at.isoformat()
        return d


class PaypalMemory(Base):
    __tablename__ = "paypal_memory"

    username = Column(String(255), primary_key=True)
    email = Column(String(255), nullable=False)


class InternalCreator(Base):
    __tablename__ = "internal_creators"

    username = Column(String(255), primary_key=True)
    added_at = Column(DateTime, default=datetime.now)


class InternalVideoCache(Base):
    """30-day rolling video cache for internal creators."""
    __tablename__ = "internal_video_cache"
    __table_args__ = (
        UniqueConstraint("username", "url", name="uq_internal_cache_video"),
    )

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    url = Column(Text, nullable=False)
    song = Column(String(500), default="")
    artist = Column(String(255), default="")
    account = Column(String(255), default="")
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    upload_date = Column(String(20), default="")
    timestamp = Column(String(30), default="")
    cached_at = Column(DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "url": self.url or "",
            "song": self.song or "",
            "artist": self.artist or "",
            "account": self.account or "",
            "views": self.views or 0,
            "likes": self.likes or 0,
            "upload_date": self.upload_date or "",
            "timestamp": self.timestamp or "",
        }


class InternalScrapeResult(Base):
    """Stores the last internal scrape results (replaces internal_last_scrape.json)."""
    __tablename__ = "internal_scrape_results"

    id = Column(Integer, primary_key=True)
    scraped_at = Column(DateTime, nullable=False)
    hours = Column(Integer, default=48)
    start_dt = Column(DateTime)
    end_dt = Column(DateTime)
    accounts_total = Column(Integer, default=0)
    accounts_successful = Column(Integer, default=0)
    accounts_failed = Column(Integer, default=0)
    total_videos = Column(Integer, default=0)
    total_videos_unfiltered = Column(Integer, default=0)
    unique_songs = Column(Integer, default=0)
    songs = Column(JSONB, default=list)


class CronLog(Base):
    """Logs each scheduled cron job run."""
    __tablename__ = "cron_log"

    id = Column(Integer, primary_key=True)
    job_type = Column(String(50), nullable=False, index=True)   # 'campaign_refresh' | 'internal_scrape'
    status = Column(String(20), nullable=False, index=True)     # 'running' | 'completed' | 'failed'
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    summary = Column(JSONB, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "job_type": self.job_type or "",
            "status": self.status or "",
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "finished_at": self.finished_at.isoformat() if self.finished_at else "",
            "summary": self.summary or {},
        }
