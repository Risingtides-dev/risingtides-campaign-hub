"""Tests for the tracker_names population fix (RTA-41).

Covers:
  - Forward fix: ``set_tracker_campaign_link`` writes the link AND seeds
    ``tracker_names`` in the same transaction when a display name is
    supplied and no override already exists.
  - The seeded name is what a name-based lookup will resolve against —
    ensuring the campaign slug -> tracker_id resolution path doesn't
    have to fall back to slug matching.
  - Existing manual renames are preserved (never clobbered by re-linking).
  - Backfill is idempotent — rerunning is a no-op once every link has a
    corresponding name.

The backfill script itself is exercised by inlining the same logic
against the in-memory DB. Hitting ``scripts/backfill_tracker_names.py``
end-to-end would require the live TidesTracker API; the logic the
script depends on (find-orphans + insert) is what we verify here.
"""
from __future__ import annotations

from campaign_manager.models import TrackerCampaignLink, TrackerName


def _seed_link(db, tid: str, slug: str) -> None:
    """Insert a tracker_campaign_links row WITHOUT touching tracker_names,
    mimicking the legacy write path that caused the population gap."""
    with db.get_session() as s:
        s.add(TrackerCampaignLink(tracker_id=tid, campaign_slug=slug))
        s.commit()


class TestSetTrackerCampaignLinkAtomicUpsert:
    def test_link_and_name_written_together(self, db):
        db.set_tracker_campaign_link(
            "tracker-abc",
            "my-campaign",
            display_name="My Campaign",
        )

        assert db.get_tracker_campaign_links() == {"tracker-abc": "my-campaign"}
        assert db.get_tracker_names() == {"tracker-abc": "My Campaign"}

    def test_link_without_display_name_skips_name_write(self, db):
        """Backwards-compatible: omitting display_name does not error
        and does not invent a name. The backfill script picks up the slack."""
        db.set_tracker_campaign_link("tracker-abc", "my-campaign")

        assert db.get_tracker_campaign_links() == {"tracker-abc": "my-campaign"}
        assert db.get_tracker_names() == {}

    def test_relinking_preserves_existing_name_override(self, db):
        """A user renamed the tracker; later they re-link it. The rename wins."""
        db.set_tracker_name("tracker-abc", "Custom Label")
        db.set_tracker_campaign_link(
            "tracker-abc",
            "my-campaign",
            display_name="Auto-resolved Title",
        )

        assert db.get_tracker_names() == {"tracker-abc": "Custom Label"}

    def test_clearing_link_does_not_touch_names(self, db):
        db.set_tracker_campaign_link("tracker-abc", "my-campaign", display_name="Name")
        assert db.get_tracker_names() == {"tracker-abc": "Name"}

        db.set_tracker_campaign_link("tracker-abc", None)
        assert db.get_tracker_campaign_links() == {}
        # Names overlay is independent of link presence — keep it.
        assert db.get_tracker_names() == {"tracker-abc": "Name"}

    def test_empty_tracker_id_is_noop(self, db):
        db.set_tracker_campaign_link("", "my-campaign", display_name="Name")
        assert db.get_tracker_campaign_links() == {}
        assert db.get_tracker_names() == {}


class TestAcceptanceQuery:
    """The acceptance evidence query from RTA-41:

        SELECT COUNT(*) FROM tracker_campaign_links l
          LEFT JOIN tracker_names n ON l.tracker_id = n.tracker_id
          WHERE n.display_name IS NULL;

    Must return 0 after the forward fix is applied to every new link.
    """

    def _orphan_link_count(self, db) -> int:
        with db.get_session() as s:
            existing_name_ids = {tid for (tid,) in s.query(TrackerName.tracker_id).all()}
            link_ids = {tid for (tid,) in s.query(TrackerCampaignLink.tracker_id).all()}
            return len(link_ids - existing_name_ids)

    def test_forward_fix_keeps_orphan_count_at_zero(self, db):
        db.set_tracker_campaign_link("t1", "c1", display_name="Campaign One")
        db.set_tracker_campaign_link("t2", "c2", display_name="Campaign Two")
        db.set_tracker_campaign_link("t3", "c3", display_name="Campaign Three")

        assert self._orphan_link_count(db) == 0

    def test_legacy_link_creates_orphan(self, db):
        """Reproduces the bug: a pre-fix code path leaves an orphan link."""
        _seed_link(db, "legacy-tracker", "legacy-campaign")
        assert self._orphan_link_count(db) == 1


class TestBackfillLogic:
    """Verify the orphan-discovery + insert logic the backfill script
    runs. We don't shell out to the script (it needs live TidesTracker);
    we exercise the SQLAlchemy logic it relies on, against in-memory DB.
    """

    def _backfill(self, db, name_index: dict) -> int:
        """Mirror of scripts/backfill_tracker_names.py main loop:
        for every link without a name, insert one sourced from the
        provided name_index (which simulates the TidesTracker API
        response). Returns count inserted."""
        inserted = 0
        with db.get_session() as s:
            existing_name_ids = {tid for (tid,) in s.query(TrackerName.tracker_id).all()}
            link_rows = s.query(
                TrackerCampaignLink.tracker_id,
                TrackerCampaignLink.campaign_slug,
            ).all()
            for tid, _slug in link_rows:
                if tid in existing_name_ids:
                    continue
                name = name_index.get(tid, "").strip()
                if not name:
                    continue
                s.add(TrackerName(tracker_id=tid, display_name=name))
                inserted += 1
            s.commit()
        return inserted

    def test_backfill_fills_orphans(self, db):
        _seed_link(db, "t1", "c1")
        _seed_link(db, "t2", "c2")
        _seed_link(db, "t3", "c3")

        inserted = self._backfill(
            db,
            name_index={"t1": "Campaign One", "t2": "Campaign Two", "t3": "Campaign Three"},
        )

        assert inserted == 3
        assert db.get_tracker_names() == {
            "t1": "Campaign One",
            "t2": "Campaign Two",
            "t3": "Campaign Three",
        }

    def test_backfill_is_idempotent(self, db):
        _seed_link(db, "t1", "c1")
        name_index = {"t1": "Campaign One"}

        first = self._backfill(db, name_index)
        second = self._backfill(db, name_index)

        assert first == 1
        assert second == 0
        assert db.get_tracker_names() == {"t1": "Campaign One"}

    def test_backfill_does_not_overwrite_existing_override(self, db):
        _seed_link(db, "t1", "c1")
        db.set_tracker_name("t1", "Manual Override")

        inserted = self._backfill(db, name_index={"t1": "Auto Name"})

        assert inserted == 0
        assert db.get_tracker_names() == {"t1": "Manual Override"}


class TestNameLookupResolution:
    """RTA-41 acceptance: a campaign slug lookup resolves to a tracker_id
    via tracker_names without falling back to campaign-slug matching.

    With tracker_names populated, callers building a name -> tracker_id
    index can resolve campaigns by their human-facing label. The
    existing slug-based source (``campaigns.tracker_campaign_id`` /
    ``tracker_campaign_links``) is unchanged."""

    def test_display_name_to_tracker_id_map_is_populated(self, db):
        db.set_tracker_campaign_link("tracker-aaa", "summer-2026", display_name="Summer 2026")
        db.set_tracker_campaign_link("tracker-bbb", "fall-2026", display_name="Fall 2026")

        names = db.get_tracker_names()
        name_to_tracker = {name: tid for tid, name in names.items()}

        assert name_to_tracker["Summer 2026"] == "tracker-aaa"
        assert name_to_tracker["Fall 2026"] == "tracker-bbb"

    def test_slug_lookup_still_works_independently(self, db):
        """Slug-based resolution path (the only path that worked pre-fix)
        must continue working. The name path is additive, not a replacement."""
        db.set_tracker_campaign_link("tracker-aaa", "summer-2026", display_name="Summer 2026")

        assert db.get_tracker_id_for_campaign("summer-2026") == "tracker-aaa"
