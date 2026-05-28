"""Tests for resolve_memberships — cluster model (CAMP cluster work).

These tests bypass the Notion fetch entirely — they seed the
`notion_master_pages` mirror directly and exercise the resolver.

The resolver classifies pages by ONE axis: the cluster, sourced from
`notion_subgroup` (Notion's `Group` field). Label (`notion_group`) and
booker (`poster`) are NOT read.
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
    cluster: str = "",
    notion_group: str = "",
    poster: str = "",
    page_id: UUID | None = None,
    last_edited: datetime | None = None,
) -> UUID:
    """Seed one mirror row. ``cluster`` is the grouping axis (notion_subgroup);
    ``notion_group`` (label) and ``poster`` (booker) are metadata the resolver
    must ignore — they're here so tests can prove they're ignored."""
    pid = page_id or uuid4()
    session.add(NotionMasterPage(
        notion_page_id=pid,
        account_username=account_username,
        notion_group=notion_group or None,
        poster=poster or None,
        notion_subgroup=cluster or None,
        notion_last_edited_at=last_edited or datetime.now(timezone.utc),
    ))
    session.commit()
    return pid


def _members(session, slug: str):
    """Return sorted usernames in the group with this slug. Empty if no group."""
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
# Title helper
# ---------------------------------------------------------------------------

class TestTitleHelper:
    def test_cluster_preserves_casing(self):
        # Cluster titles keep their Notion casing — "Warner UGC", not "Warner Ugc".
        assert notion_sync._title_from_notion_value("Warner UGC", "cluster") == "Warner UGC"

    def test_empty_string_passes_through(self):
        assert notion_sync._title_from_notion_value("", "cluster") == ""


# ---------------------------------------------------------------------------
# resolve_memberships — cluster axis
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_rows_create_cluster_groups(self, db):
        with db.get_session() as s:
            for u in ("brew.pilled", "beaujenkins"):
                _seed_mirror(s, account_username=u, cluster="Sam Barber")

        result = notion_sync.resolve_memberships(triggered_by="manual:test")

        assert result.rows_processed == 2
        assert result.memberships_added == 2   # one cluster axis only
        assert result.memberships_removed == 0
        assert result.groups_created == 1       # sam_barber
        assert result.sync_log_id > 0

        with db.get_session() as s:
            grp = s.query(InternalCreatorGroup).filter_by(slug="sam_barber").one()
            assert grp.kind == "cluster"
            assert grp.title == "Sam Barber"
            assert _members(s, "sam_barber") == ["beaujenkins", "brew.pilled"]

    def test_label_and_booker_are_ignored(self, db):
        # A page with a label + booker but NO cluster resolves to nothing.
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", notion_group="WARNER", poster="Jake Balik")

        result = notion_sync.resolve_memberships()

        assert result.memberships_added == 0
        assert result.groups_created == 0
        with db.get_session() as s:
            # No label/booker groups were created.
            assert s.query(InternalCreatorGroup).filter_by(slug="warner").one_or_none() is None
            assert s.query(InternalCreatorGroup).filter_by(slug="jake_balik").one_or_none() is None
        # It's logged as unattributed.
        assert [e for e in result.errors if e["error_kind"] == "no_attribution"]


class TestSlugNormalization:
    def test_cluster_variants_collapse_to_one_group(self, db):
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", cluster="Mon Rovia")
            _seed_mirror(s, account_username="bob", cluster="mon rovia")
            _seed_mirror(s, account_username="carol", cluster="Mon Rovia ")

        result = notion_sync.resolve_memberships()
        assert result.groups_created == 1  # mon_rovia, only

        with db.get_session() as s:
            assert _members(s, "mon_rovia") == ["alice", "bob", "carol"]


class TestIdempotency:
    def test_second_run_is_a_noop(self, db):
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", cluster="Warner UGC")

        first = notion_sync.resolve_memberships()
        second = notion_sync.resolve_memberships()

        assert first.memberships_added == 1
        assert second.memberships_added == 0
        assert second.memberships_removed == 0
        assert second.groups_created == 0


class TestRemoval:
    def test_membership_no_longer_in_mirror_gets_removed(self, db):
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", cluster="Sam Barber")
        notion_sync.resolve_memberships()

        # Notion now says alice is in Jack Harlow instead.
        with db.get_session() as s:
            s.query(NotionMasterPage).delete()
            s.commit()
            _seed_mirror(s, account_username="alice", cluster="Jack Harlow")

        result = notion_sync.resolve_memberships()
        assert result.memberships_added == 1    # jack_harlow
        assert result.memberships_removed == 1  # sam_barber

        with db.get_session() as s:
            assert _members(s, "sam_barber") == []
            assert _members(s, "jack_harlow") == ["alice"]


class TestLegacyKindProtection:
    def test_custom_and_legacy_groups_survive_resolve(self, db):
        # A `general` (custom) group and a leftover `label` group both have
        # members unrelated to the cluster axis. Neither may be touched.
        with db.get_session() as s:
            gid = _seed_group(s, slug="general", kind="custom", title="General")
            s.add(InternalCreatorGroupMember(group_id=gid, username="random_internal_account"))
            lid = _seed_group(s, slug="warner", kind="label", title="Warner Pages")
            s.add(InternalCreatorGroupMember(group_id=lid, username="legacy_warner_acct"))
            s.commit()
            _seed_mirror(s, account_username="alice", cluster="Sam Barber")

        notion_sync.resolve_memberships()

        with db.get_session() as s:
            # Both legacy/custom memberships untouched.
            assert _members(s, "general") == ["random_internal_account"]
            assert _members(s, "warner") == ["legacy_warner_acct"]
            # The cluster membership is added.
            assert _members(s, "sam_barber") == ["alice"]


class TestTrackerIdUniqueness:
    def test_two_clusters_cannot_pin_same_tracker(self, db):
        import pytest
        from sqlalchemy.exc import IntegrityError

        with db.get_session() as s:
            s.add(InternalCreatorGroup(slug="sam_barber", title="Sam Barber",
                                       kind="cluster", tracker_id="trk-1"))
            s.commit()
        with pytest.raises(IntegrityError):
            with db.get_session() as s:
                s.add(InternalCreatorGroup(slug="jack_harlow", title="Jack Harlow",
                                           kind="cluster", tracker_id="trk-1"))
                s.commit()

    def test_multiple_clusters_may_have_null_tracker(self, db):
        # The common case: unpinned clusters all carry NULL and must coexist.
        with db.get_session() as s:
            s.add(InternalCreatorGroup(slug="a", title="A", kind="cluster"))
            s.add(InternalCreatorGroup(slug="b", title="B", kind="cluster"))
            s.commit()
            assert _members(s, "a") == []  # both inserted without an IntegrityError
            assert _members(s, "b") == []


class TestErrorPaths:
    def test_row_with_no_cluster_logs_no_attribution(self, db):
        with db.get_session() as s:
            pid = _seed_mirror(s, account_username="orphan", cluster="")

        result = notion_sync.resolve_memberships()
        assert result.memberships_added == 0
        no_attr = [e for e in result.errors if e["error_kind"] == "no_attribution"]
        assert len(no_attr) == 1
        assert no_attr[0]["row_id"] == str(pid)

    def test_missing_account_username_in_mirror_logs_error(self, db):
        with db.get_session() as s:
            s.add(NotionMasterPage(
                notion_page_id=uuid4(),
                account_username="   ",  # whitespace, strip()s to ''
                notion_subgroup="Sam Barber",
                notion_last_edited_at=datetime.now(timezone.utc),
            ))
            s.commit()

        result = notion_sync.resolve_memberships()
        assert any(e["error_kind"] == "missing_account_username" for e in result.errors)
        assert result.memberships_added == 0


class TestSyncLogIntegration:
    def test_writes_fresh_log_row_when_no_id_passed(self, db):
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", cluster="Sam Barber")

        result = notion_sync.resolve_memberships(triggered_by="manual:test")

        with db.get_session() as s:
            log = s.query(NotionSyncLog).filter_by(id=result.sync_log_id).one()
            assert log.sync_type == "resolve"
            assert log.triggered_by == "manual:test"
            assert log.memberships_added == 1
            assert log.memberships_removed == 0
            assert log.pages_fetched is None
            assert log.pages_added is None

    def test_updates_existing_log_row_when_id_passed(self, db):
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

            _seed_mirror(s, account_username="alice", cluster="Sam Barber")

        result = notion_sync.resolve_memberships(
            triggered_by="cron", sync_log_id=existing_id,
        )
        assert result.sync_log_id == existing_id

        with db.get_session() as s:
            log = s.query(NotionSyncLog).filter_by(id=existing_id).one()
            assert log.pages_fetched == 10
            assert log.pages_added == 10
            assert log.sync_type == "full"
            assert log.memberships_added == 1
            assert log.memberships_removed == 0
            assert log.finished_at is not None
            errors = log.errors or []
            kinds = [e["error_kind"] for e in errors]
            assert "missing_account_username" in kinds   # the original
            assert "group_created" in kinds              # added by the resolver

    def test_falls_through_to_fresh_log_if_passed_id_does_not_exist(self, db):
        with db.get_session() as s:
            _seed_mirror(s, account_username="alice", cluster="Sam Barber")

        result = notion_sync.resolve_memberships(sync_log_id=999999)
        assert result.sync_log_id != 999999
        assert result.sync_log_id > 0
        with db.get_session() as s:
            log = s.query(NotionSyncLog).filter_by(id=result.sync_log_id).one()
            assert log.sync_type == "resolve"
