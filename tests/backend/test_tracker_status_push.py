"""Pushing campaign delivery status onto the client-facing tracker badge.

Campaign Hub owns completion status; TidesTracker renders it. The risks are
that a tracker outage blocks saving a campaign, or that a wrong value
reaches a page a client is reading.
"""
from __future__ import annotations

import pytest

from campaign_manager.services.tidestracker import (
    TRACKER_STATUS_COMPLETE,
    TRACKER_STATUS_IN_PROGRESS,
    set_tracker_status,
    tracker_status_for,
)


# ── status mapping ─────────────────────────────────────────────────────

def test_completed_maps_to_complete():
    assert tracker_status_for("completed") == TRACKER_STATUS_COMPLETE


@pytest.mark.parametrize("hub_status", ["none", "booked", "", None])
def test_everything_else_reads_as_in_progress(hub_status):
    """A client only cares running vs finished — 'none' and 'booked' are
    both 'still going' from their side."""
    assert tracker_status_for(hub_status) == TRACKER_STATUS_IN_PROGRESS


def test_mapping_tolerates_casing_and_padding():
    assert tracker_status_for("  Completed ") == TRACKER_STATUS_COMPLETE


# ── the push ───────────────────────────────────────────────────────────

def test_no_tracker_id_is_a_no_op(app):
    with app.app_context():
        assert set_tracker_status("", TRACKER_STATUS_COMPLETE) is False
        assert set_tracker_status("   ", TRACKER_STATUS_COMPLETE) is False


def test_invalid_status_raises_rather_than_posting_garbage(app):
    with app.app_context():
        with pytest.raises(ValueError):
            set_tracker_status("some-uuid", "wrapped")


def test_a_tracker_outage_does_not_raise(app, monkeypatch):
    """This runs inside the campaign save. If TidesTracker is down the save
    must still succeed — the badge catches up on the next edit."""
    import campaign_manager.services.tidestracker as tt

    def boom(*args, **kwargs):
        raise tt._requests.RequestException("connection refused")

    monkeypatch.setattr(tt._requests, "patch", boom)
    monkeypatch.setattr(tt, "_config", lambda: ("http://api", "key", "http://base"))

    with app.app_context():
        assert set_tracker_status("some-uuid", TRACKER_STATUS_COMPLETE) is False


def test_unconfigured_tracker_is_skipped_quietly(app, monkeypatch):
    import campaign_manager.services.tidestracker as tt

    def unconfigured():
        raise tt.TidesTrackerError("TidesTracker not configured.")

    monkeypatch.setattr(tt, "_config", unconfigured)

    with app.app_context():
        assert set_tracker_status("some-uuid", TRACKER_STATUS_COMPLETE) is False


def test_successful_push_sends_the_service_key_and_status(app, monkeypatch):
    import campaign_manager.services.tidestracker as tt

    sent = {}

    class _Resp:
        def raise_for_status(self):
            return None

    def fake_patch(url, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        sent["headers"] = headers
        return _Resp()

    monkeypatch.setattr(tt._requests, "patch", fake_patch)
    monkeypatch.setattr(tt, "_config", lambda: ("http://api", "svc-key", "http://base"))

    with app.app_context():
        assert set_tracker_status("uuid-123", TRACKER_STATUS_COMPLETE) is True

    assert sent["url"] == "http://api/campaigns/uuid-123"
    assert sent["json"] == {"status": "complete"}
    assert sent["headers"]["x-service-key"] == "svc-key"


def test_null_status_is_allowed_to_clear_the_badge(app, monkeypatch):
    import campaign_manager.services.tidestracker as tt

    sent = {}

    class _Resp:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        tt._requests, "patch",
        lambda url, json=None, headers=None, timeout=None: (
            sent.update(json=json) or _Resp()
        ),
    )
    monkeypatch.setattr(tt, "_config", lambda: ("http://api", "k", "http://b"))

    with app.app_context():
        assert set_tracker_status("uuid-123", None) is True
    assert sent["json"] == {"status": None}
