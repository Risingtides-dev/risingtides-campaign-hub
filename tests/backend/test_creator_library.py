"""Niche vocabulary and per-creator library records.

The vocabulary is user-owned and grows mid-session, so the risks are all
about drift: "Gym" and "gym" becoming two niches, a merge dropping tags on
the floor, or tagging one creator quietly rewriting another's tags.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from campaign_manager.services import creator_library as lib


@pytest.fixture
def session(db):
    with db.get_session() as s:
        yield s


# ── vocabulary ─────────────────────────────────────────────────────────

def test_seed_niches_are_installed_once(session):
    first = lib.ensure_seed_niches(session)
    second = lib.ensure_seed_niches(session)

    assert first == len(lib.SEED_NICHES)
    assert second == 0, "re-running must not duplicate the vocabulary"
    assert len(lib.list_niches(session)) == len(lib.SEED_NICHES)


def test_seed_vocabulary_matches_what_jake_asked_for(session):
    for expected in ("POV", "dark POV", "trucktok", "pinterest moodboard", "anime"):
        assert expected.lower() in [n.lower() for n in lib.SEED_NICHES]


def test_creating_a_niche_is_case_insensitive(session):
    a = lib.create_niche(session, "Gym Motivation")
    b = lib.create_niche(session, "gym motivation")

    assert a["id"] == b["id"], "casing must not fork the vocabulary"
    assert a["name"] == "gym motivation"


def test_creating_a_niche_trims_and_collapses_whitespace(session):
    made = lib.create_niche(session, "  dark   POV  ")
    assert made["name"] == "dark pov"


def test_blank_niche_is_rejected(session):
    with pytest.raises(ValueError):
        lib.create_niche(session, "   ")


def test_list_reports_how_many_creators_carry_each_niche(session):
    gym = lib.create_niche(session, "gym")
    lib.create_niche(session, "anime")
    lib.apply_niche_to(session, gym["id"], ["alice", "bob"])

    counts = {n["name"]: n["count"] for n in lib.list_niches(session)}
    assert counts["gym"] == 2
    assert counts["anime"] == 0, "an unused niche still belongs in the picker"


# ── tagging ────────────────────────────────────────────────────────────

def test_a_creator_holds_many_niches(session):
    lib.set_niches(session, "alice", ["gym", "grwm", "anime"])
    assert sorted(lib.niches_for(session, ["alice"])["alice"]) == ["anime", "grwm", "gym"]


def test_tagging_one_creator_leaves_others_untouched(session):
    lib.set_niches(session, "alice", ["gym"])
    lib.set_niches(session, "bob", ["anime"])

    tags = lib.niches_for(session, ["alice", "bob"])
    assert tags["alice"] == ["gym"]
    assert tags["bob"] == ["anime"]


def test_set_niches_replaces_rather_than_appends(session):
    lib.set_niches(session, "alice", ["gym", "anime"])
    lib.set_niches(session, "alice", ["gym"])

    assert lib.niches_for(session, ["alice"])["alice"] == ["gym"]


def test_set_niches_creates_vocabulary_entries_on_the_fly(session):
    lib.set_niches(session, "alice", ["ultra specific thing"])
    assert "ultra specific thing" in [n["name"] for n in lib.list_niches(session)]


def test_usernames_are_matched_case_insensitively(session):
    lib.set_niches(session, "Alice", ["gym"])
    assert lib.niches_for(session, ["alice"])["alice"] == ["gym"]


def test_bulk_apply_tags_many_creators_at_once(session):
    gym = lib.create_niche(session, "gym")
    added = lib.apply_niche_to(session, gym["id"], ["alice", "bob", "carol"])

    assert added == 3
    assert lib.niches_for(session, ["bob"])["bob"] == ["gym"]


def test_bulk_apply_skips_creators_who_already_have_it(session):
    gym = lib.create_niche(session, "gym")
    lib.apply_niche_to(session, gym["id"], ["alice"])
    added = lib.apply_niche_to(session, gym["id"], ["alice", "bob"])

    assert added == 1
    assert lib.niches_for(session, ["alice"])["alice"] == ["gym"]


# ── housekeeping ───────────────────────────────────────────────────────

def test_rename_carries_every_creator_with_it(session):
    gym = lib.create_niche(session, "gym")
    lib.apply_niche_to(session, gym["id"], ["alice", "bob"])

    lib.rename_niche(session, gym["id"], "gym motivation")

    assert lib.niches_for(session, ["alice"])["alice"] == ["gym motivation"]


def test_merge_folds_one_niche_into_another(session):
    gym = lib.create_niche(session, "gym")
    motivation = lib.create_niche(session, "gym motivation")
    lib.apply_niche_to(session, gym["id"], ["alice"])
    lib.apply_niche_to(session, motivation["id"], ["bob"])

    lib.merge_niches(session, gym["id"], motivation["id"])

    names = [n["name"] for n in lib.list_niches(session)]
    assert "gym" not in names
    assert lib.niches_for(session, ["alice"])["alice"] == ["gym motivation"]
    assert lib.niches_for(session, ["bob"])["bob"] == ["gym motivation"]


def test_merge_does_not_duplicate_shared_creators(session):
    gym = lib.create_niche(session, "gym")
    motivation = lib.create_niche(session, "gym motivation")
    lib.apply_niche_to(session, gym["id"], ["alice"])
    lib.apply_niche_to(session, motivation["id"], ["alice"])

    lib.merge_niches(session, gym["id"], motivation["id"])

    assert lib.niches_for(session, ["alice"])["alice"] == ["gym motivation"]


def test_renaming_onto_an_existing_name_merges_instead_of_colliding(session):
    gym = lib.create_niche(session, "gym")
    motivation = lib.create_niche(session, "gym motivation")
    lib.apply_niche_to(session, gym["id"], ["alice"])

    lib.rename_niche(session, gym["id"], "gym motivation")

    assert lib.niches_for(session, ["alice"])["alice"] == ["gym motivation"]
    assert len([n for n in lib.list_niches(session) if n["name"] == "gym motivation"]) == 1


def test_delete_removes_the_niche_and_its_tags(session):
    gym = lib.create_niche(session, "gym")
    lib.apply_niche_to(session, gym["id"], ["alice"])

    lib.delete_niche(session, gym["id"])

    assert lib.niches_for(session, ["alice"])["alice"] == []
    assert "gym" not in [n["name"] for n in lib.list_niches(session)]


# ── profiles ───────────────────────────────────────────────────────────

def test_profile_is_created_on_demand_and_keeps_display_casing(session):
    p = lib.get_or_create_profile(session, "TheEllieBarker")

    assert p.username == "theelliebarker"
    assert p.display_username == "TheEllieBarker"


def test_updating_a_rate_stamps_when_it_was_set(session):
    lib.update_profile(session, "alice", rate_override=35.0)
    p = lib.get_or_create_profile(session, "alice")

    assert p.rate_override == 35.0
    assert isinstance(p.rate_override_at, datetime)


def test_clearing_a_rate_drops_the_stamp_too(session):
    lib.update_profile(session, "alice", rate_override=35.0)
    lib.update_profile(session, "alice", rate_override=None)
    p = lib.get_or_create_profile(session, "alice")

    assert p.rate_override is None
    assert p.rate_override_at is None


def test_notes_and_slow_flag_round_trip(session):
    lib.update_profile(session, "alice", slow=True, note="needs a nudge")
    p = lib.get_or_create_profile(session, "alice")

    assert p.slow is True
    assert p.note == "needs a nudge"
