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

    # TikTok scraper matching — for original sounds, the artist/track on TikTok
    # often differs from the real artist/song name. These fields store what
    # TikTok actually labels the sound so the scraper can match reliably.
    tt_artist_label = Column(String(255), default="")
    tt_track_name = Column(String(255), default="")

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
            "tt_artist_label": self.tt_artist_label or "",
            "tt_track_name": self.tt_track_name or "",
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
    niches = Column(JSONB, default=list)

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
            "niches": self.niches or [],
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
    display_name = Column(String(255), default="")
    niche = Column(String(100), default="")
    added_at = Column(DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "username": self.username or "",
            "display_name": self.display_name or "",
            "niche": self.niche or "",
            "added_at": self.added_at.isoformat() if self.added_at else "",
        }


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


class NetworkCreator(Base):
    """Creator network roster for outreach."""
    __tablename__ = "network_creators"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    platform = Column(String(20), default="tiktok")
    default_rate = Column(Float, default=0.0)
    default_posts = Column(Integer, default=1)
    paypal_email = Column(String(255), default="")
    manychat_subscriber_id = Column(String(100), default="")
    niches = Column(JSONB, default=list)
    notes = Column(Text, default="")
    added_at = Column(DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "username": self.username or "",
            "platform": self.platform or "tiktok",
            "default_rate": self.default_rate or 0.0,
            "default_posts": self.default_posts or 1,
            "paypal_email": self.paypal_email or "",
            "manychat_subscriber_id": self.manychat_subscriber_id or "",
            "niches": self.niches or [],
            "notes": self.notes or "",
            "added_at": self.added_at.isoformat() if self.added_at else "",
        }


class OutreachMessage(Base):
    """Outreach messages sent to creators for a campaign."""
    __tablename__ = "outreach_messages"
    __table_args__ = (
        UniqueConstraint("campaign_id", "username", name="uq_outreach_campaign_creator"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    rate_offered = Column(Float, default=0.0)
    posts_offered = Column(Integer, default=1)
    message_text = Column(Text, default="")
    status = Column(String(20), default="draft", index=True)  # draft|sent|responded|accepted|declined|expired
    sent_at = Column(DateTime, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    manychat_message_id = Column(String(100), default="")
    reply_text = Column(Text, default="")
    notes = Column(Text, default="")

    campaign = relationship("Campaign")

    def to_dict(self):
        return {
            "id": self.id,
            "campaign_id": self.campaign_id,
            "username": self.username or "",
            "rate_offered": self.rate_offered or 0.0,
            "posts_offered": self.posts_offered or 1,
            "message_text": self.message_text or "",
            "status": self.status or "draft",
            "sent_at": self.sent_at.isoformat() if self.sent_at else "",
            "responded_at": self.responded_at.isoformat() if self.responded_at else "",
            "manychat_message_id": self.manychat_message_id or "",
            "reply_text": self.reply_text or "",
            "notes": self.notes or "",
        }


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


# ===================================================================
# Internal creator groups (booked-by / niche / custom)
# ===================================================================

class InternalCreatorGroup(Base):
    """Named grouping of internal TikTok creators.

    Groups let us bucket creators by who books them (Johnny/Sam/Eric/etc.),
    by niche, by label (Warner Pages), or by any custom criteria. A creator
    can belong to many groups via InternalCreatorGroupMember.
    """
    __tablename__ = "internal_creator_groups"

    id = Column(Integer, primary_key=True)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    kind = Column(String(50), default="custom")  # booked_by | label | niche | custom
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

    members = relationship(
        "InternalCreatorGroupMember",
        back_populates="group",
        cascade="all, delete-orphan",
    )

    def to_dict(self, member_count: int | None = None):
        return {
            "id": self.id,
            "slug": self.slug or "",
            "title": self.title or "",
            "kind": self.kind or "custom",
            "sort_order": self.sort_order or 0,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "member_count": member_count if member_count is not None else len(self.members or []),
        }


class InternalCreatorGroupMember(Base):
    """Many-to-many join: an internal creator belongs to a group."""
    __tablename__ = "internal_creator_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "username", name="uq_internal_group_member"),
    )

    group_id = Column(
        Integer,
        ForeignKey("internal_creator_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    username = Column(String(255), primary_key=True)
    added_at = Column(DateTime, default=datetime.now)

    group = relationship("InternalCreatorGroup", back_populates="members")


# ===================================================================
# TidesTrackers (folder overlay for trackers that live in TidesTracker)
# ===================================================================
#
# Tracker data itself lives in TidesTracker's database (Supabase). The
# tables below only store the local "folder" overlay: groups and which
# tracker (by TidesTracker UUID) belongs to which group.

class TrackerGroup(Base):
    """A folder for grouping TidesTrackers (e.g. one per record label)."""
    __tablename__ = "tracker_groups"

    id = Column(Integer, primary_key=True)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

    assignments = relationship(
        "TrackerGroupAssignment",
        back_populates="group",
        cascade="all, delete-orphan",
    )

    def to_dict(self, tracker_count: int | None = None):
        return {
            "id": self.id,
            "slug": self.slug or "",
            "title": self.title or "",
            "sort_order": self.sort_order or 0,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "tracker_count": tracker_count if tracker_count is not None else 0,
        }


class TrackerGroupAssignment(Base):
    """Joins a TidesTracker (by its UUID) to a local TrackerGroup."""
    __tablename__ = "tracker_group_assignments"

    tracker_id = Column(String(64), primary_key=True)  # TidesTracker campaign UUID
    group_id = Column(
        Integer,
        ForeignKey("tracker_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.now)

    group = relationship("TrackerGroup", back_populates="assignments")


class TrackerName(Base):
    """Local display-name override for a TidesTracker.

    TidesTracker auto-names some campaigns generically ("Campaign"); we let
    users rename them inside Campaign Hub without round-tripping to
    TidesTracker. Stored as an overlay so the original name is recoverable
    by clearing the override.
    """
    __tablename__ = "tracker_names"

    tracker_id = Column(String(64), primary_key=True)  # TidesTracker campaign UUID
    display_name = Column(String(500), nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class TrackerCampaignLink(Base):
    """Links a TidesTracker (by UUID) to a Campaign Hub campaign (by slug)."""
    __tablename__ = "tracker_campaign_links"

    tracker_id = Column(String(64), primary_key=True)  # TidesTracker UUID
    campaign_slug = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now)


# ===================================================================
# ManyChat conversation log
# ===================================================================
#
# Every DM -- inbound and outbound -- between Rising Tides and a
# ManyChat subscriber is logged verbatim in manychat_messages. This is
# separate from OutreachMessage (which tracks per-campaign outreach
# state): a subscriber may have dozens of raw messages but only one
# OutreachMessage per campaign. The raw log powers the DM Inbox, Claude
# intent classification, and conversation-threaded views.
#
# Intents are tagged asynchronously by a Claude Haiku classification
# pass on inbound messages. The set is closed (not free-form) so the
# inbox can reliably filter and Claude can use the tag in later
# decisioning (e.g. which creators to draft follow-ups for).

class ManyChatMessage(Base):
    """A single verbatim DM between Rising Tides and a ManyChat subscriber."""
    __tablename__ = "manychat_messages"
    __table_args__ = (
        UniqueConstraint(
            "subscriber_id",
            "manychat_message_id",
            name="uq_manychat_message_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    subscriber_id = Column(String(100), nullable=False, index=True)
    username = Column(String(255), default="", index=True)
    platform = Column(String(20), default="tiktok")  # tiktok | instagram | messenger
    direction = Column(String(10), nullable=False, index=True)  # in | out
    text = Column(Text, default="")
    manychat_message_id = Column(String(100), default="")
    flow_ns = Column(String(100), default="")  # which ManyChat flow produced this
    campaign_slug = Column(String(255), default="", index=True)  # context if known
    received_at = Column(DateTime, default=datetime.now, index=True)

    # Claude intent classification (nullable -- set asynchronously)
    intent = Column(String(50), default="", index=True)
    intent_confidence = Column(Float, default=0.0)
    extracted = Column(JSONB, default=dict)  # {rate, email, paypal, song, ...}
    classified_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "subscriber_id": self.subscriber_id or "",
            "username": self.username or "",
            "platform": self.platform or "tiktok",
            "direction": self.direction or "in",
            "text": self.text or "",
            "manychat_message_id": self.manychat_message_id or "",
            "flow_ns": self.flow_ns or "",
            "campaign_slug": self.campaign_slug or "",
            "received_at": self.received_at.isoformat() if self.received_at else "",
            "intent": self.intent or "",
            "intent_confidence": self.intent_confidence or 0.0,
            "extracted": self.extracted or {},
            "classified_at": self.classified_at.isoformat() if self.classified_at else "",
        }
