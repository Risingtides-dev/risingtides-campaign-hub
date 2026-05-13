"""Tests for resolve_memberships (RTA-9).

These tests bypass the Notion fetch entirely — they seed the
`notion_master_pages` mirror directly and exercise the resolver.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from campaign_manager.models import (
    InternalCreatorGroup,
    InternalCreatorGroupMember,
    NotionMasterPage,
    NotionSyncLog,
)
from campaign_manager.services import notion_sync


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_mirror(
    session,
    *,
    account_username: str,
    notion_group: str = "",
    poster: str = "",
    page_id: UUID | None = None,
    last_edited: datetime | None = None,
) -> UUID:
    pid = page_id or uuid4()
    session.add(NotionMasterPage(
        notion_page_id=pid,
        account_username=account_username,
        notion_group=notion_group or None,
        poster=poster or None,
        notion_last_edited_at=last_edited or datetime.now(timezone.utc),
    ))
    session.commit()
    return pid


def _members(session, slug: str):
    """Return sorted list of usernames in the group with this slug. Empty list
    if the group itself does not exist."""
    grp = session.query(InternalCreatorGroup).filter_by(slug=slug).one_or_none()
    if grp is None:
        return []
    return sorted(
        m.username
        for m in session.query(InternalCreatorGroupMember).filter_by(group_id=grp.id).all()
    )


def _seed_group(session, *, slug: str, kind: str, title: str | None = None) -> int:
    grp = InternalCreatorGroup(slug=slug, title=title or slug, kind=kind)
    session.add(grp)
    session.commit()
    return int(grp.id)


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

class TestTitleHelper:
    def test_label_titlecases_allcaps(self):
        assert notion_sync._title_from_notion_value("WARNER", "label") == "Warner"

    def test_booker_keeps_freetext_casing(self):
        assert notion_sync._title_from_notion_value("Jake Balik", "booked_by") == "Jake Balik"

    def test_empty_string_passes_through(self):
        assert notion_sync._title_from_notion_value("", "label") == ""


# ---------------------------------------------------------------------------
# resolve_memberships
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_three_rows_create_warner_and_jake_memberships(self, db):
        with db.get_session() as s:
            for u in ("brew.pilled", "beaujenkins", "codyjames6.7"):
                _seed_mirror(s, account_username=u, notion_group="WARNER", poster="Jake Balik")

        result = notion_sync.resolve_memberships(triggered_by="manual:test")

        assert result.rows_processed == 3
        assert result.memberships_added == 6  # 3 users x 2 axes
        assert result.memberships_removed == 0
        assert result.groups_created == 2  # warner + jake_balik
        assert result.sync_log_id > 0

        with db.get_session() as s:
            assert _members(s, "warner") == ["beaujenkins", "brew.pilled", "codyjames6.7"]
            assert _members(s, "jake_balik") == ["beaujenkins", "brew.pilled", "codyjames6.7"]

    def test_groups_get_correct_kind_when_auto_created(self, db):
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", notion_group="ATLANTIC", poster="Eric Cromartie")

        notion_sync.resolve_memberships()

        with db.get_session() as s:
            atl = s.query(InternalCreatorGroup).filter_by(slug="atlantic").one()
            eric = s.query(InternalCreatorGroup).filter_by(slug="eric_cromartie").one()
            assert atl.kind == "label"
            assert atl.title == "Atlantic"
            assert eric.kind == "booked_by"
            assert eric.title == "Eric Cromartie"


class TestIdempotency:
    def test_second_run_is_a_noop(self, db):
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", notion_group="WARNER", poster="Jake")

        first = notion_sync.resolve_memberships()
        second = notion_sync.resolve_memberships()

        assert first.memberships_added == 2
        assert second.memberships_added == 0
        assert second.memberships_removed == 0
        assert second.groups_created == 0


class TestRemoval:
    def test_membership_no_longer_in_mirror_gets_removed(self, db):
        # Stage A: alice is in WARNER per Notion -> resolver adds her.
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", notion_group="WARNER")
        notion_sync.resolve_memberships()

        # Stage B: Notion now says alice is in ATLANTIC instead. Mirror gets
        # rewritten (the sync stage would do this; we simulate it).
        with db.get_session() as s:
            s.query(NotionMasterPage).delete()
            s.commit()
            _seed_mirror(s, account_username="alice", notion_group="ATLANTIC")

        result = notion_sync.resolve_memberships()
        assert result.memberships_added == 1   # atlantic
        assert result.memberships_removed == 1  # warner

        with db.get_session() as s:
            assert _members(s, "warner") == []
            assert _members(s, "atlantic") == ["alice"]


class TestCustomKindProtection:
    def test_custom_group_membership_survives_resolve(self, db):
        # Pre-create a `general` (custom) group with a member that has
        # nothing to do with Notion.
        with db.get_session() as s:
            gid = _seed_group(s, slug="general", kind="custom", title="General")
            s.add(InternalCreatorGroupMember(group_id=gid, username="random_internal_account"))
            s.commit()

            # Seed Notion mirror with a totally different account.
            _seed_mirror(s, account_username="alice", notion_group="WARNER")

        notion_sync.resolve_memberships()

        with db.get_session() as s:
            # The custom-group membership is untouched.
            assert _members(s, "general") == ["random_internal_account"]
            # The Notion-driven membership is added.
            assert _members(s, "warner") == ["alice"]

    def test_custom_membership_for_user_also_in_notion_survives(self, db):
        # Edge case: the SAME username is in a custom group AND a Notion
        # label group. The custom membership must not be touched by the
        # resolver's removal pass even though the user is "covered" elsewhere.
        with db.get_session() as s:
            gid = _seed_group(s, slug="general", kind="custom")
            s.add(InternalCreatorGroupMember(group_id=gid, username="alice"))
            s.commit()
            _seed_mirror(s, account_username="alice", notion_group="WARNER")

        notion_sync.resolve_memberships()

        with db.get_session() as s:
            assert _members(s, "general") == ["alice"]
            assert _members(s, "warner") == ["alice"]


class TestErrorPaths:
    def test_row_with_no_group_or_poster_logs_no_attribution(self, db):
        with db.get_session() as s:
            pid = _seed_mirror(s, account_username="orphan", notion_group="", poster="")

        result = notion_sync.resolve_memberships()
        assert result.memberships_added == 0
        no_attr = [e for e in result.errors if e["error_kind"] == "no_attribution"]
        assert len(no_attr) == 1
        assert no_attr[0]["row_id"] == str(pid)

    def test_missing_account_username_in_mirror_logs_error(self, db):
        # account_username is NOT NULL in the schema, but the resolver
        # still defends in case of ' ' / ''.
        with db.get_session() as s:
            s.add(NotionMasterPage(
                notion_page_id=uuid4(),
                account_username="   ",  # whitespace, strip()s to ''
                notion_group="WARNER",
                notion_last_edited_at=datetime.now(timezone.utc),
            ))
            s.commit()

        result = notion_sync.resolve_memberships()
        assert any(e["error_kind"] == "missing_account_username" for e in result.errors)
        assert result.memberships_added == 0


class TestSlugNormalization:
    def test_freetext_poster_variants_collapse_to_one_group(self, db):
        # Notion has the same booker spelled three different ways across
        # three different rows. Resolver should slugify each to `jake_balik`
        # and write all three accounts into the same group.
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", poster="Jake Balik")
            _seed_mirror(s, account_username="bob", poster="jake balik")
            _seed_mirror(s, account_username="carol", poster="Jake Balik ")

        result = notion_sync.resolve_memberships()
        assert result.groups_created == 1  # jake_balik, only

        with db.get_session() as s:
            assert _members(s, "jake_balik") == ["alice", "bob", "carol"]


class TestSyncLogIntegration:
    def test_writes_fresh_log_row_when_no_id_passed(self, db):
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", notion_group="WARNER")

        result = notion_sync.resolve_memberships(triggered_by="manual:test")

        with db.get_session() as s:
            log = s.query(NotionSyncLog).filter_by(id=result.sync_log_id).one()
            assert log.sync_type == "resolve"
            assert log.triggered_by == "manual:test"
            assert log.memberships_added == 1
            assert log.memberships_removed == 0
            # Page-level counts are untouched (this stage didn't fetch).
            assert log.pages_fetched is None
            assert log.pages_added is None

    def test_updates_existing_log_row_when_id_passed(self, db):
        # Simulate the cron's natural flow: sync_master_pages writes a row,
        # then resolve_memberships adds its counts to the same row.
        with db.get_session() as s:
            existing = NotionSyncLog(
                started_at=datetime.now(timezone.utc),
                sync_type="full",
                pages_fetched=10, pages_added=10,
                pages_updated=0, pages_deleted=0,
                errors=[{"row_id": "x", "error_kind": "missing_account_username", "detail": "..."}],
                triggered_by="cron",
            )
            s.add(existing)
            s.commit()
            existing_id = existing.id

            _seed_mirror(s, account_username="alice", notion_group="WARNER")

        result = notion_sync.resolve_memberships(
            triggered_by="cron", sync_log_id=existing_id,
        )
        assert result.sync_log_id == existing_id

        with db.get_session() as s:
            log = s.query(NotionSyncLog).filter_by(id=existing_id).one()
            # Original page-level counts preserved.
            assert log.pages_fetched == 10
            assert log.pages_added == 10
            assert log.sync_type == "full"
            # Membership counts layered on.
            assert log.memberships_added == 1
            assert log.memberships_removed == 0
            # finished_at updated.
            assert log.finished_at is not None
            # Errors are MERGED: original sync-stage entry preserved + any
            # informational entries the resolver appended (e.g. "group_created"
            # when warner gets auto-created here).
            errors = log.errors or []
            kinds = [e["error_kind"] for e in errors]
            assert "missing_account_username" in kinds  # the original
            assert "group_created" in kinds  # added by the resolver

    def test_falls_through_to_fresh_log_if_passed_id_does_not_exist(self, db):
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", notion_group="WARNER")

        # ID 999999 doesn't exist -> resolver should still record audit.
        result = notion_sync.resolve_memberships(sync_log_id=999999)
        assert result.sync_log_id != 999999
        assert result.sync_log_id > 0
        with db.get_session() as s:
            log = s.query(NotionSyncLog).filter_by(id=result.sync_log_id).one()
            assert log.sync_type == "resolve"
