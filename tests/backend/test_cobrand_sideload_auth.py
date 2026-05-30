"""Tests for the Auth0 token manager (caching, expiry, grants, invalidate)."""
import json

import pytest

from campaign_manager.services.cobrand_sideload.auth import (
    Auth0TokenManager,
    CobrandAuthError,
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


def _clock():
    state = {"t": 1000.0}
    return (lambda: state["t"]), state


def _m2m_config():
    return SideloadConfig(
        auth0_domain="tenant.auth0.com",
        auth0_audience="https://api.cobrand.com",
        auth0_client_id="cid",
        auth0_client_secret="secret",
    )


def test_token_is_cached():
    sess = FakeSession([FakeResp(200, {"access_token": "abc", "expires_in": 3600})])
    clock, _ = _clock()
    mgr = Auth0TokenManager(_m2m_config(), session=sess, clock=clock)

    assert mgr.get_token() == "abc"
    assert mgr.get_token() == "abc"  # served from cache
    assert len(sess.calls) == 1
    assert sess.calls[0]["json"]["grant_type"] == "client_credentials"
    assert sess.calls[0]["json"]["audience"] == "https://api.cobrand.com"


def test_token_refetched_after_expiry():
    sess = FakeSession([
        FakeResp(200, {"access_token": "abc", "expires_in": 100}),
        FakeResp(200, {"access_token": "def", "expires_in": 100}),
    ])
    clock, state = _clock()
    mgr = Auth0TokenManager(_m2m_config(), session=sess, clock=clock)

    assert mgr.get_token() == "abc"
    state["t"] += 200  # blow past expiry (incl. skew)
    assert mgr.get_token() == "def"
    assert len(sess.calls) == 2


def test_refresh_token_grant_body():
    cfg = SideloadConfig(auth0_domain="tenant.auth0.com", auth0_refresh_token="rt-123")
    sess = FakeSession([FakeResp(200, {"access_token": "abc", "expires_in": 3600})])
    clock, _ = _clock()
    mgr = Auth0TokenManager(cfg, session=sess, clock=clock)

    assert cfg.grant_type == "refresh_token"
    assert mgr.get_token() == "abc"
    body = sess.calls[0]["json"]
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "rt-123"


def test_invalidate_forces_refetch():
    sess = FakeSession([
        FakeResp(200, {"access_token": "abc", "expires_in": 3600}),
        FakeResp(200, {"access_token": "def", "expires_in": 3600}),
    ])
    clock, _ = _clock()
    mgr = Auth0TokenManager(_m2m_config(), session=sess, clock=clock)

    assert mgr.get_token() == "abc"
    mgr.invalidate()
    assert mgr.get_token() == "def"
    assert len(sess.calls) == 2


def test_no_credentials_raises():
    cfg = SideloadConfig(auth0_domain="tenant.auth0.com")  # no client/refresh creds
    mgr = Auth0TokenManager(cfg, session=FakeSession([]))
    with pytest.raises(CobrandAuthError):
        mgr.get_token()


def test_non_200_raises():
    sess = FakeSession([FakeResp(403, text="forbidden")])
    mgr = Auth0TokenManager(_m2m_config(), session=sess)
    with pytest.raises(CobrandAuthError):
        mgr.get_token()
