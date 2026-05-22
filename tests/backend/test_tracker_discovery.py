"""Tests for ``campaign_manager.services.tracker_discovery``.

Focus is on the API-vs-fallback boundary added when we switched from
scraping Cobrand share pages on every cold cache to calling the
tidestracker ``/api/public/<id>?type=sounds`` endpoint. The
``build_sound_to_trackers_map()`` response shape is contract-stable
because three callers (trackers blueprint, scrape_tasks blueprint,
cron) depend on it — these tests pin that.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from campaign_manager.services import tracker_discovery


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Wipe per-module caches and latch state between tests.

    Without this, a test that probes the 404 latch poisons the next
    test (which then short-circuits to fallback without exercising
    the API path).
    """
    tracker_discovery._sound_to_trackers_cache = None
    tracker_discovery._cache_timestamp = 0.0
    tracker_discovery._tides_sounds_api_available = None
    yield
    tracker_discovery._sound_to_trackers_cache = None
    tracker_discovery._cache_timestamp = 0.0
    tracker_discovery._tides_sounds_api_available = None


@pytest.fixture
def trackers_fixture() -> List[Dict[str, Any]]:
    """Two trackers, one with a Cobrand share link, both active."""
    return [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Artist A - Song",
            "slug": "artist-a-song",
            "is_active": True,
            "cobrand_share_link": "https://music.cobrand.com/promote/aaaa/share?token=t1",
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Artist B - Song",
            "slug": "artist-b-song",
            "is_active": True,
            "cobrand_share_link": "https://music.cobrand.com/promote/bbbb/share?token=t2",
        },
    ]


def _api_response(sounds: List[Dict[str, Any]], status: int = 200) -> Any:
    """Stand-in for a ``requests.Response`` returned by ``requests.get``."""

    class _Resp:
        status_code = status

        def json(self):
            return {
                "success": True,
                "type": "sounds",
                "count": len(sounds),
                "sounds": sounds,
            }

    return _Resp()


def test_build_map_uses_tides_api_when_available(monkeypatch, trackers_fixture):
    """Happy path: API returns sounds for both trackers, no Cobrand scrape fires."""
    monkeypatch.setattr(
        tracker_discovery,
        "list_tracker_campaigns",
        lambda: trackers_fixture,
    )
    monkeypatch.setattr(
        tracker_discovery,
        "_extract_promo_data",
        lambda *a, **kw: pytest.fail("fallback scraper should not run"),
    )

    def fake_get(url, **kwargs):
        if "11111111" in url:
            return _api_response([
                {
                    "sound_id": "7000000000000000001",
                    "sound_title": "Song A",
                    "platform": "tiktok",
                    "activation_name": "Round 1",
                },
            ])
        if "22222222" in url:
            return _api_response([
                {
                    "sound_id": "7000000000000000002",
                    "sound_title": "Song B",
                    "platform": "tiktok",
                    "activation_name": "",
                },
            ])
        raise AssertionError(f"unexpected URL {url}")

    with patch.object(tracker_discovery._requests, "get", side_effect=fake_get):
        out = tracker_discovery.build_sound_to_trackers_map(force_refresh=True)

    assert set(out.keys()) == {
        "7000000000000000001",
        "7000000000000000002",
    }
    entry = out["7000000000000000001"][0]
    # Response shape pinned — these keys are what trackers.py, scrape_tasks.py,
    # and the cron all read off the map.
    assert entry["tracker_id"] == "11111111-1111-1111-1111-111111111111"
    assert entry["tracker_name"] == "Artist A - Song"
    assert entry["tracker_slug"] == "artist-a-song"
    assert entry["tracker_is_active"] is True
    assert entry["activation_name"] == "Round 1"
    assert entry["sound_title"] == "Song A"
    assert entry["cobrand_share_link"].startswith("https://music.cobrand.com/")
    # promo_name has no API equivalent — falls through to tracker name
    assert entry["promo_name"] == "Artist A - Song"


def test_build_map_falls_back_to_scrape_when_api_returns_404(monkeypatch, trackers_fixture):
    """Endpoint not yet deployed: first 404 latches off the API for the rest."""
    monkeypatch.setattr(
        tracker_discovery,
        "list_tracker_campaigns",
        lambda: trackers_fixture,
    )

    class _Resp404:
        status_code = 404

        def json(self):
            return {}

    # Both trackers see the API return 404
    monkeypatch.setattr(
        tracker_discovery._requests,
        "get",
        lambda *a, **kw: _Resp404(),
    )

    # Fallback scrape returns valid promo data for tracker 1, nothing for 2
    def fake_scrape(share_url):
        if "aaaa" in share_url:
            return {
                "name": "Promo A",
                "activations": [
                    {
                        "name": "Round 1",
                        "segment": {
                            "social_sounds": [
                                {"id_platform": "7000000000000000001", "title": "Song A"},
                            ],
                        },
                    },
                ],
            }
        return None

    monkeypatch.setattr(tracker_discovery, "_extract_promo_data", fake_scrape)

    out = tracker_discovery.build_sound_to_trackers_map(force_refresh=True)

    assert "7000000000000000001" in out
    # Latch flipped after the first 404 — fallback path took over
    assert tracker_discovery._tides_sounds_api_available is False
    # `promo_name` survives via the legacy path because the scraper
    # returned a promo dict
    assert out["7000000000000000001"][0]["promo_name"] == "Promo A"


def test_build_map_falls_back_when_api_returns_bad_json(monkeypatch, trackers_fixture):
    """200 response with malformed body falls back to scrape for that tracker only.

    Unlike the 404 latch, a per-tracker JSON error should NOT disable
    the API globally — it could be a one-off Cobrand hiccup, not a
    missing route.
    """
    monkeypatch.setattr(
        tracker_discovery,
        "list_tracker_campaigns",
        lambda: trackers_fixture,
    )

    class _RespBad:
        status_code = 200

        def json(self):
            raise ValueError("not json")

    class _RespOk:
        status_code = 200

        def json(self):
            return {
                "success": True,
                "sounds": [
                    {
                        "sound_id": "7000000000000000002",
                        "sound_title": "Song B",
                        "platform": "tiktok",
                        "activation_name": "",
                    },
                ],
            }

    def fake_get(url, **kwargs):
        return _RespBad() if "11111111" in url else _RespOk()

    monkeypatch.setattr(tracker_discovery._requests, "get", fake_get)

    # Fallback fires only for tracker 1
    scrape_calls: List[str] = []

    def fake_scrape(share_url):
        scrape_calls.append(share_url)
        return {
            "name": "Promo A",
            "activations": [
                {
                    "name": "Round 1",
                    "segment": {
                        "social_sounds": [
                            {"id_platform": "7000000000000000001", "title": "Song A"},
                        ],
                    },
                },
            ],
        }

    monkeypatch.setattr(tracker_discovery, "_extract_promo_data", fake_scrape)

    out = tracker_discovery.build_sound_to_trackers_map(force_refresh=True)

    # Both sound IDs present — one via fallback, one via API
    assert set(out.keys()) == {
        "7000000000000000001",
        "7000000000000000002",
    }
    # Scraper was called only for the bad-JSON tracker
    assert len(scrape_calls) == 1
    assert "aaaa" in scrape_calls[0]
    # API latch stayed True because the OK response succeeded
    assert tracker_discovery._tides_sounds_api_available is True


def test_use_tides_sounds_api_flag_disables_api_path(monkeypatch, trackers_fixture):
    """Setting ``USE_TIDES_SOUNDS_API=false`` forces the legacy scrape path.

    Useful for emergency rollback without redeploying. We don't ship a
    flip in this PR, but the flag has to actually do what its docstring
    promises — verify it short-circuits before any HTTP call.
    """
    monkeypatch.setattr(tracker_discovery, "USE_TIDES_SOUNDS_API", False)
    monkeypatch.setattr(
        tracker_discovery,
        "list_tracker_campaigns",
        lambda: trackers_fixture,
    )

    def boom(*args, **kwargs):
        raise AssertionError("API should not be called when flag is off")

    monkeypatch.setattr(tracker_discovery._requests, "get", boom)
    monkeypatch.setattr(
        tracker_discovery,
        "_extract_promo_data",
        lambda url: {
            "name": "Promo",
            "activations": [
                {
                    "segment": {
                        "social_sounds": [
                            {"id_platform": "7000000000000000001", "title": "X"}
                        ]
                    }
                }
            ],
        } if url else None,
    )

    out = tracker_discovery.build_sound_to_trackers_map(force_refresh=True)
    assert "7000000000000000001" in out


def test_api_returning_empty_sounds_is_a_valid_answer(monkeypatch, trackers_fixture):
    """A tracker with no configured sounds returns ``sounds: []`` — that's
    success, not a reason to fall back."""
    monkeypatch.setattr(
        tracker_discovery,
        "list_tracker_campaigns",
        lambda: [trackers_fixture[0]],
    )
    monkeypatch.setattr(
        tracker_discovery,
        "_extract_promo_data",
        lambda *a, **kw: pytest.fail("fallback should not run on empty success"),
    )
    monkeypatch.setattr(
        tracker_discovery._requests,
        "get",
        lambda *a, **kw: _api_response([]),
    )

    out = tracker_discovery.build_sound_to_trackers_map(force_refresh=True)
    # Empty sound list = tracker contributes nothing to the map, which
    # is correct. The key assertion is that the fallback didn't fire.
    assert out == {}
