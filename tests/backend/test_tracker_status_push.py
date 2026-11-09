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


# ── the backfill route ─────────────────────────────────────────────────

def test_backfill_pushes_from_worker_threads_with_real_config(app, client, db, monkeypatch):
    """POST /api/trackers/sync-status fans out on a thread pool. The push
    reads its config from current_app, which worker threads do not inherit;
    on 2026-11-09 that made prod report 329 of 329 failed without sending a
    request or logging a line. `_config` is deliberately NOT stubbed here —
    stubbing it is how the per-push tests above could not see this."""
    import threading

    import campaign_manager.services.tidestracker as tt
    from campaign_manager.models import Campaign

    app.config["TIDESTRACKER_API_URL"] = "http://api"
    app.config["TIDESTRACKER_SERVICE_KEY"] = "svc-key"

    session = db.get_session()
    session.add(Campaign(slug="done", title="Done", tracker_campaign_id="uuid-done",
                         completion_status="completed"))
    session.add(Campaign(slug="live", title="Live", tracker_campaign_id="uuid-live",
                         completion_status="booked"))
    session.add(Campaign(slug="unlinked", title="Unlinked", tracker_campaign_id="",
                         completion_status="completed"))
    session.commit()
    session.close()

    sent = {}
    lock = threading.Lock()

    class _Resp:
        def raise_for_status(self):
            return None

    def fake_patch(url, json=None, headers=None, timeout=None):
        with lock:
            sent[url] = (json, headers.get("x-service-key"))
        return _Resp()

    monkeypatch.setattr(tt._requests, "patch", fake_patch)

    resp = client.post("/api/trackers/sync-status")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "ok": True, "pushed": 2, "failed": 0, "total": 2, "conflicts": 0,
    }
    assert sent == {
        "http://api/campaigns/uuid-done": ({"status": "complete"}, "svc-key"),
        "http://api/campaigns/uuid-live": ({"status": "in_progress"}, "svc-key"),
    }


def test_backfill_logs_a_push_that_crashes(app, client, db, monkeypatch, caplog):
    """A crash inside a worker used to be swallowed silently, which is why
    329 failures left nothing in the logs to explain them."""
    import campaign_manager.blueprints.trackers as trackers_bp_module
    import campaign_manager.services.tidestracker as tt
    from campaign_manager.models import Campaign

    session = db.get_session()
    session.add(Campaign(slug="done", title="Done", tracker_campaign_id="uuid-done",
                         completion_status="completed"))
    session.commit()
    session.close()

    def crash(tracker_id, status):
        raise RuntimeError("boom")

    monkeypatch.setattr(tt, "set_tracker_status", crash)

    with caplog.at_level("ERROR", logger=trackers_bp_module.__name__):
        resp = client.post("/api/trackers/sync-status")

    assert resp.get_json() == {
        "ok": True, "pushed": 0, "failed": 1, "total": 1, "conflicts": 0,
    }
    assert "uuid-done" in caplog.text


def test_backfill_pushes_a_shared_tracker_once_and_keeps_it_running(app, client, db, monkeypatch):
    """Two rounds can name the same client page. If one is finished and one
    is live, the page is still running — and it must get one push, not two
    racing ones that leave the badge on whichever landed last."""
    import threading

    import campaign_manager.services.tidestracker as tt
    from campaign_manager.models import Campaign

    app.config["TIDESTRACKER_API_URL"] = "http://api"
    app.config["TIDESTRACKER_SERVICE_KEY"] = "svc-key"

    session = db.get_session()
    for slug, tracker, status in [
        ("round-1", "uuid-shared", "completed"),
        ("round-2", "uuid-shared", "booked"),
        ("old-1", "uuid-both-done", "completed"),
        ("old-2", "uuid-both-done", "completed"),
    ]:
        session.add(Campaign(slug=slug, title=slug, tracker_campaign_id=tracker,
                             completion_status=status))
    session.commit()
    session.close()

    calls = []
    lock = threading.Lock()

    class _Resp:
        def raise_for_status(self):
            return None

    def fake_patch(url, json=None, headers=None, timeout=None):
        with lock:
            calls.append((url, json["status"]))
        return _Resp()

    monkeypatch.setattr(tt._requests, "patch", fake_patch)

    resp = client.post("/api/trackers/sync-status")

    assert resp.get_json() == {
        "ok": True, "pushed": 2, "failed": 0, "total": 2, "conflicts": 1,
    }
    assert sorted(calls) == [
        ("http://api/campaigns/uuid-both-done", "complete"),
        ("http://api/campaigns/uuid-shared", "in_progress"),
    ]
