"""Slack's exempt write route must authenticate before any payload handling."""
import hashlib
import hmac
import json
import time

import pytest


FAKE_SECRET = "test-key-not-real-0000000000000000"
NOW = 1_700_000_000
PATH = "/api/webhooks/slack/events"


@pytest.fixture(autouse=True)
def signing_clock(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", FAKE_SECRET)
    monkeypatch.setattr(time, "time", lambda: NOW)


def signed_headers(body, timestamp=NOW, secret=FAKE_SECRET):
    base = b"v0:" + str(timestamp).encode() + b":" + body
    signature = hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": str(timestamp),
            "X-Slack-Signature": "v0=" + signature}


def post(anon_client, payload, headers=None):
    body = json.dumps(payload, separators=(",", ":")).encode()
    return anon_client.post(PATH, data=body, content_type="application/json",
                            headers=headers or {}), body


def assert_refused(response, marker="unsigned-review-challenge"):
    assert response.status_code in (401, 503)
    assert marker not in response.get_data(as_text=True)


def test_unsigned_challenge_is_refused_before_echo(anon_client, caplog):
    response, _ = post(anon_client, {"type": "url_verification",
                                     "challenge": "unsigned-review-challenge"})
    assert_refused(response)
    assert "unsigned-review-challenge" not in caplog.text


def test_signed_challenge_is_echoed(anon_client):
    payload = {"type": "url_verification", "challenge": "signed-challenge"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    response, _ = post(anon_client, payload, signed_headers(body))
    assert response.status_code == 200
    assert response.get_json() == {"challenge": "signed-challenge"}


def test_wrong_secret_is_refused(anon_client):
    payload = {"type": "url_verification", "challenge": "unsigned-review-challenge"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    response, _ = post(anon_client, payload, signed_headers(body, secret="wrong-secret"))
    assert_refused(response)


def test_changed_body_after_signing_is_refused(anon_client):
    payload = {"type": "url_verification", "challenge": "unsigned-review-challenge"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    altered = {"type": "url_verification", "challenge": "altered-challenge"}
    response, _ = post(anon_client, altered, signed_headers(body))
    assert_refused(response, "altered-challenge")  # body is bound to the signature


@pytest.mark.parametrize("secret", [None, ""])
def test_unset_or_empty_secret_fails_closed(anon_client, monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)
    else:
        monkeypatch.setenv("SLACK_SIGNING_SECRET", secret)
    payload = {"type": "url_verification", "challenge": "unsigned-review-challenge"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    # fx2: sign with the configured value itself (the empty key for ""), so an
    # empty secret wrongly used as an HMAC key would verify and be caught here.
    key = FAKE_SECRET if secret is None else secret
    response, _ = post(anon_client, payload, signed_headers(body, secret=key))
    assert_refused(response)
    assert response.status_code == 503
    assert response.get_json() == {"error": "Slack signing unavailable"}


def test_timestamp_window_and_malformed_headers(anon_client):
    payload = {"type": "url_verification", "challenge": "signed-challenge"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    response, _ = post(anon_client, payload, signed_headers(body, NOW - 301))
    assert_refused(response, "signed-challenge")
    response, _ = post(anon_client, payload, signed_headers(body, NOW - 299))
    assert response.status_code == 200
    for headers in ({"X-Slack-Request-Timestamp": "bad", "X-Slack-Signature": "v0=" + "0" * 64},
                    {"X-Slack-Request-Timestamp": str(NOW), "X-Slack-Signature": "v0=bad"},
                    {"X-Slack-Request-Timestamp": str(NOW)}):
        response, _ = post(anon_client, payload, headers)
        assert_refused(response, "signed-challenge")


def test_signed_event_reaches_bolt_only_once(anon_client, monkeypatch):
    from campaign_manager.services import slack_bot
    from slack_bolt.adapter import flask as bolt_flask

    calls = []
    app_marker = object()
    monkeypatch.setattr(slack_bot, "get_slack_app", lambda: app_marker)

    class Recorder:
        def __init__(self, app):
            assert app is app_marker

        def handle(self, request):
            calls.append(request.get_data(cache=True))
            return {"handled": True}, 200

    monkeypatch.setattr(bolt_flask, "SlackRequestHandler", Recorder)
    payload = {"type": "event_callback", "event": {"type": "message", "text": "test"}}
    body = json.dumps(payload, separators=(",", ":")).encode()
    response, _ = post(anon_client, payload, signed_headers(body))
    assert response.status_code == 200
    assert calls == [body]
    response, _ = post(anon_client, payload)
    assert_refused(response, "test")
    assert calls == [body]


# fx2: a numeric timestamp too large for float arithmetic must be a fixed 401,
# not an uncaught OverflowError (500). Shape-valid signature, then a signature
# actually computed over the oversized timestamp.
@pytest.mark.parametrize("digits", [13, 400, 5000])
def test_oversized_timestamp_is_refused(anon_client, monkeypatch, digits):
    from campaign_manager.services import slack_bot

    # The real clock returns a float; int - int never overflows, float - int does.
    monkeypatch.setattr(time, "time", lambda: float(NOW))
    dispatched = []
    monkeypatch.setattr(slack_bot, "get_slack_app", lambda: dispatched.append(1))
    payload = {"type": "url_verification", "challenge": "oversized-challenge"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    huge = "9" * digits
    for headers in ({"X-Slack-Request-Timestamp": huge, "X-Slack-Signature": "v0=" + "0" * 64},
                    signed_headers(body, timestamp=huge)):
        response, _ = post(anon_client, payload, headers)
        assert response.status_code == 401
        assert response.get_json() == {"error": "Invalid Slack signature"}
        assert "oversized-challenge" not in response.get_data(as_text=True)
    assert dispatched == []


# fx2: the window is symmetric — a correctly signed timestamp from the future
# is refused just like a stale one.
def test_future_timestamp_outside_window_is_refused(anon_client):
    payload = {"type": "url_verification", "challenge": "future-challenge"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    response, _ = post(anon_client, payload, signed_headers(body, NOW + 301))
    assert response.status_code == 401
    assert response.get_json() == {"error": "Invalid Slack signature"}
    response, _ = post(anon_client, payload, signed_headers(body, NOW + 299))
    assert response.status_code == 200
    assert response.get_json() == {"challenge": "future-challenge"}
