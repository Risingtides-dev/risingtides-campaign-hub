"""Tests for campaign_manager.services.matching."""
from __future__ import annotations

from campaign_manager.services.matching import (
    build_sound_sets,
    core_song_name,
    discover_original_sounds,
    match_videos,
    merge_matched_videos,
    update_creator_post_counts,
)


class TestCoreSongName:
    def test_lowercases_and_strips(self):
        assert core_song_name("  Fever Dream  ") == "fever dream"

    def test_strips_feat_parens(self):
        assert core_song_name("Fever Dream (feat. Other)") == "fever dream"

    def test_strips_ft_parens(self):
        assert core_song_name("Fever Dream (ft. Other Artist)") == "fever dream"

    def test_strips_feat_suffix(self):
        assert core_song_name("Fever Dream feat. Other") == "fever dream"

    def test_strips_trailing_promo(self):
        assert core_song_name("Fever Dream Promo") == "fever dream"

    def test_strips_trailing_remix(self):
        assert core_song_name("Fever Dream Remix") == "fever dream"


class TestBuildSoundSets:
    def test_collects_sound_id_and_additional_sounds(self):
        ids, _, _ = build_sound_sets(
            {"sound_id": "111", "additional_sounds": ["222", "333"]}
        )
        assert ids == {"111", "222", "333"}

    def test_skips_falsy_additional_sounds(self):
        ids, _, _ = build_sound_sets(
            {"sound_id": "111", "additional_sounds": ["", None, "222"]}
        )
        assert ids == {"111", "222"}

    def test_sound_keys_include_song_and_artist(self):
        _, keys, _ = build_sound_sets({"song": "Fever Dream", "artist": "Sam Barber"})
        assert "fever dream - sam barber" in keys

    def test_sound_keys_include_tt_labels_when_set(self):
        _, keys, _ = build_sound_sets({
            "song": "Fever Dream",
            "artist": "Sam Barber",
            "tt_track_name": "Original Sound",
            "tt_artist_label": "Music for the Soul",
        })
        assert "original sound - music for the soul" in keys

    def test_core_song_words_drops_short_tokens(self):
        _, _, words = build_sound_sets({"song": "I Am In Love"})
        # words shorter than 3 chars are filtered.
        assert "love" in words
        assert "i" not in words and "am" not in words


class TestMatchVideos:
    def test_matches_by_sound_id(self):
        videos = [
            {"url": "v1", "extracted_sound_id": "111"},
            {"url": "v2", "music_id": "222"},
            {"url": "v3", "extracted_sound_id": "999"},
        ]
        matched = match_videos(videos, {"111", "222"}, set(), set(), artist="x")
        assert [v["url"] for v in matched] == ["v1", "v2"]
        assert all(v["match_strategy"] == "sound_id" for v in matched)

    def test_strict_mode_excludes_fuzzy_matches(self):
        videos = [
            {"url": "v1", "extracted_sound_id": "111"},
            {"url": "v2", "song": "Fever Dream", "artist": "Sam Barber"},
        ]
        matched = match_videos(
            videos,
            sound_ids={"111"},
            sound_keys={"fever dream - sam barber"},
            core_song_words={"fever", "dream"},
            artist="Sam Barber",
            match_strategy="strict",
        )
        assert [v["url"] for v in matched] == ["v1"]

    def test_fuzzy_word_overlap_matches_with_correct_artist(self):
        videos = [
            {"url": "v1", "song": "Fever Dream Promo", "artist": "Sam Barber"},
            # Wrong artist — should be excluded.
            {"url": "v2", "song": "Fever Dream", "artist": "Other Artist"},
        ]
        matched = match_videos(
            videos,
            sound_ids=set(),
            sound_keys=set(),
            core_song_words={"fever", "dream"},
            artist="Sam Barber",
        )
        assert [v["url"] for v in matched] == ["v1"]
        assert matched[0]["match_strategy"] == "fuzzy_word_overlap"

    def test_match_fn_callback_is_used(self):
        videos = [
            {"url": "v1", "song": "Whatever", "artist": "X"},
        ]
        calls = []

        def fake_match(video, sound_ids, sound_keys):
            calls.append(video["url"])
            return True

        matched = match_videos(
            videos, set(), set(), set(), artist="X", match_fn=fake_match
        )
        assert calls == ["v1"]
        assert matched[0]["match_strategy"] == "music_id_or_song_key"


class TestDiscoverOriginalSounds:
    def test_strict_mode_disables_discovery(self):
        videos = [
            {
                "url": "v1",
                "account": "@sam",
                "song": "Original sound - sam",
                "artist": "Sam Barber",
                "extracted_sound_id": "newid",
            }
        ]
        additional, discovered = discover_original_sounds(
            videos, [], set(), ["sam"], "Sam Barber", match_strategy="strict"
        )
        assert additional == []
        assert discovered == []

    def test_discovers_new_sound_for_matching_creator_and_artist(self):
        videos = [
            {
                "url": "v1",
                "account": "@sam",
                "song": "original sound - sam",
                "artist": "Sam Barber",
                "extracted_sound_id": "newid",
            }
        ]
        additional, discovered = discover_original_sounds(
            videos, [], set(), ["sam"], "Sam Barber"
        )
        assert discovered == ["newid"]
        assert additional[0]["match_strategy"] == "discovered_original_sound"

    def test_skips_video_when_artist_mismatch(self):
        videos = [
            {
                "url": "v1",
                "account": "@sam",
                "song": "original sound - sam",
                "artist": "Random",
                "extracted_sound_id": "id1",
            }
        ]
        additional, discovered = discover_original_sounds(
            videos, [], set(), ["sam"], "Sam Barber"
        )
        assert additional == []
        assert discovered == []

    def test_skips_videos_already_matched(self):
        videos = [{"url": "v1"}]
        additional, _ = discover_original_sounds(
            videos, [{"url": "v1"}], set(), ["sam"], "Sam Barber"
        )
        assert additional == []


class TestMergeMatchedVideos:
    def test_updates_existing_video_stats(self):
        existing = [{"url": "u1", "views": 100, "likes": 10}]
        fresh = [{"url": "u1", "views": 500, "likes": 50}]
        merged, new_count = merge_matched_videos(existing, fresh)
        assert new_count == 0
        assert merged[0]["views"] == 500
        assert merged[0]["likes"] == 50

    def test_appends_new_videos(self):
        existing = [{"url": "u1", "views": 100}]
        fresh = [{"url": "u2", "views": 200}]
        merged, new_count = merge_matched_videos(existing, fresh)
        assert new_count == 1
        urls = {v["url"] for v in merged}
        assert urls == {"u1", "u2"}

    def test_backfills_sound_metadata_only_when_missing(self):
        existing = [{"url": "u1", "extracted_sound_id": "old"}]
        fresh = [{"url": "u1", "extracted_sound_id": "new"}]
        merged, _ = merge_matched_videos(existing, fresh)
        # Existing value takes precedence.
        assert merged[0]["extracted_sound_id"] == "old"

    def test_backfills_when_existing_field_blank(self):
        existing = [{"url": "u1", "extracted_sound_id": ""}]
        fresh = [{"url": "u1", "extracted_sound_id": "new"}]
        merged, _ = merge_matched_videos(existing, fresh)
        assert merged[0]["extracted_sound_id"] == "new"


class TestUpdateCreatorPostCounts:
    def test_counts_matches_per_account(self):
        creators = [{"username": "alice"}, {"username": "bob"}]
        videos = [
            {"account": "@alice"},
            {"account": "alice"},
            {"account": "@bob"},
        ]
        updated = update_creator_post_counts(creators, videos)
        by_user = {c["username"]: c for c in updated}
        assert by_user["alice"]["posts_matched"] == 2
        assert by_user["alice"]["posts_done"] == 2
        assert by_user["bob"]["posts_matched"] == 1

    def test_creators_without_matches_get_zero(self):
        creators = [{"username": "lonely"}]
        updated = update_creator_post_counts(creators, [])
        assert updated[0]["posts_matched"] == 0
        assert updated[0]["posts_done"] == 0

    def test_does_not_mutate_input(self):
        original = [{"username": "alice"}]
        update_creator_post_counts(original, [{"account": "@alice"}])
        assert "posts_matched" not in original[0]
