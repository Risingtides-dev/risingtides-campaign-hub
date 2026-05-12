"""Tests for campaign_manager.utils.helpers."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from campaign_manager.utils.helpers import (
    slugify,
    load_json,
    save_json,
    campaign_title,
    parse_sort_datetime,
    extract_sound_id,
    is_original_sound,
)


class TestSlugify:
    def test_lowercases_and_replaces_spaces_with_underscores(self):
        assert slugify("Hello World") == "hello_world"

    def test_strips_special_characters(self):
        assert slugify("Artist - Song (feat. Other)") == "artist_song_feat_other"

    def test_collapses_multiple_separators(self):
        assert slugify("a   b---c") == "a_b_c"

    def test_strips_surrounding_whitespace(self):
        assert slugify("   Hello   ") == "hello"

    def test_preserves_alphanumerics(self):
        assert slugify("Track 123") == "track_123"


class TestLoadJson:
    def test_returns_empty_dict_for_missing_file(self, tmp_path: Path):
        assert load_json(tmp_path / "nope.json") == {}

    def test_reads_valid_json(self, tmp_path: Path):
        p = tmp_path / "data.json"
        p.write_text('{"a": 1, "b": "x"}', encoding="utf-8")
        assert load_json(p) == {"a": 1, "b": "x"}

    def test_returns_empty_dict_for_invalid_json(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("not json at all", encoding="utf-8")
        assert load_json(p) == {}


class TestSaveJson:
    def test_writes_pretty_printed_json(self, tmp_path: Path):
        p = tmp_path / "out.json"
        save_json(p, {"x": 1})
        assert json.loads(p.read_text()) == {"x": 1}

    def test_serializes_datetime_via_default_str(self, tmp_path: Path):
        p = tmp_path / "dt.json"
        save_json(p, {"when": datetime(2026, 1, 2, 3, 4, 5)})
        loaded = json.loads(p.read_text())
        assert "2026-01-02" in loaded["when"]


class TestCampaignTitle:
    def test_returns_title_when_present(self):
        assert campaign_title({"title": "X", "name": "Y"}) == "X"

    def test_falls_back_to_name(self):
        assert campaign_title({"name": "Only Name"}) == "Only Name"

    def test_falls_back_to_default(self):
        assert campaign_title({}) == "Untitled Campaign"


class TestParseSortDatetime:
    def test_prefers_created_at(self):
        dt = parse_sort_datetime({"created_at": "2026-01-01T10:00:00"})
        assert dt == datetime(2026, 1, 1, 10, 0, 0)

    def test_falls_back_to_iso_start_date(self):
        dt = parse_sort_datetime({"start_date": "2026-03-15"})
        assert dt == datetime(2026, 3, 15)

    def test_falls_back_to_slash_start_date(self):
        dt = parse_sort_datetime({"start_date": "03/15/2026"})
        assert dt == datetime(2026, 3, 15)

    def test_returns_min_on_empty(self):
        assert parse_sort_datetime({}) == datetime.min

    def test_returns_min_on_garbage_dates(self):
        assert parse_sort_datetime({"start_date": "not a date"}) == datetime.min


class TestExtractSoundId:
    def test_returns_raw_numeric_id_unchanged(self):
        assert extract_sound_id("7602731070429858591") == "7602731070429858591"

    def test_extracts_from_music_url(self):
        url = "https://www.tiktok.com/music/FEVER-DREAM-7602731070429858591"
        assert extract_sound_id(url) == "7602731070429858591"

    def test_extracts_from_music_url_with_query_string(self):
        url = "https://www.tiktok.com/music/Song-1234567890123456?lang=en"
        assert extract_sound_id(url) == "1234567890123456"

    def test_extracts_long_numeric_id_from_arbitrary_string(self):
        assert extract_sound_id("foo 7602731070429858591 bar") == "7602731070429858591"

    def test_short_url_resolution_is_attempted(self):
        """Short URLs should trigger redirect resolution."""
        short_url = "https://www.tiktok.com/t/ABCDEFG/"
        resolved = (
            "https://www.tiktok.com/music/Song-9999999999999999999"
        )
        with patch(
            "campaign_manager.utils.helpers.resolve_tiktok_short_url",
            return_value=resolved,
        ) as resolver:
            result = extract_sound_id(short_url)
            resolver.assert_called_once_with(short_url)
            assert result == "9999999999999999999"

    def test_video_url_falls_back_to_html_extraction(self):
        url = "https://www.tiktok.com/@user/video/7000000000000000000"
        with patch(
            "campaign_manager.utils.helpers.extract_sound_id_from_html",
            return_value=("8888888888888888888", "Some Song"),
        ):
            # html extractor wins over the raw long-number fallback
            assert extract_sound_id(url) == "8888888888888888888"

    def test_returns_input_when_no_id_present(self):
        assert extract_sound_id("just some text") == "just some text"


class TestIsOriginalSound:
    def test_original_sound_prefix(self):
        assert is_original_sound("Original Sound - @user", "@user") is True

    def test_blank_song_is_original(self):
        assert is_original_sound("", "") is True

    def test_unknown_is_original(self):
        assert is_original_sound("Unknown", "") is True

    def test_localized_son_original(self):
        assert is_original_sound("Son Original - @user", "@user") is True

    def test_localized_suara_asli(self):
        assert is_original_sound("Suara Asli - @user", "@user") is True

    def test_real_song_is_not_original(self):
        assert is_original_sound("Fever Dream", "Sam Barber") is False
