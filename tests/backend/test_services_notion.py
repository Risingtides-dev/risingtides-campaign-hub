"""Tests for campaign_manager.services.notion."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from campaign_manager.services import notion as notion_module
from campaign_manager.services.notion import (
    _get_date,
    _get_email,
    _get_multi_select,
    _get_number,
    _get_rich_text,
    _get_select,
    _get_status,
    _get_title,
    _get_url,
    _parse_platform_split,
    query_new_clients,
    resolve_data_source_id,
)


class TestPropExtractors:
    def test_title_concatenates_segments(self):
        assert _get_title({"title": [
            {"plain_text": "Hello "},
            {"plain_text": "World"},
        ]}) == "Hello World"

    def test_title_empty_when_missing(self):
        assert _get_title({}) == ""

    def test_rich_text_concatenates(self):
        assert _get_rich_text({"rich_text": [
            {"plain_text": "Foo"},
            {"plain_text": "Bar"},
        ]}) == "FooBar"

    def test_select_returns_name(self):
        assert _get_select({"select": {"name": "Option A"}}) == "Option A"

    def test_select_empty_when_null(self):
        assert _get_select({"select": None}) == ""

    def test_multi_select_returns_names(self):
        prop = {"multi_select": [{"name": "x"}, {"name": "y"}]}
        assert _get_multi_select(prop) == ["x", "y"]

    def test_status_returns_name(self):
        assert _get_status({"status": {"name": "Client"}}) == "Client"

    def test_status_empty_when_none(self):
        assert _get_status({"status": None}) == ""

    def test_url_passthrough(self):
        assert _get_url({"url": "https://x"}) == "https://x"

    def test_url_handles_none(self):
        assert _get_url({"url": None}) == ""

    def test_date_returns_start(self):
        assert _get_date({"date": {"start": "2026-03-01"}}) == "2026-03-01"

    def test_date_handles_null(self):
        assert _get_date({"date": None}) == ""

    def test_number_returns_value(self):
        assert _get_number({"number": 100}) == 100

    def test_number_handles_missing(self):
        assert _get_number({}) is None

    def test_email_handles_none(self):
        assert _get_email({"email": None}) == ""


class TestParsePlatformSplit:
    def test_parses_both_platforms(self):
        result = _parse_platform_split(["70%"], ["30%"])
        assert result == {"tiktok": 70, "instagram": 30}

    def test_handles_empty_lists(self):
        assert _parse_platform_split([], []) == {}

    def test_skips_unparseable_values(self):
        result = _parse_platform_split(["bad"], ["50%"])
        # tiktok gets dropped (couldn't parse), instagram present
        assert "tiktok" not in result
        assert result["instagram"] == 50


class TestResolveDataSourceId:
    @pytest.fixture(autouse=True)
    def _clean_cache(self, monkeypatch):
        monkeypatch.setattr(notion_module, "_data_source_cache", {})
        monkeypatch.delenv("MY_DS_OVERRIDE", raising=False)

    def test_env_override_wins_without_http(self, monkeypatch):
        monkeypatch.setenv("MY_DS_OVERRIDE", "ds-pinned")
        with patch("campaign_manager.services.notion.requests.get") as get:
            assert resolve_data_source_id("db-1", env_override="MY_DS_OVERRIDE") == "ds-pinned"
            get.assert_not_called()

    def test_picks_first_listed_source_and_caches(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "data_sources": [
                {"id": "ds-real", "name": "Rising Tides CRM"},
                {"id": "ds-empty", "name": "New data source"},
            ]
        }
        with patch("campaign_manager.services.notion.requests.get", return_value=resp) as get:
            assert resolve_data_source_id("db-1") == "ds-real"
            # Second call hits the cache, not the API
            assert resolve_data_source_id("db-1") == "ds-real"
            assert get.call_count == 1

    def test_returns_empty_on_http_error(self):
        resp = MagicMock(status_code=404, text="not found")
        with patch("campaign_manager.services.notion.requests.get", return_value=resp):
            assert resolve_data_source_id("db-1") == ""

    def test_returns_empty_when_no_sources(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data_sources": []}
        with patch("campaign_manager.services.notion.requests.get", return_value=resp):
            assert resolve_data_source_id("db-1") == ""


class TestQueryNewClients:
    @pytest.fixture(autouse=True)
    def _pin_data_source(self, monkeypatch):
        # Pin the CRM data source so query_new_clients never issues the
        # resolution GET — these tests only stub requests.post.
        monkeypatch.setenv("NOTION_CRM_DATA_SOURCE_ID", "ds-crm-test")
        monkeypatch.setattr(notion_module, "_data_source_cache", {})

    def test_returns_empty_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("NOTION_API_KEY", raising=False)
        assert query_new_clients(set()) == []

    def test_queries_the_pinned_data_source(self, monkeypatch):
        monkeypatch.setenv("NOTION_API_KEY", "test-key")
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"results": []}
        with patch("campaign_manager.services.notion.requests.post", return_value=resp) as post:
            query_new_clients(set())
        assert post.call_args[0][0].endswith("/data_sources/ds-crm-test/query")

    def test_returns_empty_on_non_200(self, monkeypatch):
        monkeypatch.setenv("NOTION_API_KEY", "test-key")
        resp = MagicMock(status_code=500)
        with patch("campaign_manager.services.notion.requests.post", return_value=resp):
            assert query_new_clients(set()) == []

    def test_skips_already_synced_pages(self, monkeypatch):
        monkeypatch.setenv("NOTION_API_KEY", "test-key")
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "results": [
                {"id": "page-known", "properties": {}},
            ]
        }
        with patch("campaign_manager.services.notion.requests.post", return_value=resp):
            assert query_new_clients({"page-known"}) == []

    def test_builds_campaign_from_notion_page(self, monkeypatch):
        monkeypatch.setenv("NOTION_API_KEY", "test-key")
        page = {
            "id": "page-1",
            "properties": {
                "Artist Name": {"title": [{"plain_text": "Sam Barber"}]},
                "Song Name": {"rich_text": [{"plain_text": "Fever Dream"}]},
                "TikTok Sound Link": {
                    "url": "https://www.tiktok.com/music/Fever-1234567890123456"
                },
                "Insta Sound Link": {"url": ""},
                "Co Brand Link": {"url": "https://cobrand.com/promo/x"},
                "Desired Start Date": {"date": {"start": "2026-04-01"}},
                "Media Spend": {"number": 5000},
                "Campaign Stage": {"status": {"name": "Active"}},
                "Round": {"select": {"name": "R1"}},
                "Label/Distro Partner": {
                    "rich_text": [{"plain_text": "Warner"}]
                },
                "Project Lead": {"multi_select": [{"name": "Johnny"}]},
                "Key Contact Email": {"email": "client@example.com"},
                "Types of Content Creators": {
                    "multi_select": [{"name": "UGC"}]
                },
                "TikTok": {"multi_select": [{"name": "70%"}]},
                "Instagram": {"multi_select": [{"name": "30%"}]},
            },
        }
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"results": [page]}
        with patch("campaign_manager.services.notion.requests.post", return_value=resp):
            results = query_new_clients(set())

        assert len(results) == 1
        camp = results[0]
        assert camp["notion_page_id"] == "page-1"
        assert camp["title"] == "Sam Barber - Fever Dream"
        assert camp["slug"] == "sam_barber_fever_dream"
        assert camp["sound_id"] == "1234567890123456"
        assert camp["budget"] == 5000.0
        assert camp["source"] == "notion"
        assert camp["platform_split"] == {"tiktok": 70, "instagram": 30}
        assert camp["project_lead"] == ["Johnny"]

    def test_falls_back_to_artist_only_title(self, monkeypatch):
        monkeypatch.setenv("NOTION_API_KEY", "test-key")
        page = {
            "id": "page-2",
            "properties": {
                "Artist Name": {"title": [{"plain_text": "Solo Artist"}]},
            },
        }
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"results": [page]}
        with patch("campaign_manager.services.notion.requests.post", return_value=resp):
            results = query_new_clients(set())
        assert results[0]["title"] == "Solo Artist"

    def test_falls_back_to_untitled_when_artist_and_song_missing(self, monkeypatch):
        monkeypatch.setenv("NOTION_API_KEY", "test-key")
        page = {"id": "page-abcdefgh-rest", "properties": {}}
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"results": [page]}
        with patch("campaign_manager.services.notion.requests.post", return_value=resp):
            results = query_new_clients(set())
        assert results[0]["title"].startswith("Untitled (")
