"""Tests for the co:brand HTTP client (backoff, 401 refresh, parsing)."""
import json

import pytest

from campaign_manager.services.cobrand_sideload.client import (
    CobrandSideloadClient,
    CobrandAPIError,
)
from campaign_manager.services.cobrand_sideload.config import SideloadConfig


class FakeResp:
    def __init__(self, status, json_data=None, text=""):
        self.status_code = status
        self._json = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise AssertionError("no more responses queued")
        return self._responses.pop(0)


class StubTokens:
    """Yields tok1, then tok2 after invalidate()."""

    def __init__(self):
        self.invalidated = 0
        self._cur = "tok1"

    def get_token(self, force_refresh=False):
        return self._cur

    def invalidate(self):
        self.invalidated += 1
        self._cur = "tok2"


def _config():
    return SideloadConfig(
        api_base="https://api.cobrand.com",
        request_max_retries=4,
        request_backoff_base=0.0,  # no real waiting in tests
    )


def _client(responses):
    sess = FakeSession(responses)
    slept = []
    client = CobrandSideloadClient(
        _config(),
        token_manager=StubTokens(),
        session=sess,
        sleep=lambda d: slept.append(d),
    )
    return client, sess, slept


def test_retries_on_503_then_succeeds():
    client, sess, slept = _client([
        FakeResp(503, text="busy"),
        FakeResp(200, {"items": []}),
    ])
    groups = client.list_bulk_create_groups("act-1")
    assert groups == []
    assert len(sess.calls) == 2
    assert len(slept) == 1


def test_retries_on_429():
    client, sess, slept = _client([
        FakeResp(429, text="slow down"),
        FakeResp(429, text="slow down"),
        FakeResp(200, {"group_id": "g1"}),
    ])
    gid = client.bulk_upload("act-1", ["u1", "u2"])
    assert gid == "g1"
    assert len(sess.calls) == 3
    assert len(slept) == 2
    # request payload is well-formed
    assert sess.calls[0]["json"] == {"activation_id": "act-1", "urls": ["u1", "u2"]}


def test_401_refreshes_token_and_retries():
    client, sess, _ = _client([
        FakeResp(401, text="expired"),
        FakeResp(200, {"group_id": "g9"}),
    ])
    gid = client.bulk_upload("act-1", ["u1"])
    assert gid == "g9"
    assert client.tokens.invalidated == 1
    # second attempt carried the refreshed token
    assert sess.calls[1]["headers"]["Authorization"] == "Bearer tok2"


def test_exhausts_retries_then_raises():
    client, sess, _ = _client([FakeResp(500) for _ in range(5)])
    with pytest.raises(CobrandAPIError):
        client.get_promotion("p1")
    assert len(sess.calls) == 5  # initial + 4 retries


def test_get_promotion_parses_activations():
    client, _, _ = _client([
        FakeResp(200, {
            "id": "p1", "name": "Promo", "status": "active",
            "activations": [
                {"id": "a1", "name": "Act One", "artist": {"id": "ar1", "name": "Artist"}},
            ],
        }),
    ])
    resp = client.get_promotion("p1")
    assert resp.id == "p1"
    assert len(resp.activations) == 1
    assert resp.activations[0].id == "a1"
    assert resp.activations[0].artist_name == "Artist"


def test_non_2xx_4xx_raises_without_retry():
    client, sess, _ = _client([FakeResp(400, text="bad request")])
    with pytest.raises(CobrandAPIError):
        client.get_promotion("p1")
    assert len(sess.calls) == 1
