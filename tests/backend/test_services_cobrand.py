"""Tests for campaign_manager.services.cobrand."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from campaign_manager.services.cobrand import (
    extract_performance_data,
    fetch_cobrand_stats,
    parse_next_data,
)


def _build_next_data_html(promotion: dict) -> str:
    payload = {"props": {"pageProps": {"promotion": promotion}}}
    return (
        "<html><head>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        "</head><body></body></html>"
    )


class TestParseNextData:
    def test_returns_none_when_script_tag_missing(self):
        assert parse_next_data("<html><body>no script</body></html>") is None

    def test_returns_none_for_invalid_json(self):
        html = (
            '<script id="__NEXT_DATA__" type="application/json">not json</script>'
        )
        assert parse_next_data(html) is None

    def test_returns_none_when_promotion_key_missing(self):
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {}}})
            + "</script>"
        )
        assert parse_next_data(html) is None

    def test_parses_promotion_into_performance_dict(self):
        promotion = {
            "id": "promo-1",
            "name": "Test Promo",
            "status": "live",
            "live_submission_count": 42,
            "draft_submission_count": 8,
            "comment_count": 100,
            "activation_count": 1,
        }
        result = parse_next_data(_build_next_data_html(promotion))
        assert result["promotion_id"] == "promo-1"
        assert result["live_submission_count"] == 42
        assert result["comment_count"] == 100


class TestExtractPerformanceData:
    def test_strips_financial_fields(self):
        promotion = {
            "id": "p1",
            "budget": 99999,
            "spend": 12345,
            "spend_committed": 6789,
            "owner_auth0_user": "auth0|x",
        }
        result = extract_performance_data(promotion)
        # Performance-only fields appear.
        assert result["promotion_id"] == "p1"
        # Financial fields must not leak in.
        for forbidden in ("budget", "spend", "spend_committed", "owner_auth0_user"):
            assert forbidden not in result

    def test_extracts_activations_with_sounds(self):
        promotion = {
            "id": "p2",
            "activations": [
                {
                    "id": "a1",
                    "name": "Activation One",
                    "artist": {"name": "Artist", "image_url": "http://img/x.png"},
                    "segment": {
                        "social_sounds": [
                            {
                                "id_platform": "12345",
                                "platform": "tiktok",
                                "title": "Sound Title",
                            }
                        ]
                    },
                    "tags": ["a", "b"],
                }
            ],
        }
        result = extract_performance_data(promotion)
        assert len(result["activations"]) == 1
        act = result["activations"][0]
        assert act["artist_name"] == "Artist"
        assert act["artist_image_url"] == "http://img/x.png"
        assert act["social_sounds"] == [
            {"id_platform": "12345", "platform": "tiktok", "title": "Sound Title"}
        ]
        assert act["tags"] == ["a", "b"]

    def test_handles_missing_artist_object(self):
        promotion = {"activations": [{"id": "a1", "name": "x"}]}
        result = extract_performance_data(promotion)
        assert result["activations"][0]["artist_name"] == ""

    def test_zero_counts_default_when_keys_missing(self):
        result = extract_performance_data({"id": "p"})
        assert result["live_submission_count"] == 0
        assert result["draft_submission_count"] == 0
        assert result["comment_count"] == 0


class TestFetchCobrandStats:
    def test_returns_none_for_empty_url(self):
        assert fetch_cobrand_stats("") is None

    def test_returns_none_on_non_200(self):
        resp = MagicMock(status_code=500, text="<html></html>")
        with patch("campaign_manager.services.cobrand.requests.get", return_value=resp):
            assert fetch_cobrand_stats("https://example.com") is None

    def test_returns_none_on_exception(self):
        with patch(
            "campaign_manager.services.cobrand.requests.get",
            side_effect=RuntimeError("boom"),
        ):
            assert fetch_cobrand_stats("https://example.com") is None

    def test_parses_response_html(self):
        html = _build_next_data_html({
            "id": "p9",
            "live_submission_count": 7,
        })
        resp = MagicMock(status_code=200, text=html)
        with patch("campaign_manager.services.cobrand.requests.get", return_value=resp):
            result = fetch_cobrand_stats("https://example.com/share/?token=x")
        assert result["promotion_id"] == "p9"
        assert result["live_submission_count"] == 7
