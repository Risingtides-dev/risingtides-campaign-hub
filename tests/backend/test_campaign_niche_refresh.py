from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from campaign_manager.services import notion


@pytest.fixture(autouse=True)
def reset_cursor():
    notion._niche_refresh_after = ''
    yield
    notion._niche_refresh_after = ''


def fields(content_types, internal_captions=None):
    return {'content_types': content_types, 'internal_captions': internal_captions}


def test_refresh_updates_only_existing_active_campaign_categories(db):
    for slug, status in [('active', 'booked'), ('pending', 'none'), ('finished', 'completed')]:
        db.save_campaign(slug, {'title': slug, 'notion_page_id': 'crm-' + slug,
                                'completion_status': status, 'budget': 120,
                                'content_types': ['Coffee']})
    before = db.get_campaign('active')
    with patch.object(notion, 'fetch_page_campaign_fields', side_effect=lambda page: fields(['Trucktok']) if page == 'crm-active' else None) as fetch:
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
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields([])):
        assert notion.refresh_campaign_niche_targets()['updated'] == 1
    assert db.get_campaign('active')['content_types'] == []


def test_bounded_refresh_advances_past_failures():
    links = [{'slug': f'campaign-{i:03}', 'notion_page_id': str(i), 'content_types': []} for i in range(60)]
    with patch('campaign_manager.db.is_active', return_value=True), patch('campaign_manager.db.get_campaign_notion_links', return_value=links), patch.object(notion, 'fetch_page_campaign_fields', return_value=None) as fetch:
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


def test_refresh_brings_crm_captions_onto_the_campaign_verbatim(db):
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'content_types': ['Coffee'], 'budget': 120})
    assert db.get_campaign('active')['internal_captions'] is None
    typed = 'pov: u miss him  \n\nstill aint over it\n'
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields(['Coffee'], typed)):
        assert notion.refresh_campaign_niche_targets() == {'checked': 1, 'updated': 1, 'unavailable': 0}
    after = db.get_campaign('active')
    assert after['internal_captions'] == typed
    assert after['content_types'] == ['Coffee']
    assert after['budget'] == 120
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields(['Coffee'], typed)):
        assert notion.refresh_campaign_niche_targets()['updated'] == 0


def test_explicitly_empty_crm_captions_clear_the_stored_ones(db):
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'internal_captions': 'a line'})
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields([], '')):
        assert notion.refresh_campaign_niche_targets()['updated'] == 1
    assert db.get_campaign('active')['internal_captions'] == ''


def test_unreadable_captions_property_preserves_stored_captions(db):
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'content_types': ['Coffee'], 'internal_captions': 'a line'})
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields(['Trucktok'], None)):
        assert notion.refresh_campaign_niche_targets() == {'checked': 1, 'updated': 1, 'unavailable': 0}
    after = db.get_campaign('active')
    assert after['internal_captions'] == 'a line'
    assert after['content_types'] == ['Trucktok']


def test_unreadable_niches_do_not_hold_back_readable_captions(db):
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'content_types': ['Coffee']})
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields(None, 'a line')):
        assert notion.refresh_campaign_niche_targets() == {'checked': 1, 'updated': 1, 'unavailable': 1}
    after = db.get_campaign('active')
    assert after['internal_captions'] == 'a line'
    assert after['content_types'] == ['Coffee']


@pytest.mark.parametrize('properties, expected', [
    ({}, None),
    ({'Internal Captions': {'rich_text': []}}, ''),
    ({'Internal Captions': {'rich_text': [{'plain_text': 'one\n'}, {'plain_text': 'two'}]}}, 'one\ntwo'),
    ({'Internal Captions': {'rich_text': [{'text': 'no plain text'}]}}, None),
    ({'Internal Captions': {'multi_select': []}}, None),
    ({'Internal Captions': None}, None),
])
def test_captions_fetch_distinguishes_missing_property_from_empty(monkeypatch, properties, expected):
    monkeypatch.setenv('NOTION_API_KEY', 'test-only')
    response = Mock(status_code=200)
    response.json.return_value = {'properties': properties}
    with patch.object(notion.requests, 'get', return_value=response) as get:
        result = notion.fetch_page_campaign_fields('crm-page')
    assert result['internal_captions'] == expected
    assert get.call_count == 1


def test_long_captions_are_read_whole_through_the_property_endpoint(monkeypatch):
    monkeypatch.setenv('NOTION_API_KEY', 'test-only')
    inline = [{'plain_text': f'inline {i}\n'} for i in range(25)]
    page = Mock(status_code=200)
    page.json.return_value = {'properties': {'Internal Captions': {'id': 'cap%3A', 'rich_text': inline}}}
    first = Mock(status_code=200)
    first.json.return_value = {
        'results': [{'rich_text': {'plain_text': f'line {i}\n'}} for i in range(100)],
        'has_more': True, 'next_cursor': 'cursor-2',
    }
    second = Mock(status_code=200)
    second.json.return_value = {
        'results': [{'rich_text': {'plain_text': 'last line'}}], 'has_more': False, 'next_cursor': None,
    }
    with patch.object(notion.requests, 'get', side_effect=[page, first, second]) as get:
        result = notion.fetch_page_campaign_fields('crm-page')
    assert result['internal_captions'] == ''.join(f'line {i}\n' for i in range(100)) + 'last line'
    assert get.call_args_list[1].args[0].endswith('/pages/crm-page/properties/cap%3A')
    assert get.call_args_list[1].kwargs['params'] == {'page_size': 100}
    assert get.call_args_list[2].kwargs['params'] == {'page_size': 100, 'start_cursor': 'cursor-2'}


def test_long_captions_that_cannot_be_read_whole_are_unreadable_not_cut_short(monkeypatch):
    monkeypatch.setenv('NOTION_API_KEY', 'test-only')
    inline = [{'plain_text': f'inline {i}\n'} for i in range(25)]
    page = Mock(status_code=200)
    page.json.return_value = {'properties': {
        'Internal Captions': {'id': 'cap', 'rich_text': inline},
        'Content Niche Targets': {'multi_select': [{'name': 'Coffee'}]},
    }}
    with patch.object(notion.requests, 'get', side_effect=[page, Mock(status_code=502)]):
        result = notion.fetch_page_campaign_fields('crm-page')
    assert result == {'content_types': ['Coffee'], 'internal_captions': None}


def test_captions_endpoint_lists_active_read_campaigns_with_their_sound(client, db):
    db.save_campaign('with_lines', {'title': 'With', 'sound_id': '7684050289380379422',
                                    'official_sound': 'https://www.tiktok.com/music/x-7684050289380379422',
                                    'internal_captions': 'one\ntwo'})
    db.save_campaign('cleared', {'title': 'Cleared', 'sound_id': '7683349944753588240',
                                 'completion_status': 'booked', 'internal_captions': ''})
    db.save_campaign('finished', {'title': 'Finished', 'completion_status': 'completed',
                                  'sound_id': '7687855665968646145', 'internal_captions': 'stale'})
    db.save_campaign('never_read', {'title': 'Never', 'sound_id': '7681621526072821776'})
    with patch.object(notion, 'request_campaign_niche_refresh', return_value=False) as request_refresh:
        response = client.get('/api/campaigns/captions')
    assert response.status_code == 200
    request_refresh.assert_called_once_with()
    assert response.get_json() == [
        {'slug': 'cleared', 'sound_id': '7683349944753588240', 'official_sound': '',
         'internal_captions': ''},
        {'slug': 'with_lines', 'sound_id': '7684050289380379422',
         'official_sound': 'https://www.tiktok.com/music/x-7684050289380379422',
         'internal_captions': 'one\ntwo'},
    ]


def test_campaign_list_does_not_carry_caption_text(client, db):
    db.save_campaign('with_lines', {'title': 'With', 'internal_captions': 'one\ntwo'})
    with patch.object(notion, 'request_campaign_niche_refresh', return_value=False):
        rows = client.get('/api/campaigns').get_json()
    assert [row['slug'] for row in rows] == ['with_lines']
    assert 'internal_captions' not in rows[0]


def test_campaign_detail_shows_the_crm_captions(client, db):
    db.save_campaign('with_lines', {'title': 'With', 'internal_captions': 'one\ntwo'})
    db.save_campaign('never_read', {'title': 'Never'})
    assert client.get('/api/campaign/with_lines').get_json()['internal_captions'] == 'one\ntwo'
    assert client.get('/api/campaign/never_read').get_json()['internal_captions'] is None


def test_saving_a_campaign_without_captions_keeps_the_stored_ones(db):
    db.save_campaign('active', {'title': 'Active', 'internal_captions': 'a line'})
    db.save_campaign('active', {'title': 'Active renamed', 'budget': 50})
    after = db.get_campaign('active')
    assert after['title'] == 'Active renamed'
    assert after['internal_captions'] == 'a line'


def test_a_save_that_loaded_its_copy_earlier_does_not_put_old_captions_back(db):
    # The scraper and the edit doors load a campaign, work, then save the
    # whole thing. The CRM refresh can land in between.
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'internal_captions': 'old line'})
    loaded_earlier = db.get_campaign('active')
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields([], 'new line')):
        notion.refresh_campaign_niche_targets()

    db.save_campaign('active', {**loaded_earlier, 'additional_sounds': ['7684050289380379422']})

    after = db.get_campaign('active')
    assert after['additional_sounds'] == ['7684050289380379422']
    assert after['internal_captions'] == 'new line'


def test_a_save_that_loaded_before_the_first_crm_read_does_not_blank_the_captions(db, client):
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'sound_id': '7684050289380379422'})
    loaded_earlier = db.get_campaign('active')
    assert loaded_earlier['internal_captions'] is None
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields([], 'first line')):
        notion.refresh_campaign_niche_targets()

    db.save_campaign('active', loaded_earlier)

    assert db.get_campaign('active')['internal_captions'] == 'first line'
    with patch.object(notion, 'request_campaign_niche_refresh', return_value=False):
        listed = client.get('/api/campaigns/captions').get_json()
    assert [row['slug'] for row in listed] == ['active']


def _put(client, slug, body, headers=None):
    return client.put(f'/api/campaign/{slug}/internal-captions', json=body, headers=headers or {})


def test_captions_written_back_go_to_the_crm_page_first_and_are_then_stored(db, client, monkeypatch):
    monkeypatch.setenv('NOTION_API_KEY', 'test-only')
    monkeypatch.delenv('HUB_WRITE_KEY', raising=False)
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'internal_captions': 'old line'})
    response = Mock(status_code=200)
    response.json.return_value = {'id': 'crm-active'}
    with patch.object(notion.requests, 'patch', return_value=response) as patched:
        reply = _put(client, 'active', {'internal_captions': 'new line\nsecond', 'expected': 'old line'})
    assert reply.status_code == 200
    assert reply.get_json() == {'slug': 'active', 'internal_captions': 'new line\nsecond', 'crm': 'updated'}
    assert db.get_campaign('active')['internal_captions'] == 'new line\nsecond'
    assert patched.call_args.args[0].endswith('/pages/crm-active')
    assert patched.call_args.kwargs['json'] == {'properties': {'Internal Captions': {
        'rich_text': [{'type': 'text', 'text': {'content': 'new line\nsecond'}}]}}}


def test_a_stale_write_back_is_refused_with_the_current_captions(db, client, monkeypatch):
    monkeypatch.setenv('NOTION_API_KEY', 'test-only')
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'internal_captions': 'newer line'})
    with patch.object(notion.requests, 'patch') as patched:
        reply = _put(client, 'active', {'internal_captions': 'mine', 'expected': 'old line'})
        never_read = _put(client, 'active', {'internal_captions': 'mine', 'expected': None})
    assert reply.status_code == 409
    assert reply.get_json()['internal_captions'] == 'newer line'
    assert never_read.status_code == 409
    patched.assert_not_called()
    assert db.get_campaign('active')['internal_captions'] == 'newer line'


def test_a_write_back_the_crm_refuses_is_not_stored_here_either(db, client, monkeypatch):
    monkeypatch.setenv('NOTION_API_KEY', 'test-only')
    db.save_campaign('active', {'title': 'Active', 'notion_page_id': 'crm-active',
                                'internal_captions': 'old line'})
    refused = Mock(status_code=400, text='{}')
    refused.json.return_value = {'message': 'Internal Captions is not a property that exists.'}
    with patch.object(notion.requests, 'patch', return_value=refused):
        reply = _put(client, 'active', {'internal_captions': 'new line', 'expected': 'old line'})
    assert reply.status_code == 502
    assert reply.get_json() == {'error': 'CRM update failed: CRM answered 400: Internal Captions is not a property that exists.',
                                'internal_captions': 'old line'}
    assert db.get_campaign('active')['internal_captions'] == 'old line'

    monkeypatch.delenv('NOTION_API_KEY')
    with patch.object(notion.requests, 'patch') as patched:
        reply = _put(client, 'active', {'internal_captions': 'new line', 'expected': 'old line'})
    assert reply.status_code == 502
    assert 'not configured' in reply.get_json()['error']
    patched.assert_not_called()


def test_a_campaign_without_a_crm_page_keeps_its_captions_here_only(db, client, monkeypatch):
    monkeypatch.delenv('NOTION_API_KEY', raising=False)
    db.save_campaign('manual', {'title': 'Manual'})
    with patch.object(notion.requests, 'patch') as patched:
        reply = _put(client, 'manual', {'internal_captions': 'typed in Sounds', 'expected': None})
    assert reply.status_code == 200
    assert reply.get_json()['crm'] == 'none'
    assert db.get_campaign('manual')['internal_captions'] == 'typed in Sounds'
    patched.assert_not_called()


def test_the_write_back_checks_its_key_when_one_is_set(db, client, monkeypatch):
    monkeypatch.setenv('HUB_WRITE_KEY', 'shared-secret')
    db.save_campaign('manual', {'title': 'Manual'})
    assert _put(client, 'manual', {'internal_captions': 'x', 'expected': None}).status_code == 401
    assert _put(client, 'manual', {'internal_captions': 'x', 'expected': None},
                {'X-Hub-Write-Key': 'wrong'}).status_code == 401
    assert _put(client, 'manual', {'internal_captions': 'x', 'expected': None},
                {'X-Hub-Write-Key': 'shared-secret'}).status_code == 200


def test_the_write_back_refuses_bad_bodies_by_name(db, client, monkeypatch):
    monkeypatch.delenv('HUB_WRITE_KEY', raising=False)
    db.save_campaign('manual', {'title': 'Manual'})
    assert _put(client, 'manual', {'internal_captions': 'x'}).status_code == 400
    assert _put(client, 'manual', {'internal_captions': 5, 'expected': None}).status_code == 400
    assert _put(client, 'manual', {'internal_captions': 'x' * 100_001, 'expected': None}).status_code == 400
    assert _put(client, 'manual', {'internal_captions': 'x', 'expected': 5}).status_code == 400
    assert _put(client, 'missing', {'internal_captions': 'x', 'expected': None}).status_code == 404


def test_long_captions_reach_notion_in_pieces_it_accepts():
    pieces = notion._rich_text_pieces('a' * 4500)
    assert [len(piece['text']['content']) for piece in pieces] == [2000, 2000, 500]
    assert notion._rich_text_pieces('') == []


# ── Minute CRM queue coverage (issue #257) ───────────────────────────

def _queue_state(db, *, watermark_age=timedelta(seconds=30), audit_age=timedelta(hours=1),
                 paused=False, rows=()):
    from campaign_manager.models import CrmPageQueue, CrmScanState
    now = datetime.now(timezone.utc)
    with db._SessionLocal.begin() as session:
        session.add(CrmScanState(
            id=1, watermark=now - watermark_age, last_full_audit_at=now - audit_age,
            source_pause_until=now + timedelta(minutes=1) if paused else None,
            cursor_reset_count=0, full_audit_active=False, updated_at=now))
        for page_id, completed, reason, leased in rows:
            session.add(CrmPageQueue(
                page_id=page_id, edited_at=now - timedelta(minutes=5),
                queued_at=now - timedelta(minutes=5), due_at=now - timedelta(minutes=5),
                attempts=0, completed_at=now - timedelta(minutes=4) if completed else None,
                last_reason=reason, lease_token='lease' if leased else None))


def _two_linked(db):
    db.save_campaign('a', {'title': 'A', 'notion_page_id': 'aaaa-1111', 'content_types': ['Coffee']})
    db.save_campaign('b', {'title': 'B', 'notion_page_id': 'bbbb-2222', 'content_types': ['Coffee']})


def test_refresh_skips_pages_the_current_queue_reconciled(db):
    _two_linked(db)
    # Queue stores Notion's hyphenated form; matching ignores hyphens and case.
    _queue_state(db, rows=[('AAAA1111', True, None, False)])
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields(['Trucktok'])) as fetch:
        result = notion.refresh_campaign_niche_targets()
    assert [call.args[0] for call in fetch.call_args_list] == ['bbbb-2222']
    assert result == {'checked': 1, 'updated': 1, 'unavailable': 0}
    assert db.get_campaign('a')['content_types'] == ['Coffee']
    assert db.get_campaign('b')['content_types'] == ['Trucktok']


@pytest.mark.parametrize('state', [
    {'watermark_age': timedelta(minutes=11)},
    {'audit_age': timedelta(hours=13)},
    {'paused': True},
])
def test_stale_or_paused_queue_leaves_every_link_to_the_refresh(db, state):
    _two_linked(db)
    _queue_state(db, rows=[('aaaa-1111', True, None, False), ('bbbb-2222', True, None, False)], **state)
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields(['Coffee'])) as fetch:
        notion.refresh_campaign_niche_targets()
    assert sorted(call.args[0] for call in fetch.call_args_list) == ['aaaa-1111', 'bbbb-2222']


def test_pending_failing_or_leased_queue_pages_are_still_refreshed(db):
    db.save_campaign('a', {'title': 'A', 'notion_page_id': 'aaaa-1111', 'content_types': []})
    db.save_campaign('b', {'title': 'B', 'notion_page_id': 'bbbb-2222', 'content_types': []})
    db.save_campaign('c', {'title': 'C', 'notion_page_id': 'cccc-3333', 'content_types': []})
    db.save_campaign('d', {'title': 'D', 'notion_page_id': 'dddd-4444', 'content_types': []})
    _queue_state(db, rows=[('aaaa-1111', False, None, False),
                           ('bbbb-2222', True, 'http_status', False),
                           ('cccc-3333', True, None, True),
                           ('dddd-4444', True, None, False)])
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields([])) as fetch:
        notion.refresh_campaign_niche_targets()
    assert sorted(call.args[0] for call in fetch.call_args_list) == ['aaaa-1111', 'bbbb-2222', 'cccc-3333']


def test_no_queue_state_refreshes_every_link(db):
    _two_linked(db)
    with patch.object(notion, 'fetch_page_campaign_fields', return_value=fields(['Coffee'])) as fetch:
        notion.refresh_campaign_niche_targets()
    assert sorted(call.args[0] for call in fetch.call_args_list) == ['aaaa-1111', 'bbbb-2222']


def test_coverage_lookup_failure_refreshes_every_link(db):
    from campaign_manager.services import crm_queue
    _two_linked(db)
    _queue_state(db, rows=[('aaaa-1111', True, None, False)])
    with patch.object(crm_queue, 'select', side_effect=RuntimeError('down')), \
            patch.object(notion, 'fetch_page_campaign_fields', return_value=fields(['Coffee'])) as fetch:
        notion.refresh_campaign_niche_targets()
    assert sorted(call.args[0] for call in fetch.call_args_list) == ['aaaa-1111', 'bbbb-2222']
