"""Tests for Instagram Reels scraping via Apify and its cron/dedupe wiring."""
from datetime import datetime
from unittest.mock import MagicMock, patch

from campaign_manager.services import apify_instagram as ig
from campaign_manager.services import scheduler
from campaign_manager.services.tides_tracker import _extract_post_id


LICENSED_REEL = {
    "id": "3994274242077263398",
    "shortCode": "Ddug0K2ggYm",
    "url": "https://www.instagram.com/p/Ddug0K2ggYm/",
    "productType": "clips",
    "timestamp": "2026-09-25T22:17:40.000Z",
    "ownerUsername": "SomeCreator",
    "videoViewCount": None,
    "videoPlayCount": 1269967,
    "likesCount": 70849,
    "caption": "new fav song",
    "musicInfo": {
        "artist_name": "Sabrina Carpenter",
        "song_name": "Espresso",
        "uses_original_audio": False,
        "audio_id": "28680826474891808",
    },
}


class TestNormalizeReel:
    def test_maps_to_shared_video_schema(self):
        v = ig.normalize_reel(LICENSED_REEL)
        assert v["url"] == "https://www.instagram.com/reel/Ddug0K2ggYm/"
        assert v["account"] == "@somecreator"
        assert v["song"] == "Espresso"
        assert v["artist"] == "Sabrina Carpenter"
        assert v["music_id"] == "28680826474891808"
        assert v["is_original_sound"] is False
        assert v["views"] == 1269967
        assert v["likes"] == 70849
        assert v["platform"] == "instagram"
        assert v["upload_date"] == "20260925"
        assert datetime.fromisoformat(v["timestamp"]).date().isoformat() == "2026-09-25"

    def test_non_reel_post_uses_p_link(self):
        v = ig.normalize_reel({**LICENSED_REEL, "productType": "feed"})
        assert v["url"] == "https://www.instagram.com/p/Ddug0K2ggYm/"

    def test_missing_music_and_timestamp(self):
        v = ig.normalize_reel({"shortCode": "abcde", "ownerUsername": "x"})
        assert v["song"] == "" and v["music_id"] == ""
        assert v["timestamp"] == ""  # excluded later by _filter_by_date


class TestCleanUsername:
    def test_variants(self):
        assert ig.clean_username("@Foo.Bar") == "foo.bar"
        assert ig.clean_username("https://www.instagram.com/foo_bar/?hl=en") == "foo_bar"
        assert ig.clean_username("  ") == ""


def _fake_client(items):
    client = MagicMock()
    client.actor.return_value.call.return_value = {"defaultDatasetId": "ds1"}
    client.dataset.return_value.list_items.return_value.items = items
    return client


class TestScrapeInstagramReels:
    def test_batches_all_creators_in_one_run_with_date_bound(self):
        client = _fake_client([LICENSED_REEL])
        with patch.object(ig, "_get_client", return_value=client):
            res = ig.scrape_instagram_reels(
                ["@SomeCreator", "quiet_one"], start_date=datetime(2026, 9, 1)
            )
        run_input = client.actor.return_value.call.call_args.kwargs["run_input"]
        assert run_input["username"] == ["quiet_one", "somecreator"]
        assert run_input["onlyPostsNewerThan"] == "2026-09-01"
        assert client.actor.return_value.call.call_count == 1
        assert len(res.videos) == 1
        assert res.outcomes["somecreator"]["status"] == "ok"
        assert res.outcomes["quiet_one"]["status"] == "empty"

    def test_skips_error_items(self):
        client = _fake_client([{"error": "private", "url": "x"}, LICENSED_REEL])
        with patch.object(ig, "_get_client", return_value=client):
            res = ig.scrape_instagram_reels(["somecreator"])
        assert len(res.videos) == 1

    def test_actor_failure_marks_all_error_without_raising(self):
        client = MagicMock()
        client.actor.return_value.call.side_effect = RuntimeError("boom")
        with patch.object(ig, "_get_client", return_value=client):
            res = ig.scrape_instagram_reels(["a", "b"])
        assert res.videos == []
        assert {o["status"] for o in res.outcomes.values()} == {"error"}
        assert res.errors

    def test_missing_token_does_not_raise(self):
        with patch.object(ig, "_get_client", side_effect=RuntimeError("APIFY_API_TOKEN is not set")):
            res = ig.scrape_instagram_reels(["a"])
        assert res.outcomes["a"]["status"] == "error"

    def test_no_usernames_skips_actor(self):
        with patch.object(ig, "_get_client") as gc:
            res = ig.scrape_instagram_reels(["", "@"])
        gc.assert_not_called()
        assert res.videos == []

    def test_supports_pydantic_style_run(self):
        client = _fake_client([LICENSED_REEL])
        run = MagicMock(spec=["default_dataset_id"])
        run.default_dataset_id = "ds9"
        client.actor.return_value.call.return_value = run
        with patch.object(ig, "_get_client", return_value=client):
            ig.scrape_instagram_reels(["somecreator"])
        client.dataset.assert_called_with("ds9")


class TestSharedKey:
    def test_instagram_is_namespaced_tiktok_is_bare(self):
        assert scheduler._shared_key("tiktok", "@Foo") == "foo"
        assert scheduler._shared_key("instagram", "@Foo") == "instagram:foo"


class TestRefreshSingleCampaignInstagram:
    def test_ig_creator_reel_is_matched_from_shared_cache(self):
        reel = ig.normalize_reel(LICENSED_REEL)
        tiktok_same_handle = {
            "url": "https://www.tiktok.com/@somecreator/video/123",
            "account": "@somecreator", "song": "Espresso",
            "artist": "Sabrina Carpenter", "timestamp": "2026-09-20T00:00:00+00:00",
            "platform": "tiktok",
        }
        shared = {"instagram:somecreator": [reel], "somecreator": [tiktok_same_handle]}
        creators = [{"username": "SomeCreator", "platform": "instagram", "status": "active"}]
        meta = {"song": "Espresso", "artist": "Sabrina Carpenter", "start_date": "2026-09-01"}

        saved = {}
        with patch.object(scheduler, "_db") as db:
            db.get_creators.return_value = creators
            db.get_matched_videos.return_value = []
            db.save_matched_videos.side_effect = lambda slug, vids: saved.update(v=vids)
            result = scheduler._refresh_single_campaign("camp", meta, shared_videos=shared)

        assert result["new_matches"] == 1
        # The TikTok with the same handle must not leak into an IG-only booking.
        assert result["videos_checked"] == 1


class TestExtractPostId:
    def test_instagram_link_variants_share_one_id(self):
        ids = {
            _extract_post_id("https://www.instagram.com/reel/Ddug0K2ggYm/"),
            _extract_post_id("https://instagram.com/p/Ddug0K2ggYm/?igsh=abc"),
            _extract_post_id("https://www.instagram.com/somecreator/reel/Ddug0K2ggYm"),
            _extract_post_id("https://www.instagram.com/reels/Ddug0K2ggYm/"),
        }
        assert ids == {"ig:Ddug0K2ggYm"}

    def test_tiktok_unchanged_and_profile_links_ignored(self):
        assert _extract_post_id("https://www.tiktok.com/@a/video/7412345678901234567") == "7412345678901234567"
        assert _extract_post_id("https://www.instagram.com/somecreator/") == ""
