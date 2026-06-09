"""Tests for campaign_manager.services.notion_sync (RTA-8)."""
from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

import pytest

from campaign_manager.models import NotionMasterPage, NotionSyncLog
from campaign_manager.services import notion_sync


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PAGE_ID_A = "11111111-1111-1111-1111-111111111111"
_PAGE_ID_B = "22222222-2222-2222-2222-222222222222"


def _page(
    page_id: str,
    *,
    account: str = "test_account",
    group: str = "WARNER",
    subgroup: str = "Warner UGC",
    poster: str = "jake",
    last_edited: str = "2026-05-13T10:00:00.000Z",
    is_complete: bool = False,
):
    """Build a Notion-shaped page dict for tests."""
    return {
        "id": page_id,
        "last_edited_time": last_edited,
        "properties": {
            "Account Username": {"title": [{"plain_text": account}]},
            "Group": {"select": {"name": group}},
            "Group ": {"select": {"name": subgroup}},
            "Poster": {"rich_text": [{"plain_text": poster}]},
            "Account Type": {"select": {"name": "TRUCK"}},
            "Page Type": {"select": {"name": "Lyric page"}},
            "ContentEngine": {"select": {"name": "Kingmaker"}},
            "Pipeline": {"select": {"name": "King Maker Tech"}},
            "Status": {"select": {"name": "In Production"}},
            "Page URL": {"url": f"https://tiktok.com/@{account}"},
            "email": {"email": f"{account}@example.com"},
            "NOTES": {"rich_text": [{"plain_text": "n/a"}]},
            "Go-Live Date": {"date": {"start": "2026-06-01"}},
            "Complete": {"checkbox": is_complete},
        },
    }


@pytest.fixture
def patch_fetch():
    """Mock _fetch_all_pages so tests stay offline."""
    with patch.object(notion_sync, "_fetch_all_pages") as m:
        yield m


# ---------------------------------------------------------------------------
# Property extractor unit tests
# ---------------------------------------------------------------------------

class TestExtractors:
    def test_checkbox_true(self):
        assert notion_sync._get_checkbox({"checkbox": True}) is True

    def test_checkbox_false_when_missing(self):
        assert notion_sync._get_checkbox({}) is False

    def test_parse_iso_z_suffix(self):
        dt = notion_sync._parse_iso_datetime("2026-05-13T10:00:00Z")
        assert dt is not None
        assert dt.year == 2026 and dt.month == 5
        assert dt.tzinfo is not None

    def test_parse_iso_none_when_blank(self):
        assert notion_sync._parse_iso_datetime("") is None
        assert notion_sync._parse_iso_datetime(None) is None

    def test_parse_date_handles_yyyymmdd(self):
        d = notion_sync._parse_date_to_pydate("2026-06-01")
        assert d is not None
        assert (d.year, d.month, d.day) == (2026, 6, 1)


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

class TestMapping:
    def test_happy_path_maps_all_fields(self):
        row, err = notion_sync._map_page_to_row(_page(_PAGE_ID_A, account="brew.pilled"))
        assert err is None
        assert row is not None
        assert row["notion_page_id"] == UUID(_PAGE_ID_A)
        assert row["account_username"] == "brew.pilled"
        assert row["notion_group"] == "WARNER"
        assert row["notion_subgroup"] == "Warner UGC"
        assert row["poster"] == "jake"
        assert row["is_complete"] is False
        assert row["page_url"] == "https://tiktok.com/@brew.pilled"
        assert row["go_live_date"] is not None and row["go_live_date"].year == 2026
        assert row["notion_last_edited_at"] is not None

    def test_missing_account_username_becomes_error(self):
        page = _page(_PAGE_ID_A, account="")
        page["properties"]["Account Username"] = {"title": []}
        row, err = notion_sync._map_page_to_row(page)
        assert row is None
        assert err is not None
        assert err["error_kind"] == "missing_account_username"
        assert err["row_id"] == _PAGE_ID_A

    def test_invalid_page_id_becomes_error(self):
        page = _page(_PAGE_ID_A)
        page["id"] = "not-a-uuid"
        row, err = notion_sync._map_page_to_row(page)
        assert row is None
        assert err is not None
        assert err["error_kind"] == "invalid_page_id"

    def test_password_field_is_never_mirrored(self):
        # Even if Notion sends a Password property, we don't surface it.
        page = _page(_PAGE_ID_A)
        page["properties"]["Password"] = {"rich_text": [{"plain_text": "shh-no-peeking"}]}
        row, err = notion_sync._map_page_to_row(page)
        assert err is None
        assert row is not None
        assert "password" not in row
        # Sanity: the literal value didn't sneak into any other field either.
        assert all("shh-no-peeking" not in str(v) for v in row.values() if v is not None)


# ---------------------------------------------------------------------------
# sync_master_pages — end-to-end with mocked fetch
# ---------------------------------------------------------------------------

class TestSyncMasterPages:
    def test_happy_path_inserts_new_rows(self, db, patch_fetch):
        patch_fetch.return_value = [
            _page(_PAGE_ID_A, account="alice"),
            _page(_PAGE_ID_B, account="bob"),
        ]
        result = notion_sync.sync_master_pages(triggered_by="manual:test")
        assert result.pages_fetched == 2
        assert result.pages_added == 2
        assert result.pages_updated == 0
        assert result.pages_deleted == 0
        assert result.errors == []
        assert result.sync_log_id > 0

        with db.get_session() as s:
            rows = s.query(NotionMasterPage).all()
            assert {r.account_username for r in rows} == {"alice", "bob"}

    def test_idempotent_rerun_is_noop(self, db, patch_fetch):
        patch_fetch.return_value = [_page(_PAGE_ID_A, account="alice")]
        first = notion_sync.sync_master_pages()
        second = notion_sync.sync_master_pages()
        assert first.pages_added == 1
        assert second.pages_added == 0
        assert second.pages_updated == 0
        assert second.pages_deleted == 0

    def test_newer_last_edited_triggers_update(self, db, patch_fetch):
        patch_fetch.return_value = [
            _page(_PAGE_ID_A, account="alice", last_edited="2026-05-13T10:00:00Z"),
        ]
        notion_sync.sync_master_pages()

        patch_fetch.return_value = [
            _page(
                _PAGE_ID_A,
                account="alice_renamed",
                last_edited="2026-05-13T12:00:00Z",
            ),
        ]
        result = notion_sync.sync_master_pages()
        assert result.pages_updated == 1
        assert result.pages_added == 0
        with db.get_session() as s:
            row = s.query(NotionMasterPage).one()
            assert row.account_username == "alice_renamed"

    def test_value_change_with_same_timestamp_triggers_update(self, db, patch_fetch):
        """Notion select-option renames rewrite page values WITHOUT bumping
        last_edited_time. The sync must catch the content change anyway —
        the old timestamp-only diff froze stale values forever."""
        page = _page(_PAGE_ID_A, account="alice", last_edited="2026-05-15T19:47:00Z")
        page["properties"]["Group "] = {"select": {"name": "Warner Test UGC"}}
        patch_fetch.return_value = [page]
        notion_sync.sync_master_pages()

        page2 = _page(_PAGE_ID_A, account="alice", last_edited="2026-05-15T19:47:00Z")
        page2["properties"]["Group "] = {"select": {"name": "Gannon Fremin"}}
        patch_fetch.return_value = [page2]
        result = notion_sync.sync_master_pages()
        assert result.pages_updated == 1
        with db.get_session() as s:
            row = s.query(NotionMasterPage).one()
            assert row.notion_subgroup == "Gannon Fremin"

    def test_mirror_only_row_gets_deleted(self, db, patch_fetch):
        patch_fetch.return_value = [
            _page(_PAGE_ID_A, account="alice"),
            _page(_PAGE_ID_B, account="bob"),
        ]
        notion_sync.sync_master_pages()

        patch_fetch.return_value = [_page(_PAGE_ID_A, account="alice")]
        result = notion_sync.sync_master_pages()
        assert result.pages_deleted == 1
        with db.get_session() as s:
            assert s.query(NotionMasterPage).count() == 1

    def test_per_row_error_does_not_block_other_rows(self, db, patch_fetch):
        bad_page = _page(_PAGE_ID_A, account="")
        bad_page["properties"]["Account Username"] = {"title": []}
        good_page = _page(_PAGE_ID_B, account="bob")
        patch_fetch.return_value = [bad_page, good_page]

        result = notion_sync.sync_master_pages()
        assert result.pages_added == 1
        assert len(result.errors) == 1
        assert result.errors[0]["error_kind"] == "missing_account_username"
        with db.get_session() as s:
            usernames = {r.account_username for r in s.query(NotionMasterPage).all()}
            assert usernames == {"bob"}

    def test_sync_log_row_written_on_success(self, db, patch_fetch):
        patch_fetch.return_value = [_page(_PAGE_ID_A, account="alice")]
        result = notion_sync.sync_master_pages(triggered_by="cron")
        with db.get_session() as s:
            log = s.query(NotionSyncLog).order_by(NotionSyncLog.id.desc()).first()
            assert log is not None
            assert log.id == result.sync_log_id
            assert log.sync_type == "full"
            assert log.triggered_by == "cron"
            assert log.pages_fetched == 1
            assert log.pages_added == 1
            assert log.finished_at is not None

    def test_sync_log_row_written_when_fetch_fails(self, db, patch_fetch):
        patch_fetch.side_effect = RuntimeError("Notion API returned HTTP 401")
        result = notion_sync.sync_master_pages(triggered_by="manual:test")
        assert result.pages_fetched == 0
        assert result.pages_added == 0
        assert any(e["error_kind"] == "fetch_failed" for e in result.errors)
        assert result.sync_log_id > 0
        with db.get_session() as s:
            log = s.query(NotionSyncLog).filter_by(id=result.sync_log_id).one()
            assert log.pages_fetched == 0
            assert log.errors and log.errors[0]["error_kind"] == "fetch_failed"

    def test_triggered_by_default_is_cron(self, db, patch_fetch):
        patch_fetch.return_value = [_page(_PAGE_ID_A, account="alice")]
        notion_sync.sync_master_pages()
        with db.get_session() as s:
            log = s.query(NotionSyncLog).one()
            assert log.triggered_by == "cron"
