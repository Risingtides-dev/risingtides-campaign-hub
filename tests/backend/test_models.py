"""Tests for SQLAlchemy model ``to_dict`` / ``to_meta_dict`` serializers.

These verify the contract that the API depends on: every model exposes a
plain-dict shape with sensible defaults when columns are unset.
"""
from __future__ import annotations

from datetime import datetime

from campaign_manager.models import (
    Campaign,
    Creator,
    CronLog,
    InboxItem,
    InternalCreator,
    InternalCreatorGroup,
    InternalVideoCache,
    ManyChatMessage,
    MatchedVideo,
    NetworkCreator,
    OutreachMessage,
    TrackerGroup,
)


class TestCampaignToMetaDict:
    def test_defaults_are_filled_for_empty_campaign(self):
        c = Campaign(slug="x", title="Title")
        meta = c.to_meta_dict()
        assert meta["slug"] == "x"
        assert meta["title"] == "Title"
        assert meta["status"] == "active"
        assert meta["platform"] == "tiktok"
        assert meta["match_strategy"] == "fuzzy"
        assert meta["completion_status"] == "none"
        assert meta["source"] == "manual"
        assert meta["stats"] == {
            "total_views": 0,
            "total_likes": 0,
            "last_scrape": "",
        }
        assert meta["additional_sounds"] == []
        assert meta["project_lead"] == []
        assert meta["platform_split"] == {}
        assert meta["content_types"] == []

    def test_serializes_datetimes_iso(self):
        c = Campaign(
            slug="x",
            title="T",
            last_scrape=datetime(2026, 1, 2, 3, 4, 5),
            created_at=datetime(2026, 1, 1),
        )
        meta = c.to_meta_dict()
        assert meta["stats"]["last_scrape"] == "2026-01-02T03:04:05"
        assert meta["created_at"] == "2026-01-01T00:00:00"

    def test_falls_back_name_to_title(self):
        c = Campaign(slug="x", title="My Title")
        assert c.to_meta_dict()["name"] == "My Title"


class TestCreatorToDict:
    def test_default_fields(self):
        cr = Creator(campaign_id=1, username="alice")
        d = cr.to_dict()
        assert d["username"] == "alice"
        assert d["posts_owed"] == 0
        assert d["paid"] == "no"
        assert d["status"] == "active"
        assert d["platform"] == "tiktok"
        assert d["niches"] == []

    def test_populated_fields(self):
        cr = Creator(
            campaign_id=1,
            username="bob",
            posts_owed=3,
            total_rate=750.0,
            per_post_rate=250.0,
            paid="yes",
            niches=["fashion"],
        )
        d = cr.to_dict()
        assert d["posts_owed"] == 3
        assert d["total_rate"] == 750.0
        assert d["niches"] == ["fashion"]


class TestMatchedVideoToDict:
    def test_serializes_dates(self):
        v = MatchedVideo(
            campaign_id=1,
            url="https://tiktok.com/v/1",
            first_seen_at=datetime(2026, 5, 1),
            tracked_at=datetime(2026, 5, 2),
            dismissed_at=datetime(2026, 5, 3),
        )
        d = v.to_dict()
        assert d["first_seen_at"] == "2026-05-01T00:00:00"
        assert d["tracked_at"] == "2026-05-02T00:00:00"
        assert d["dismissed_at"] == "2026-05-03T00:00:00"

    def test_blank_strings_when_dates_unset(self):
        v = MatchedVideo(campaign_id=1, url="x")
        d = v.to_dict()
        assert d["first_seen_at"] == ""
        assert d["tracked_at"] == ""
        assert d["dismissed_at"] == ""


class TestInboxItemToDict:
    def test_pending_item_omits_approval_fields(self):
        item = InboxItem(id="i1", raw_message="m", creators=[])
        d = item.to_dict()
        assert "approved_at" not in d
        assert "dismissed_at" not in d

    def test_approved_includes_creators_added(self):
        item = InboxItem(
            id="i1",
            approved_at=datetime(2026, 1, 1),
            creators_added=["alice"],
        )
        d = item.to_dict()
        assert d["approved_at"] == "2026-01-01T00:00:00"
        assert d["creators_added"] == ["alice"]

    def test_dismissed_at_serialized(self):
        item = InboxItem(id="i1", dismissed_at=datetime(2026, 1, 1))
        d = item.to_dict()
        assert d["dismissed_at"] == "2026-01-01T00:00:00"


class TestSmallModels:
    def test_internal_creator_to_dict(self):
        ic = InternalCreator(username="solo", display_name="Solo")
        d = ic.to_dict()
        assert d["username"] == "solo"
        assert d["display_name"] == "Solo"

    def test_internal_video_cache_to_dict(self):
        v = InternalVideoCache(username="u", url="http://x", views=10)
        d = v.to_dict()
        assert d["views"] == 10
        assert d["url"] == "http://x"

    def test_network_creator_to_dict(self):
        nc = NetworkCreator(username="nc1", platform="instagram")
        d = nc.to_dict()
        assert d["platform"] == "instagram"
        assert d["default_posts"] == 1

    def test_outreach_message_to_dict(self):
        om = OutreachMessage(
            campaign_id=1, username="u", sent_at=datetime(2026, 1, 1)
        )
        d = om.to_dict()
        assert d["status"] == "draft"
        assert d["sent_at"] == "2026-01-01T00:00:00"

    def test_cron_log_to_dict_handles_missing_finished_at(self):
        log = CronLog(
            job_type="campaign_refresh",
            status="running",
            started_at=datetime(2026, 1, 1),
        )
        d = log.to_dict()
        assert d["finished_at"] == ""

    def test_internal_group_to_dict(self):
        g = InternalCreatorGroup(slug="g1", title="Group", kind="custom")
        d = g.to_dict(member_count=5)
        assert d["slug"] == "g1"
        assert d["member_count"] == 5
        assert d["tracker_id"] == ""  # unset cluster->tracker link defaults to ""

    def test_internal_group_to_dict_exposes_tracker_id(self):
        g = InternalCreatorGroup(slug="sam_barber", title="Sam Barber",
                                 kind="cluster", tracker_id="1bf00979-0d71")
        assert g.to_dict()["tracker_id"] == "1bf00979-0d71"

    def test_tracker_group_to_dict(self):
        g = TrackerGroup(slug="t1", title="Trackers")
        d = g.to_dict(tracker_count=2)
        assert d["tracker_count"] == 2

    def test_manychat_message_to_dict(self):
        m = ManyChatMessage(
            subscriber_id="sub1",
            direction="in",
            text="hi",
            received_at=datetime(2026, 1, 1),
        )
        d = m.to_dict()
        assert d["direction"] == "in"
        assert d["text"] == "hi"
        assert d["received_at"] == "2026-01-01T00:00:00"
