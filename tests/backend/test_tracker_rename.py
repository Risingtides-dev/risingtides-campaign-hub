"""The Hub rename must be confirmed upstream before local overlay mutation."""
from unittest.mock import Mock, patch

import requests

from campaign_manager import db
from campaign_manager.services.tidestracker import TidesTrackerError, set_tracker_display_name


TRACKER = "123e4567-e89b-12d3-a456-426614174000"


def _campaign(override):
    return {"campaign": {"id": TRACKER, "name": "Original", "display_name_override": override,
                         "display_name": override or "Original"}}


def _response(payload):
    response = Mock()
    response.json.return_value = payload
    return response


def test_service_rename_reads_back_original_tracker(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", side_effect=[
        _response(_campaign(None)), _response(_campaign("New"))
    ]) as get, patch("campaign_manager.services.tidestracker._requests.patch", return_value=_response(_campaign("New"))) as write:
        result = set_tracker_display_name(TRACKER, "New")
    assert result["display_name_override"] == "New"
    assert get.call_count == 2
    assert write.call_args.kwargs["json"] == {"display_name_override": "New"}
    assert write.call_args.kwargs["headers"]["x-service-key"]


def test_timeout_reconciles_without_replay(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", side_effect=[
        _response(_campaign(None)), _response(_campaign("New"))
    ]), patch("campaign_manager.services.tidestracker._requests.patch", side_effect=requests.Timeout) as write:
        assert set_tracker_display_name(TRACKER, "New")["display_name_override"] == "New"
    write.assert_called_once()


def test_timeout_without_confirmed_readback_fails_closed(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", side_effect=[
        _response(_campaign(None)), requests.Timeout()
    ]), patch("campaign_manager.services.tidestracker._requests.patch", side_effect=requests.Timeout) as write:
        try:
            set_tracker_display_name(TRACKER, "New")
            assert False, "unknown outcome must fail"
        except TidesTrackerError as error:
            assert error.status_code == 503
    write.assert_called_once()


def test_invalid_uuid_never_sends_service_key(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get") as read:
        try:
            set_tracker_display_name("../another-campaign", "New")
            assert False, "invalid UUID must fail"
        except TidesTrackerError as error:
            assert error.status_code == 400
    read.assert_not_called()


def test_mismatched_readback_is_not_success(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", side_effect=[
        _response(_campaign(None)), _response(_campaign("Other"))
    ]), patch("campaign_manager.services.tidestracker._requests.patch", return_value=_response(_campaign("New"))):
        try:
            set_tracker_display_name(TRACKER, "New")
            assert False, "wrong readback must fail"
        except TidesTrackerError as error:
            assert error.status_code == 503


def test_invalid_other_field_prevents_remote_name_write(client, monkeypatch):
    called = []
    monkeypatch.setattr("campaign_manager.blueprints.trackers.set_tracker_display_name", lambda *args: called.append(args))
    response = client.patch(f"/api/trackers/{TRACKER}", json={"name": "New", "group_id": "bad"})
    assert response.status_code == 400
    assert not called


def test_control_character_prevents_remote_name_write(client, monkeypatch):
    called = []
    monkeypatch.setattr("campaign_manager.blueprints.trackers.set_tracker_display_name", lambda *args: called.append(args))
    response = client.patch(f"/api/trackers/{TRACKER}", json={"name": "New\nName"})
    assert response.status_code == 400
    assert not called


def test_remote_failure_keeps_all_local_fields(client, monkeypatch):
    db.set_tracker_name(TRACKER, "Old")
    monkeypatch.setattr("campaign_manager.blueprints.trackers.set_tracker_display_name",
                        lambda *args: (_ for _ in ()).throw(TidesTrackerError("remote failed")))
    response = client.patch(f"/api/trackers/{TRACKER}", json={
        "name": "New", "group_id": 7, "campaign_slug": "new-campaign"
    })
    assert response.status_code == 502
    assert db.get_tracker_names()[TRACKER] == "Old"
    assert TRACKER not in db.get_tracker_assignments()
    assert TRACKER not in db.get_tracker_campaign_links()


def test_confirmed_rename_updates_local_overlay(client, monkeypatch):
    monkeypatch.setattr("campaign_manager.blueprints.trackers.set_tracker_display_name",
                        lambda *args: _campaign("New")["campaign"])
    response = client.patch(f"/api/trackers/{TRACKER}", json={"name": "  New  "})
    assert response.status_code == 200
    assert response.json["name"] == "New"
    assert db.get_tracker_names()[TRACKER] == "New"
