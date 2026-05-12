"""Tests for campaign_manager.db CRUD helpers using the in-memory DB."""
from __future__ import annotations

from datetime import datetime


# Helper used by several tests.
def _make_campaign(db, slug="my_campaign", title="My Campaign", **extra):
    meta = {
        "title": title,
        "slug": slug,
        "artist": "Artist",
        "song": "Song",
        "official_sound": "https://tiktok.com/music/X-1234567890",
        "sound_id": "1234567890",
        "start_date": "2026-04-01",
        "budget": 1000.0,
        "status": "active",
        "platform": "tiktok",
        **extra,
    }
    db.save_campaign(slug, meta)
    return meta


class TestCampaignCrud:
    def test_save_and_fetch_campaign(self, db):
        _make_campaign(db)
        meta = db.get_campaign("my_campaign")
        assert meta is not None
        assert meta["title"] == "My Campaign"
        assert meta["artist"] == "Artist"
        assert meta["budget"] == 1000.0

    def test_get_missing_campaign_returns_none(self, db):
        assert db.get_campaign("doesnotexist") is None

    def test_campaign_exists(self, db):
        _make_campaign(db)
        assert db.campaign_exists("my_campaign") is True
        assert db.campaign_exists("nope") is False

    def test_get_campaign_id(self, db):
        _make_campaign(db)
        assert isinstance(db.get_campaign_id("my_campaign"), int)
        assert db.get_campaign_id("missing") is None

    def test_save_campaign_is_upsert(self, db):
        _make_campaign(db, title="Original")
        _make_campaign(db, title="Updated")
        assert db.get_campaign("my_campaign")["title"] == "Updated"

    def test_update_campaign_fields(self, db):
        _make_campaign(db)
        db.update_campaign_fields("my_campaign", {"completion_status": "completed"})
        assert db.get_campaign("my_campaign")["completion_status"] == "completed"

    def test_update_campaign_stats(self, db):
        _make_campaign(db)
        db.update_campaign_stats("my_campaign", total_views=999, total_likes=10)
        meta = db.get_campaign("my_campaign")
        assert meta["stats"]["total_views"] == 999
        assert meta["stats"]["total_likes"] == 10
        assert meta["stats"]["last_scrape"]

    def test_list_campaigns_filters_by_status(self, db):
        _make_campaign(db, slug="active1")
        _make_campaign(db, slug="paused1", status="paused")
        assert {c["slug"] for c in db.list_campaigns(status="active")} == {"active1"}
        assert {c["slug"] for c in db.list_campaigns(status="paused")} == {"paused1"}

    def test_list_campaigns_can_exclude_completed(self, db):
        _make_campaign(db, slug="a", completion_status="none")
        _make_campaign(db, slug="b", completion_status="completed")
        slugs = {c["slug"] for c in db.list_campaigns(exclude_completed=True)}
        assert slugs == {"a"}

    def test_empty_notion_id_normalized_to_null(self, db):
        """Avoid unique-constraint violations on multiple empty notion_page_ids."""
        _make_campaign(db, slug="a", notion_page_id="")
        _make_campaign(db, slug="b", notion_page_id="")
        # Both should coexist — the empty string was converted to NULL.
        assert db.campaign_exists("a")
        assert db.campaign_exists("b")


class TestCreatorCrud:
    def test_save_and_get_creators(self, db):
        _make_campaign(db)
        db.save_creators("my_campaign", [
            {"username": "alice", "posts_owed": 2, "total_rate": 500},
            {"username": "bob", "posts_owed": 1, "total_rate": 200, "paid": "yes"},
        ])
        creators = db.get_creators("my_campaign")
        assert len(creators) == 2
        by_name = {c["username"]: c for c in creators}
        assert by_name["alice"]["posts_owed"] == 2
        assert by_name["bob"]["paid"] == "yes"

    def test_save_creators_replaces_existing(self, db):
        _make_campaign(db)
        db.save_creators("my_campaign", [{"username": "alice"}])
        db.save_creators("my_campaign", [{"username": "bob"}])
        creators = db.get_creators("my_campaign")
        assert [c["username"] for c in creators] == ["bob"]

    def test_get_creators_for_missing_campaign(self, db):
        assert db.get_creators("missing") == []

    def test_save_creators_ignores_missing_campaign(self, db):
        # Should silently no-op — does not raise.
        db.save_creators("missing", [{"username": "x"}])


class TestPaypalMemory:
    def test_save_and_recall(self, db):
        db.save_paypal("alice", "alice@example.com")
        assert db.get_paypal("alice") == "alice@example.com"

    def test_lookup_is_case_insensitive(self, db):
        db.save_paypal("Alice", "alice@example.com")
        assert db.get_paypal("ALICE") == "alice@example.com"

    def test_missing_returns_empty(self, db):
        assert db.get_paypal("ghost") == ""

    def test_get_all_returns_full_map(self, db):
        db.save_paypal("a", "a@x")
        db.save_paypal("b", "b@x")
        assert db.get_all_paypal() == {"a": "a@x", "b": "b@x"}

    def test_save_ignores_empty(self, db):
        db.save_paypal("", "email@x")
        db.save_paypal("alice", "")
        assert db.get_all_paypal() == {}

    def test_save_updates_existing(self, db):
        db.save_paypal("alice", "a1@x")
        db.save_paypal("alice", "a2@x")
        assert db.get_paypal("alice") == "a2@x"


class TestInbox:
    def _item(self, **overrides):
        item = {
            "id": "abc-1",
            "created_at": datetime.now().isoformat(),
            "status": "pending",
            "source": "slack",
            "raw_message": "msg",
            "campaign_name": "n",
            "campaign_slug": "",
            "campaign_suggested": False,
            "creators": [],
            "notes": "",
        }
        item.update(overrides)
        return item

    def test_save_and_get_inbox(self, db):
        db.save_inbox_item(self._item(id="i1"))
        db.save_inbox_item(self._item(id="i2", status="approved"))
        all_items = db.get_inbox(status="all")
        assert {i["id"] for i in all_items} == {"i1", "i2"}

    def test_get_inbox_filters_by_status(self, db):
        db.save_inbox_item(self._item(id="i1", status="pending"))
        db.save_inbox_item(self._item(id="i2", status="approved"))
        assert [i["id"] for i in db.get_inbox(status="pending")] == ["i1"]
        assert [i["id"] for i in db.get_inbox(status="approved")] == ["i2"]

    def test_get_inbox_item_returns_dict(self, db):
        db.save_inbox_item(self._item(id="i1"))
        assert db.get_inbox_item("i1")["id"] == "i1"

    def test_get_missing_inbox_item(self, db):
        assert db.get_inbox_item("nope") is None

    def test_update_inbox_item(self, db):
        db.save_inbox_item(self._item(id="i1"))
        updated = db.update_inbox_item("i1", {"status": "approved"})
        assert updated is True
        assert db.get_inbox_item("i1")["status"] == "approved"

    def test_update_missing_returns_false(self, db):
        assert db.update_inbox_item("nope", {"status": "x"}) is False


class TestInternalCreators:
    def test_add_and_list(self, db):
        added = db.add_internal_creators(["alice", "@bob", "alice"])
        assert sorted(added) == ["@bob", "alice"] or sorted(added) == ["alice", "bob"]
        creators = db.get_internal_creators()
        assert "alice" in creators
        assert "bob" in creators or "@bob" not in creators

    def test_add_skips_duplicates(self, db):
        db.add_internal_creators(["alice"])
        added_second = db.add_internal_creators(["alice"])
        assert added_second == []

    def test_remove_internal_creator(self, db):
        db.add_internal_creators(["alice"])
        db.remove_internal_creator("alice")
        assert "alice" not in db.get_internal_creators()


class TestMatchedVideos:
    def test_replace_matched_videos_inserts_and_preserves_tracked_at(self, db):
        _make_campaign(db)
        # Initial scrape: two fresh URLs.
        db.replace_matched_videos("my_campaign", [
            {"url": "v1", "song": "S", "artist": "A", "views": 100},
            {"url": "v2", "song": "S", "artist": "A", "views": 50},
        ])
        videos = db.get_matched_videos("my_campaign")
        assert {v["url"] for v in videos} == {"v1", "v2"}

        # Manually mark v1 tracked via update (simulating human action).
        from campaign_manager.models import MatchedVideo
        with db.get_session() as s:
            s.query(MatchedVideo).filter_by(url="v1").update(
                {"tracked_at": datetime(2026, 1, 1)}
            )
            s.commit()

        # Second scrape: refresh stats. tracked_at must survive.
        db.replace_matched_videos("my_campaign", [
            {"url": "v1", "song": "S", "artist": "A", "views": 500},
        ])
        with db.get_session() as s:
            row = s.query(MatchedVideo).filter_by(url="v1").first()
            assert row.tracked_at == datetime(2026, 1, 1)
            assert row.views == 500

    def test_save_matched_videos_dedupes(self, db):
        _make_campaign(db)
        db.save_matched_videos("my_campaign", [
            {"url": "v1"},
            {"url": "v1"},
            {"url": "v2"},
        ])
        videos = db.get_matched_videos("my_campaign")
        assert {v["url"] for v in videos} == {"v1", "v2"}


class TestSyncedNotionIds:
    def test_collects_non_empty_notion_ids(self, db):
        _make_campaign(db, slug="a", notion_page_id="notion-1")
        _make_campaign(db, slug="b", notion_page_id="notion-2")
        _make_campaign(db, slug="c")  # no notion id
        assert db.get_synced_notion_ids() == {"notion-1", "notion-2"}


class TestCronLog:
    def test_create_and_finish(self, db):
        log_id = db.create_cron_log("campaign_refresh")
        assert isinstance(log_id, int)
        db.finish_cron_log(log_id, status="completed", summary={"runs": 1})
        logs = db.get_cron_logs(limit=10)
        assert logs[0]["status"] == "completed"
        assert logs[0]["summary"] == {"runs": 1}

    def test_get_by_id(self, db):
        log_id = db.create_cron_log("internal_scrape")
        assert db.get_cron_log_by_id(log_id)["job_type"] == "internal_scrape"
        assert db.get_cron_log_by_id(99999) is None


class TestNetworkCreators:
    def test_add_and_fetch(self, db):
        db.add_network_creator({"username": "alice", "default_rate": 100})
        creators = db.get_network_creators()
        assert len(creators) == 1
        assert creators[0]["username"] == "alice"

    def test_get_single(self, db):
        db.add_network_creator({"username": "alice"})
        assert db.get_network_creator("alice")["username"] == "alice"
        assert db.get_network_creator("ghost") is None

    def test_update(self, db):
        db.add_network_creator({"username": "alice", "default_rate": 100})
        db.update_network_creator("alice", {"default_rate": 500})
        assert db.get_network_creator("alice")["default_rate"] == 500

    def test_remove(self, db):
        db.add_network_creator({"username": "alice"})
        assert db.remove_network_creator("alice") is True
        assert db.get_network_creator("alice") is None
        assert db.remove_network_creator("alice") is False
