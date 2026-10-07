"""Bounded minute discovery and existing exact-page refresh ownership."""
from unittest.mock import Mock, patch

import pytest

from campaign_manager.services import notion, notion_sync


@pytest.fixture(autouse=True)
def discovery_state(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "test-only")
    monkeypatch.setattr(notion, "_client_discovery_cursor", None)
    monkeypatch.setattr(notion_sync, "_crm_sync_in_progress", False)


def page(page_id, categories=None):
    props = {"Artist Name": {"title": [{"plain_text": page_id}]}}
    if categories is not None:
        props["Content Niche Targets"] = {"multi_select": categories}
    return {"id": page_id, "properties": props}


def response(pages, cursor=None, status=200):
    result = Mock(status_code=status, text="test response")
    result.json.return_value = {"results": pages, "has_more": cursor is not None,
                                "next_cursor": cursor}
    return result


def test_discovery_reaches_page_51_and_wraps_without_extra_requests():
    first = response([page(str(i)) for i in range(50)], "page-2")
    second = response([page("new-51", [{"name": "Trucktok"}])])
    with patch.object(notion, "resolve_data_source_id", return_value="crm"), patch.object(
            notion.requests, "post", side_effect=[first, second, first]) as post:
        assert notion.query_new_clients(set(), resume=True)[-1]["notion_page_id"] == "49"
        assert notion.query_new_clients(set(), resume=True)[0]["content_types"] == ["Trucktok"]
        notion.query_new_clients(set(), resume=True)
    assert post.call_count == 3
    assert "start_cursor" not in post.call_args_list[0].kwargs["json"]
    assert post.call_args_list[1].kwargs["json"]["start_cursor"] == "page-2"
    assert "start_cursor" not in post.call_args_list[2].kwargs["json"]
    assert all(call.kwargs["json"]["page_size"] == 50 for call in post.call_args_list)


def test_failed_request_retries_cursor_and_expired_cursor_recovers():
    notion._client_discovery_cursor = "page-2"
    with patch.object(notion, "resolve_data_source_id", return_value="crm"), patch.object(
            notion.requests, "post", side_effect=[response([], status=503),
            response([], status=400), response([])]) as post:
        assert notion.query_new_clients(set(), resume=True) == []
        assert notion._client_discovery_cursor == "page-2"
        assert notion.query_new_clients(set(), resume=True) == []
        assert notion._client_discovery_cursor is None
        notion.query_new_clients(set(), resume=True)
    assert "start_cursor" not in post.call_args_list[2].kwargs["json"]


@pytest.mark.parametrize("categories, expected", [
    (None, None), ([], []), ([{"id": "unreadable"}], None),
    ([{"name": "Trucktok"}], ["Trucktok"]),
])
def test_discovery_preserves_unknown_vs_empty_categories(categories, expected):
    with patch.object(notion, "resolve_data_source_id", return_value="crm"), patch.object(
            notion.requests, "post", return_value=response([page("one", categories)])):
        assert notion.query_new_clients(set())[0]["content_types"] == expected


def test_manual_query_does_not_consume_scheduler_cursor():
    notion._client_discovery_cursor = "page-2"
    with patch.object(notion, "resolve_data_source_id", return_value="crm"), patch.object(
            notion.requests, "post", return_value=response([])) as post:
        notion.query_new_clients(set())
    assert "start_cursor" not in post.call_args.kwargs["json"]
    assert notion._client_discovery_cursor == "page-2"


@pytest.mark.parametrize("source_page", ["stored-page", "different-page"])
@pytest.mark.parametrize("fresh", [None, [], ["Coffee"]])
def test_minute_tick_cannot_mutate_existing_campaign_or_poll_history(db, source_page, fresh):
    db.save_campaign("existing", {"title": "Existing", "notion_page_id": "stored-page",
        "content_types": ["Trucktok"], "internal_captions": "Exact words"})
    entry = {"slug": "existing", "notion_page_id": source_page,
             "content_types": fresh, "internal_captions": "replacement"}
    with patch.object(notion, "query_new_clients", return_value=[entry]) as query, patch.object(
            notion, "fetch_page_campaign_fields", side_effect=AssertionError("duplicate refresh")), patch.object(
            db, "get_campaign_notion_links", side_effect=AssertionError("unbounded history scan")):
        notion_sync.run_crm_sync()
    query.assert_called_once_with(set(), resume=True)
    stored = db.get_campaign("existing")
    assert stored["notion_page_id"] == "stored-page"
    assert stored["content_types"] == ["Trucktok"]
    assert stored["internal_captions"] == "Exact words"
    assert notion_sync._crm_sync_in_progress is False


def test_two_minute_ticks_create_client_beyond_fifty_existing_rows(db):
    for i in range(50):
        db.save_campaign(str(i), {"title": str(i), "notion_page_id": str(i),
                                 "content_types": ["Trucktok"]})
    first = response([page(str(i)) for i in range(50)], "page-2")
    second = response([page("new-51", [{"name": "Coffee"}])])
    with patch.object(notion, "resolve_data_source_id", return_value="crm"), patch.object(
            notion.requests, "post", side_effect=[first, second]) as post:
        notion_sync.run_crm_sync()
        assert not db.campaign_exists("new_51")
        notion_sync.run_crm_sync()
    stored = db.get_campaign("new_51")
    assert stored["notion_page_id"] == "new-51"
    assert stored["content_types"] == ["Coffee"]
    assert db.get_campaign("0")["content_types"] == ["Trucktok"]
    assert post.call_count == 2


def test_intentional_empty_current_property_never_uses_legacy_categories():
    crm_page = page("one", [])
    crm_page["properties"]["Types of Content Creators"] = {"multi_select": [{"name": "Trucktok"}]}
    with patch.object(notion, "resolve_data_source_id", return_value="crm"), patch.object(
            notion.requests, "post", return_value=response([crm_page])):
        assert notion.query_new_clients(set())[0]["content_types"] == []


def test_failed_discovery_releases_guard_for_next_tick():
    with patch("campaign_manager.db.is_active", return_value=True), patch.object(
            notion, "query_new_clients", side_effect=[RuntimeError("test-only"), []]) as query:
        notion_sync.run_crm_sync()
        assert notion_sync._crm_sync_in_progress is False
        notion_sync.run_crm_sync()
    assert query.call_count == 2
