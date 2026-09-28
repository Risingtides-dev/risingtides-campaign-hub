from unittest.mock import Mock, patch

import pytest

from campaign_manager.services import notion


@pytest.fixture(autouse=True)
def reset_cursor():
    notion._niche_refresh_after = ''
    yield
    notion._niche_refresh_after = ''


def test_refresh_updates_only_existing_active_campaign_categories(db):
    for slug, status in [('active', 'booked'), ('pending', 'none'), ('finished', 'completed')]:
        db.save_campaign(slug, {'title': slug, 'notion_page_id': 'crm-' + slug,
                                'completion_status': status, 'budget': 120,
                                'content_types': ['Coffee']})
    before = db.get_campaign('active')
    with patch.object(notion, 'fetch_page_content_types', side_effect=lambda page: ['Trucktok'] if page == 'crm-active' else None) as fetch:
        result = notion.refresh_campaign_niche_targets()
    assert result == {'checked': 2, 'updated': 1, 'unavailable': 1}
    assert {call.args[0] for call in fetch.call_args_list} == {'crm-active', 'crm-pending'}
    after = db.get_campaign('active')
    assert after['content_types'] == ['Trucktok']
    assert after['budget'] == before['budget']
    assert after['completion_status'] == 'booked'
    assert db.get_campaign('pending')['content_types'] == ['Coffee']
    assert db.get_campaign('finished')['content_types'] == ['Coffee']
    assert len(db.list_campaigns()) == 3


def test_explicit_empty_declaration_clears_stored_niches(db):
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'content_types': ['Trucktok']})
    with patch.object(notion, 'fetch_page_content_types', return_value=[]):
        assert notion.refresh_campaign_niche_targets()['updated'] == 1
    assert db.get_campaign('active')['content_types'] == []


def test_bounded_refresh_advances_past_failures():
    links = [{'slug': f'campaign-{i:03}', 'notion_page_id': str(i), 'content_types': []} for i in range(60)]
    with patch('campaign_manager.db.is_active', return_value=True), patch('campaign_manager.db.get_campaign_notion_links', return_value=links), patch.object(notion, 'fetch_page_content_types', return_value=None) as fetch:
        assert notion.refresh_campaign_niche_targets()['checked'] == 50
        assert [call.args[0] for call in fetch.call_args_list] == [str(i) for i in range(50)]
        fetch.reset_mock()
        notion.refresh_campaign_niche_targets()
        assert [call.args[0] for call in fetch.call_args_list[:10]] == [str(i) for i in range(50, 60)]


@pytest.mark.parametrize('properties, expected', [
    ({}, None),
    ({'Content Niche Targets': {'multi_select': []}}, []),
    ({'Content Niche Targets': {'multi_select': [{'name': 'Trucktok'}]}}, ['Trucktok']),
    ({'Content Niche Targets': {'multi_select': [{'id': 'missing-name'}]}}, None),
    ({'Content Niche Targets': {'rich_text': []}}, None),
])
def test_fetch_distinguishes_missing_property_from_empty_declaration(monkeypatch, properties, expected):
    monkeypatch.setenv('NOTION_API_KEY', 'test-only')
    response = Mock(status_code=200)
    response.json.return_value = {'properties': properties}
    with patch.object(notion.requests, 'get', return_value=response):
        assert notion.fetch_page_content_types('crm-page') == expected


def test_background_refresh_is_single_flight_and_throttled(monkeypatch):
    monkeypatch.setenv('NOTION_API_KEY', 'test-only')
    monkeypatch.setattr(notion, '_niche_refresh_running', False)
    monkeypatch.setattr(notion, '_niche_refresh_requested_at', None)
    threads = []
    class DeferredThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
        def start(self):
            threads.append(self)
    with patch('campaign_manager.db.is_active', return_value=True), patch.object(notion.threading, 'Thread', DeferredThread), patch.object(notion.time, 'monotonic', return_value=1000) as clock, patch.object(notion, 'refresh_campaign_niche_targets') as refresh:
        assert notion.request_campaign_niche_refresh() is True
        assert notion.request_campaign_niche_refresh() is False
        refresh.assert_not_called()
        threads[0].target()
        refresh.assert_called_once()
        assert notion.request_campaign_niche_refresh() is False
        clock.return_value = 1901
        assert notion.request_campaign_niche_refresh() is True
        assert len(threads) == 2
        threads[1].target()


def test_campaign_read_requests_refresh_without_enabling_scraper(client):
    with patch.object(notion, 'request_campaign_niche_refresh', return_value=False) as request_refresh:
        response = client.get('/api/campaigns')
    assert response.status_code == 200
    request_refresh.assert_called_once_with()


def test_failed_background_refresh_releases_single_flight(monkeypatch):
    monkeypatch.setenv('NOTION_API_KEY', 'test-only')
    monkeypatch.setattr(notion, '_niche_refresh_running', False)
    monkeypatch.setattr(notion, '_niche_refresh_requested_at', None)
    class ImmediateThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
        def start(self):
            self.target()
    with patch('campaign_manager.db.is_active', return_value=True), patch.object(notion.threading, 'Thread', ImmediateThread), patch.object(notion, 'refresh_campaign_niche_targets', side_effect=RuntimeError('unavailable')):
        assert notion.request_campaign_niche_refresh() is True
        assert notion._niche_refresh_running is False
