"""Durable CRM scan and queue regressions using disposable test-owned storage."""
from datetime import datetime, timedelta, timezone
import time
from unittest.mock import patch

from sqlalchemy import select

from campaign_manager.models import CrmPageQueue, CrmScanState
from campaign_manager.services import crm_queue, notion


def _edited(n):
    return (datetime.now(timezone.utc) - timedelta(seconds=n)).isoformat()


def _page(page_id, status="Client", categories=None, captions=None):
    props = {"Pipeline Status": {"status": {"name": status}},
             "Artist Name": {"title": [{"plain_text": page_id}]}}
    if categories is not None:
        props["Content Niche Targets"] = {"multi_select": [{"name": c} for c in categories]}
    if captions is not None:
        props["Internal Captions"] = {"rich_text": [{"plain_text": captions}] if captions else []}
    return {"id": page_id, "last_edited_time": datetime.now(timezone.utc).isoformat(),
            "properties": props}


def test_scan_commits_cursor_and_queue_together_and_resumes_after_restart(db):
    first = [(f"page-{i}", _edited(30)) for i in range(100)]
    second = [("page-101", _edited(20))]
    with patch.object(notion, "query_crm_edit_window", side_effect=[
        (first, "next"), notion.CrmSourceUnavailable("rate_limited", 10),
        (second, None)]) as query:
        assert crm_queue.scan(deadline=time.monotonic() + 10)["scan_pages"] == 1
        with db._SessionLocal() as session:
            state = session.get(CrmScanState, 1)
            assert state.cursor == "next"
            assert session.query(CrmPageQueue).count() == 100
        # Retry-After is durable; simulate its expiry before the next invocation.
        with db._SessionLocal.begin() as session:
            session.get(CrmScanState, 1).source_pause_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        # A fresh invocation recovers the persisted cursor without process globals.
        crm_queue.scan(deadline=time.monotonic() + 10)
    assert query.call_args.kwargs["cursor"] == "next"
    with db._SessionLocal() as session:
        state = session.get(CrmScanState, 1)
        assert state.cursor is None and state.window_end is None
        assert state.watermark is not None
        assert session.query(CrmPageQueue).count() == 101


def test_scan_rejects_incomplete_page_without_advancing_cursor(db):
    with patch.object(notion, "query_crm_edit_window", return_value=([("late", _edited(-60))], None)):
        crm_queue.scan(deadline=time.monotonic() + 1)
    with db._SessionLocal() as session:
        state = session.get(CrmScanState, 1)
        assert state.watermark is None
        assert session.get(CrmPageQueue, "late") is None


def test_worker_retries_rate_limit_and_reconciles_exact_page(db):
    edited = datetime.now(timezone.utc) - timedelta(seconds=30)
    with db._SessionLocal.begin() as session:
        session.add(CrmPageQueue(page_id="one", edited_at=edited,
                                 queued_at=edited, due_at=edited))
    with patch.object(notion, "fetch_crm_page_for_queue", side_effect=[
        notion.CrmSourceUnavailable("rate_limited", 3), _page("one", categories=["Coffee"], captions="Exact")]):
        assert crm_queue.work(deadline=time.monotonic() + 5)["failed"] == 1
        with db._SessionLocal.begin() as session:
            row = session.get(CrmPageQueue, "one")
            assert row.completed_at is None and row.attempts == 1
            row.due_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.get(CrmScanState, 1).source_pause_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert crm_queue.work(deadline=time.monotonic() + 5)["handled"] == 1
    assert db.get_campaign("one")["content_types"] == ["Coffee"]
    assert db.get_campaign("one")["internal_captions"] == "Exact"


def test_exact_page_refresh_preserves_missing_and_clears_empty(db):
    db.save_campaign("one", {"title": "one", "notion_page_id": "one",
                             "content_types": ["Coffee"], "internal_captions": "Keep"})
    crm_queue._reconcile_page(_page("one"))
    assert db.get_campaign("one")["content_types"] == ["Coffee"]
    assert db.get_campaign("one")["internal_captions"] == "Keep"
    crm_queue._reconcile_page(_page("one", categories=[], captions=""))
    assert db.get_campaign("one")["content_types"] == []
    assert db.get_campaign("one")["internal_captions"] == ""


def test_slug_collision_retries_without_stealing_owner(db):
    db.save_campaign("one", {"title": "Original", "notion_page_id": "original",
                             "internal_captions": "Keep"})
    try:
        crm_queue._reconcile_page(_page("one", captions="Replace"))
        assert False, "collision must remain visible"
    except notion.CrmSourceUnavailable as error:
        assert error.reason == "slug_conflict"
    assert db.get_campaign("one")["notion_page_id"] == "original"
    assert db.get_campaign("one")["internal_captions"] == "Keep"


def test_newer_enqueue_survives_old_worker_ack(db):
    older = datetime.now(timezone.utc) - timedelta(seconds=30)
    with db._SessionLocal.begin() as session:
        session.add(CrmPageQueue(page_id="one", edited_at=older,
                                 queued_at=older, due_at=older))
    claim = crm_queue._claim()
    with db._SessionLocal.begin() as session:
        row = session.get(CrmPageQueue, "one")
        row.edited_at = older + timedelta(seconds=5)
        row.completed_at = None
    assert not crm_queue._finish(claim)
    with db._SessionLocal() as session:
        assert session.get(CrmPageQueue, "one").completed_at is None


def test_window_query_is_sorted_bounded_and_rejects_truncation(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setenv("NOTION_API_KEY", "test-only")
    start = datetime.now(timezone.utc) - timedelta(minutes=1)
    upper = datetime.now(timezone.utc)
    truncated = Mock(status_code=200)
    truncated.json.return_value = {
        "results": [], "has_more": False, "next_cursor": None,
        "request_status": {"type": "incomplete",
                           "incomplete_reason": "query_result_limit_reached"},
    }
    with patch.object(notion, "resolve_data_source_id", return_value="source"), patch.object(
            notion.requests, "post", return_value=truncated) as post:
        try:
            notion.query_crm_edit_window(lower=start, upper=upper, cursor="next")
            assert False, "truncated result must not advance watermark"
        except notion.CrmSourceUnavailable as error:
            assert error.reason == "query_result_limit"
    payload = post.call_args.kwargs["json"]
    assert payload["start_cursor"] == "next"
    assert payload["sorts"] == [{"timestamp": "last_edited_time", "direction": "ascending"}]
    assert payload["page_size"] == 100
    assert len(payload["filter"]["and"]) == 2


def test_source_pause_survives_restart_and_prevents_reads(db):
    crm_queue._pause_source(120)
    with patch.object(notion, "query_crm_edit_window") as query:
        assert crm_queue.scan(deadline=time.monotonic() + 1)["scan_pages"] == 0
    query.assert_not_called()
    with db._SessionLocal() as session:
        assert session.get(CrmScanState, 1).source_pause_until is not None


def test_expired_lease_can_be_reclaimed_but_live_lease_cannot(db):
    edited = datetime.now(timezone.utc) - timedelta(seconds=30)
    with db._SessionLocal.begin() as session:
        session.add(CrmPageQueue(page_id="lease", edited_at=edited,
                                 queued_at=edited, due_at=edited))
    first = crm_queue._claim()
    assert crm_queue._claim() is None
    with db._SessionLocal.begin() as session:
        session.get(CrmPageQueue, "lease").lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    second = crm_queue._claim()
    assert second and second[2] != first[2]
    assert not crm_queue._finish(first)
    assert crm_queue._finish(second)


def test_postgres_skip_locked_claims_other_due_row(monkeypatch):
    """Real row-lock regression; uses an isolated disposable PostgreSQL schema."""
    import os
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    import pytest

    from campaign_manager import db as db_module

    url = os.environ.get("TEST_POSTGRES_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_POSTGRES_DATABASE_URL for PostgreSQL queue lock test")
    schema = "crm_queue_" + __import__("uuid").uuid4().hex[:16]
    root_engine = create_engine(url)
    with root_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"},
                                pool_size=4, max_overflow=0)
    old_engine, old_session = db_module._engine, db_module._SessionLocal
    try:
        CrmScanState.__table__.create(test_engine)
        CrmPageQueue.__table__.create(test_engine)
        db_module._engine = test_engine
        db_module._SessionLocal = sessionmaker(bind=test_engine)
        older = datetime.now(timezone.utc) - timedelta(minutes=1)
        with db_module._SessionLocal.begin() as session:
            session.add_all([
                CrmPageQueue(page_id="a", edited_at=older, queued_at=older, due_at=older),
                CrmPageQueue(page_id="b", edited_at=older, queued_at=older + timedelta(seconds=1),
                             due_at=older + timedelta(seconds=1)),
            ])
        with db_module._SessionLocal.begin() as locker:
            locked = locker.execute(select(CrmPageQueue).where(CrmPageQueue.page_id == "a")
                                    .with_for_update()).scalar_one()
            assert locked.page_id == "a"
            with ThreadPoolExecutor(max_workers=1) as pool:
                other = pool.submit(crm_queue._claim).result(timeout=5)
            assert other[0] == "b"
        first = crm_queue._claim()
        assert first[0] == "a"
        assert crm_queue._finish(first)
        assert crm_queue._finish(other)
        state = crm_queue._state()
        assert state[0] is None and state[2] is None
        assert crm_queue._save_scan_page(state, [("c", (state[1] - timedelta(seconds=1)).isoformat())], None)
        with db_module._SessionLocal() as session:
            assert session.get(CrmScanState, 1).watermark is not None
            assert session.get(CrmPageQueue, "c") is not None
    finally:
        db_module._engine, db_module._SessionLocal = old_engine, old_session
        test_engine.dispose()
        with root_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root_engine.dispose()


def test_completed_campaign_is_not_refreshed(db):
    db.save_campaign("done", {"title": "Done", "notion_page_id": "done",
                              "content_types": ["Coffee"], "internal_captions": "Keep",
                              "completion_status": "completed"})
    crm_queue._reconcile_page(_page("done", categories=[], captions=""))
    assert db.get_campaign("done")["content_types"] == ["Coffee"]
    assert db.get_campaign("done")["internal_captions"] == "Keep"


def test_notions_retry_after_is_preserved(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setenv("NOTION_API_KEY", "test-only")
    response = Mock(status_code=429, headers={"Retry-After": "120"})
    with patch.object(notion.requests, "get", return_value=response):
        try:
            notion.fetch_crm_page_for_queue("one")
            assert False, "429 must remain retryable"
        except notion.CrmSourceUnavailable as error:
            assert error.reason == "rate_limited"
            assert error.retry_after == 120


def test_replayed_page_id_dedupes_and_new_edit_reopens(db):
    first = crm_queue._state()
    edited = first[1] - timedelta(seconds=5)
    assert crm_queue._save_scan_page(first, [("same", edited.isoformat()),
                                            ("same", edited.isoformat())], None)
    with db._SessionLocal.begin() as session:
        row = session.get(CrmPageQueue, "same")
        row.completed_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    second = crm_queue._state()
    newer = second[1] - timedelta(seconds=1)
    assert crm_queue._save_scan_page(second, [("same", newer.isoformat())], None)
    with db._SessionLocal() as session:
        assert session.query(CrmPageQueue).count() == 1
        row = session.get(CrmPageQueue, "same")
        assert row.completed_at is None
        assert crm_queue._aware(row.edited_at) == newer


def test_postgres_tick_persists_scan_and_creates_exact_client():
    """Exercise the production branch against disposable PostgreSQL with no Notion I/O."""
    import os
    import uuid
    import pytest
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from campaign_manager import db as db_module
    from campaign_manager.models import Base

    url = os.environ.get("TEST_POSTGRES_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_POSTGRES_DATABASE_URL for PostgreSQL queue integration")
    schema = "crm_tick_" + uuid.uuid4().hex[:16]
    root_engine = create_engine(url)
    with root_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    old_engine, old_session = db_module._engine, db_module._SessionLocal
    try:
        Base.metadata.create_all(test_engine)
        db_module._engine = test_engine
        db_module._SessionLocal = sessionmaker(bind=test_engine)
        source_page = _page("exact-new", categories=["Coffee"], captions="Verbatim")
        edited = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with patch.object(notion, "query_crm_edit_window",
                          return_value=([("exact-new", edited)], None)), patch.object(
                notion, "fetch_crm_page_for_queue", return_value=source_page):
            crm_queue.run_tick()
        assert db_module.get_campaign("exact_new")["notion_page_id"] == "exact-new"
        assert db_module.get_campaign("exact_new")["internal_captions"] == "Verbatim"
        assert crm_queue.metrics()["depth"] == 0
    finally:
        db_module._engine, db_module._SessionLocal = old_engine, old_session
        test_engine.dispose()
        with root_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root_engine.dispose()


def test_missing_postgres_queue_does_not_fall_back_to_volatile_cursor(db, caplog):
    from types import SimpleNamespace
    from campaign_manager.services import notion_sync

    original_engine = db._engine
    db._engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    try:
        with patch.object(crm_queue, "run_tick", side_effect=RuntimeError("private CRM value")), patch.object(
                notion, "query_new_clients") as legacy:
            notion_sync.run_crm_sync()
        legacy.assert_not_called()
    finally:
        db._engine = original_engine
    assert "crm_queue unavailable (RuntimeError)" in caplog.text
    assert "private CRM value" not in caplog.text


def test_superseded_worker_cannot_overwrite_newer_claim(db):
    db.save_campaign("owned", {"title": "Owned", "notion_page_id": "owned",
                               "content_types": ["Coffee"], "internal_captions": "Keep"})
    edited = datetime.now(timezone.utc) - timedelta(seconds=30)
    with db._SessionLocal.begin() as session:
        session.add(CrmPageQueue(page_id="owned", edited_at=edited,
                                 queued_at=edited, due_at=edited))
    stale_claim = crm_queue._claim()
    with db._SessionLocal.begin() as session:
        session.get(CrmPageQueue, "owned").lease_token = "new-owner"
    try:
        crm_queue._reconcile_page(_page("owned", categories=[], captions="Replace"),
                                  claim=stale_claim)
        assert False, "stale owner must not update"
    except notion.CrmSourceUnavailable as error:
        assert error.reason == "claim_superseded"
    assert db.get_campaign("owned")["content_types"] == ["Coffee"]
    assert db.get_campaign("owned")["internal_captions"] == "Keep"


def test_new_client_caption_pagination_failure_does_not_create_or_ack(db, monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setenv("NOTION_API_KEY", "test-only")
    page = _page("new-long", categories=["Coffee"])
    page["properties"]["Internal Captions"] = {
        "id": "captions", "rich_text": [{"plain_text": "part"} for _ in range(25)],
    }
    edited = datetime.now(timezone.utc) - timedelta(seconds=1)
    with db._SessionLocal.begin() as session:
        session.add(CrmPageQueue(page_id="new-long", edited_at=edited,
                                 queued_at=edited, due_at=edited))
    overloaded = Mock(status_code=429, headers={"Retry-After": "5"})
    complete = Mock(status_code=200)
    complete.json.return_value = {"results": [
        {"rich_text": {"plain_text": "Complete caption"}}],
        "has_more": False, "next_cursor": None}
    with patch.object(notion, "fetch_crm_page_for_queue", return_value=page), patch.object(
            notion.requests, "get", side_effect=[overloaded, complete]) as get, patch.object(
                crm_queue, "_rate_slot", return_value=True) as slot:
        assert crm_queue.work(deadline=time.monotonic() + 10)["failed"] == 1
        assert db.get_campaign("new_long") is None
        with db._SessionLocal.begin() as session:
            row = session.get(CrmPageQueue, "new-long")
            assert row.completed_at is None and row.last_reason == "rate_limited"
            row.due_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.get(CrmScanState, 1).source_pause_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert crm_queue.work(deadline=time.monotonic() + 10)["handled"] == 1
    assert get.call_count == 2
    assert slot.call_count == 4  # exact page plus property GET on both attempts
    assert db.get_campaign("new_long")["internal_captions"] == "Complete caption"


def test_overload_529_preserves_long_retry_after(db, monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setenv("NOTION_API_KEY", "test-only")
    response = Mock(status_code=529, headers={"Retry-After": "7200"})
    with patch.object(notion.requests, "get", return_value=response):
        try:
            notion.fetch_crm_page_for_queue("page")
            assert False
        except notion.CrmSourceUnavailable as error:
            assert error.reason == "rate_limited" and error.retry_after == 7200
    crm_queue._pause_source(7200)
    with db._SessionLocal() as session:
        until = crm_queue._aware(session.get(CrmScanState, 1).source_pause_until)
    assert until > datetime.now(timezone.utc) + timedelta(seconds=7100)
    edited = datetime.now(timezone.utc) - timedelta(seconds=1)
    with db._SessionLocal.begin() as session:
        session.add(CrmPageQueue(page_id="pause", edited_at=edited, queued_at=edited, due_at=edited))
    claim = crm_queue._claim()
    crm_queue._finish(claim, reason="rate_limited", retry_after=7200)
    with db._SessionLocal() as session:
        due = crm_queue._aware(session.get(CrmPageQueue, "pause").due_at)
    assert due > datetime.now(timezone.utc) + timedelta(seconds=7100)


def test_confirmed_expired_cursor_resets_once_and_keeps_window(db):
    original = crm_queue._state()
    edited = (original[1] - timedelta(seconds=1)).isoformat()
    assert crm_queue._save_scan_page(original, [("first", edited)], "expired")
    with db._SessionLocal() as session:
        before = session.get(CrmScanState, 1)
        upper = crm_queue._aware(before.window_end)
    with patch.object(notion, "query_crm_edit_window", side_effect=[
        notion.CrmSourceUnavailable("expired_query_cursor"),
        ([("first", edited)], "new-cursor"),
        notion.CrmSourceUnavailable("expired_query_cursor"),
    ]) as query:
        crm_queue.scan(deadline=time.monotonic() + 10)
    assert [c.kwargs["cursor"] for c in query.call_args_list] == ["expired", None, "new-cursor"]
    with db._SessionLocal() as session:
        state = session.get(CrmScanState, 1)
        assert state.cursor == "new-cursor" and state.cursor_reset_count == 1
        assert crm_queue._aware(state.window_end) == upper and state.watermark is None
        assert session.query(CrmPageQueue).count() == 1
    with patch.object(notion, "query_crm_edit_window", side_effect=notion.CrmSourceUnavailable(
            "expired_query_cursor")) as query:
        crm_queue.scan(deadline=time.monotonic() + 10)
    assert query.call_count == 1


def test_only_confirmed_cursor_400_triggers_reset(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setenv("NOTION_API_KEY", "test-only")
    response = Mock(status_code=400, headers={})
    response.json.return_value = {"code": "validation_error", "message": "Invalid start_cursor"}
    with patch.object(notion, "resolve_data_source_id", return_value="source"), patch.object(
            notion.requests, "post", return_value=response):
        try:
            notion.query_crm_edit_window(lower=None, upper=datetime.now(timezone.utc), cursor="bad")
            assert False
        except notion.CrmSourceUnavailable as error:
            assert error.reason == "expired_query_cursor"
        try:
            notion.query_crm_edit_window(lower=None, upper=datetime.now(timezone.utc), cursor=None)
            assert False
        except notion.CrmSourceUnavailable as error:
            assert error.reason == "http_status"
