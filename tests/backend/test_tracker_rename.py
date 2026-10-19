"""The Hub rename must be confirmed upstream before local overlay mutation."""
from unittest.mock import Mock, patch

import requests

from campaign_manager import db
from campaign_manager.blueprints.trackers import _hydrate
from campaign_manager.services.tidestracker import TidesTrackerError, set_tracker_display_name
from campaign_manager.services.tides_tracker import _list_tracker_ids


TRACKER = "123e4567-e89b-12d3-a456-426614174000"


def _campaign(override, revision=0):
    return {"campaign": {"id": TRACKER, "name": "Original", "display_name_override": override,
                         "display_name": override or "Original", "display_name_override_revision": revision}}


def _response(payload):
    response = Mock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def test_service_rename_reads_back_original_tracker(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", side_effect=[
        _response(_campaign(None)), _response(_campaign("New", 1))
    ]) as get, patch("campaign_manager.services.tidestracker._requests.patch", return_value=_response(_campaign("New"))) as write:
        result = set_tracker_display_name(TRACKER, "New")
    assert result["display_name_override"] == "New"
    assert get.call_count == 2
    assert write.call_args.kwargs["json"] == {"display_name_override": "New", "expected_revision": 0}
    assert write.call_args.kwargs["allow_redirects"] is False
    assert all(call.kwargs["allow_redirects"] is False for call in get.call_args_list)
    assert write.call_args.kwargs["headers"]["x-service-key"]


def test_timeout_reconciles_without_replay(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", side_effect=[
        _response(_campaign(None)), _response(_campaign("New", 1))
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
        _response(_campaign(None)), _response(_campaign("Other", 1))
    ]), patch("campaign_manager.services.tidestracker._requests.patch", return_value=_response(_campaign("New"))):
        try:
            set_tracker_display_name(TRACKER, "New")
            assert False, "wrong readback must fail"
        except TidesTrackerError as error:
            assert error.status_code == 503


def test_inconsistent_effective_name_readback_fails_closed(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    inconsistent = _campaign("New", 1)
    inconsistent["campaign"]["display_name"] = "Original"
    with app.app_context(), patch(
        "campaign_manager.services.tidestracker._requests.get",
        side_effect=[_response(_campaign(None)), _response(inconsistent)],
    ), patch(
        "campaign_manager.services.tidestracker._requests.patch",
        return_value=_response(_campaign("New", 1)),
    ):
        try:
            set_tracker_display_name(TRACKER, "New")
            assert False, "stale effective display name cannot confirm rename"
        except TidesTrackerError as error:
            assert error.status_code == 502


def test_same_value_with_wrong_revision_does_not_reconcile_timeout(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", side_effect=[
        _response(_campaign(None, 4)), _response(_campaign("New", 6))
    ]), patch("campaign_manager.services.tidestracker._requests.patch", side_effect=requests.Timeout):
        try:
            set_tracker_display_name(TRACKER, "New")
            assert False, "a later writer's identical value cannot prove our write"
        except TidesTrackerError as error:
            assert error.status_code == 503


def test_revision_conflict_is_not_replayed(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    conflict = _response({"error": "conflict"})
    conflict.status_code = 409
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", return_value=_response(_campaign(None))), patch(
        "campaign_manager.services.tidestracker._requests.patch", return_value=conflict
    ) as write:
        try:
            set_tracker_display_name(TRACKER, "New")
            assert False, "conflict must be returned"
        except TidesTrackerError as error:
            assert error.status_code == 409
    write.assert_called_once()


def test_service_key_requests_refuse_redirects(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    redirect = _response({})
    redirect.status_code = 302
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", return_value=redirect) as read, patch(
        "campaign_manager.services.tidestracker._requests.patch"
    ) as write:
        try:
            set_tracker_display_name(TRACKER, "New")
            assert False, "redirect must fail"
        except TidesTrackerError:
            pass
    assert read.call_args.kwargs["allow_redirects"] is False
    write.assert_not_called()


def test_patch_redirect_is_failure_not_followed(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    redirect = _response({})
    redirect.status_code = 307
    with app.app_context(), patch("campaign_manager.services.tidestracker._requests.get", return_value=_response(_campaign(None))), patch(
        "campaign_manager.services.tidestracker._requests.patch", return_value=redirect
    ) as write:
        try:
            set_tracker_display_name(TRACKER, "New")
            assert False, "redirect must fail"
        except TidesTrackerError as error:
            assert error.status_code == 502
    assert write.call_args.kwargs["allow_redirects"] is False


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
    monkeypatch.setenv("HUB_WRITE_KEY", "test-write-key")
    db.set_tracker_name(TRACKER, "Old")
    monkeypatch.setattr("campaign_manager.blueprints.trackers.set_tracker_display_name",
                        lambda *args: (_ for _ in ()).throw(TidesTrackerError("remote failed")))
    response = client.patch(f"/api/trackers/{TRACKER}", headers={"X-Hub-Write-Key": "test-write-key"}, json={"name": "New"})
    assert response.status_code == 502
    assert db.get_tracker_names()[TRACKER] == "Old"
    assert TRACKER not in db.get_tracker_assignments()
    assert TRACKER not in db.get_tracker_campaign_links()


def test_combined_rename_refused_before_remote_write(client, monkeypatch):
    monkeypatch.setenv("HUB_WRITE_KEY", "test-write-key")
    called = []
    monkeypatch.setattr("campaign_manager.blueprints.trackers.set_tracker_display_name", lambda *args: called.append(args))
    response = client.patch(f"/api/trackers/{TRACKER}", headers={"X-Hub-Write-Key": "test-write-key"}, json={
        "name": "New", "group_id": 7
    })
    assert response.status_code == 400
    assert not called
    assert TRACKER not in db.get_tracker_names()


def test_local_cache_failure_never_returns_success(client, monkeypatch):
    monkeypatch.setenv("HUB_WRITE_KEY", "test-write-key")
    monkeypatch.setattr("campaign_manager.blueprints.trackers.set_tracker_display_name",
                        lambda *args: _campaign("New", 1)["campaign"])
    monkeypatch.setattr(db, "set_tracker_name", lambda *args: (_ for _ in ()).throw(RuntimeError("db unavailable")))
    response = client.patch(f"/api/trackers/{TRACKER}", headers={"X-Hub-Write-Key": "test-write-key"}, json={"name": "New"})
    assert response.status_code == 503
    assert TRACKER not in db.get_tracker_names()


def test_confirmed_rename_updates_local_overlay(client, monkeypatch):
    monkeypatch.setenv("HUB_WRITE_KEY", "test-write-key")
    monkeypatch.setattr("campaign_manager.blueprints.trackers.set_tracker_display_name",
                        lambda *args: _campaign("New")["campaign"])
    response = client.patch(f"/api/trackers/{TRACKER}", headers={"X-Hub-Write-Key": "test-write-key"}, json={"name": "  New  "})
    assert response.status_code == 200
    assert response.json["name"] == "New"
    assert db.get_tracker_names()[TRACKER] == "New"


def test_uppercase_uuid_rename_and_clear_use_confirmed_local_identity(client, monkeypatch):
    monkeypatch.setenv("HUB_WRITE_KEY", "test-write-key")
    seen = []

    def confirmed_rename(tracker_id, name):
        seen.append((tracker_id, name))
        return _campaign(name, len(seen))["campaign"]

    monkeypatch.setattr(
        "campaign_manager.blueprints.trackers.set_tracker_display_name",
        confirmed_rename,
    )
    route_id = TRACKER.upper()
    headers = {"X-Hub-Write-Key": "test-write-key"}
    renamed = client.patch(f"/api/trackers/{route_id}", headers=headers, json={"name": "New"})
    assert renamed.status_code == 200
    assert renamed.json["id"] == TRACKER
    assert db.get_tracker_names() == {TRACKER: "New"}

    cleared = client.patch(f"/api/trackers/{route_id}", headers=headers, json={"name": None})
    assert cleared.status_code == 200
    assert cleared.json["id"] == TRACKER
    assert db.get_tracker_names() == {TRACKER: "Original"}
    assert _list_tracker_ids() == [TRACKER]
    assert seen == [(TRACKER, "New"), (TRACKER, None)]


def test_uppercase_group_and_link_use_one_canonical_roster_identity(client, monkeypatch):
    route_id = TRACKER.upper()
    monkeypatch.setattr(
        "campaign_manager.blueprints.trackers.list_tracker_campaigns",
        lambda: [_campaign(None)["campaign"]],
    )
    group = client.post("/api/tracker-groups", json={"title": "Test group"})
    assert group.status_code == 201
    group_id = group.json["id"]

    assigned = client.patch(f"/api/trackers/{route_id}", json={"group_id": group_id})
    assert assigned.status_code == 200
    assert assigned.json["id"] == TRACKER
    assert db.get_tracker_assignments() == {TRACKER: group_id}

    linked = client.patch(f"/api/trackers/{route_id}", json={"campaign_slug": "test-campaign"})
    assert linked.status_code == 200
    assert linked.json["id"] == TRACKER
    assert db.get_tracker_campaign_links() == {TRACKER: "test-campaign"}
    assert db.get_tracker_names() == {TRACKER: "Original"}
    assert _list_tracker_ids() == [TRACKER]

    listed = client.get("/api/trackers")
    assert listed.status_code == 200
    assert listed.json[0]["id"] == TRACKER
    assert listed.json[0]["group_id"] == group_id
    assert listed.json[0]["campaign_slug"] == "test-campaign"


def test_service_uppercase_uuid_targets_canonical_remote_identity(app):
    app.config["TIDESTRACKER_SERVICE_KEY"] = "test-key"
    with app.app_context(), patch(
        "campaign_manager.services.tidestracker._requests.get",
        side_effect=[_response(_campaign(None)), _response(_campaign("New", 1))],
    ) as read, patch(
        "campaign_manager.services.tidestracker._requests.patch",
        return_value=_response(_campaign("New", 1)),
    ) as write:
        result = set_tracker_display_name(TRACKER.upper(), "New")
    assert result["id"] == TRACKER
    assert all(call.args[0].endswith(f"/campaigns/{TRACKER}") for call in read.call_args_list)
    assert write.call_args.args[0].endswith(f"/campaigns/{TRACKER}")


def test_anonymous_wrong_and_unconfigured_rename_fail_before_remote(client, monkeypatch):
    called = []
    monkeypatch.setattr("campaign_manager.blueprints.trackers.set_tracker_display_name", lambda *args: called.append(args))
    monkeypatch.delenv("HUB_WRITE_KEY", raising=False)
    assert client.patch(f"/api/trackers/{TRACKER}", json={"name": "New"}).status_code == 503
    monkeypatch.setenv("HUB_WRITE_KEY", "test-write-key")
    assert client.patch(f"/api/trackers/{TRACKER}", json={"name": "New"}).status_code == 401
    assert client.patch(f"/api/trackers/{TRACKER}", headers={"X-Hub-Write-Key": "wrong"}, json={"name": "New"}).status_code == 401
    assert not called


def test_hydration_prefers_authoritative_revision_after_remote_clear():
    base = {"id": TRACKER, "name": "Canonical", "display_name": "Canonical",
            "display_name_override": None, "display_name_override_revision": 2}
    def hydrate(tracker):
        return _hydrate(tracker, {}, {TRACKER: "Stale local"}, {}, {}, {}, {})["name"]
    assert hydrate(base) == "Canonical"
    assert hydrate({**base, "display_name": "Remote", "display_name_override": "Remote"}) == "Remote"
    assert hydrate({**base, "display_name_override_revision": 0}) == "Stale local"
