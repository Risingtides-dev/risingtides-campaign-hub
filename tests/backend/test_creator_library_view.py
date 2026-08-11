"""Assembling the library listing from bookings, profiles and tags."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from campaign_manager.models import Campaign, Creator, CreatorProfile
from campaign_manager.services import creator_library as lib
from campaign_manager.services.creator_library_view import (
    booking_summary,
    build_library,
    rate_for_booking,
)


@pytest.fixture
def session(db):
    with db.get_session() as s:
        yield s


def _campaign(session, slug):
    camp = Campaign(slug=slug, title=slug)
    session.add(camp)
    session.flush()
    return camp


def _book(session, camp, username, rate, posts, added, **kw):
    session.add(Creator(
        campaign_id=camp.id, username=username,
        per_post_rate=rate, total_rate=rate * posts,
        posts_owed=posts, posts_done=kw.get("posts_done", posts),
        added_date=added, status=kw.get("status", "active"),
        paypal_email=kw.get("paypal_email", ""),
    ))
    session.commit()


# ── booking rollup ─────────────────────────────────────────────────────

def test_last_rate_is_the_most_recent_booking_not_an_average(session):
    """The v1 bug: averaging made 39 of 55 creators quote a wrong rate."""
    camp = _campaign(session, "c1")
    _book(session, camp, "alice", rate=10.0, posts=1, added="2026-01-01")
    camp2 = _campaign(session, "c2")
    _book(session, camp2, "alice", rate=40.0, posts=1, added="2026-08-01")

    summary = booking_summary(session)["alice"]
    assert summary["last_rate"] == 40.0
    assert summary["last_booked_at"] == date(2026, 8, 1)
    assert summary["campaigns"] == 2


def test_removed_bookings_are_ignored(session):
    camp = _campaign(session, "c1")
    _book(session, camp, "alice", rate=10.0, posts=1, added="2026-01-01",
          status="removed")
    assert "alice" not in booking_summary(session)


def test_per_post_rate_is_derived_when_missing(session):
    camp = _campaign(session, "c1")
    session.add(Creator(
        campaign_id=camp.id, username="alice",
        per_post_rate=0.0, total_rate=100.0, posts_owed=4,
        added_date="2026-08-01", status="active",
    ))
    session.commit()

    assert booking_summary(session)["alice"]["last_rate"] == 25.0


def test_spend_and_posts_accumulate_across_campaigns(session):
    c1, c2 = _campaign(session, "c1"), _campaign(session, "c2")
    _book(session, c1, "alice", rate=10.0, posts=2, added="2026-01-01")
    _book(session, c2, "alice", rate=20.0, posts=3, added="2026-02-01")

    summary = booking_summary(session)["alice"]
    assert summary["spend"] == 80.0
    assert summary["posts_done"] == 5


# ── the listing ────────────────────────────────────────────────────────

def test_listing_unions_booked_and_scouted_creators(session):
    camp = _campaign(session, "c1")
    _book(session, camp, "booked", rate=10.0, posts=1, added="2026-08-01")
    lib.update_profile(session, "scouted", rate_override=35.0)

    rows = {r["key"]: r for r in build_library(session)}
    assert set(rows) == {"booked", "scouted"}
    assert rows["scouted"]["scouted"] is True
    assert rows["booked"]["scouted"] is False


def test_scouted_creator_reports_its_asking_rate(session):
    lib.update_profile(session, "scouted", rate_override=35.0)
    row = build_library(session)[0]

    assert row["rate"] == 35.0
    assert row["rate_source"] == "override"
    assert row["campaigns"] == 0


def test_niches_are_attached_to_the_row(session):
    lib.set_niches(session, "alice", ["gym", "anime"])
    row = {r["key"]: r for r in build_library(session)}["alice"]
    assert row["niches"] == ["anime", "gym"]


def test_projected_cpm_is_computed_from_the_current_rate(session):
    """Cached windows carry no CPM; it is derived per request so an edited
    rate takes effect without waiting for the stats job."""
    profile = lib.get_or_create_profile(session, "alice")
    profile.stats = {"w60": {
        "posts": 2, "total": 50_000, "median": 25_000, "avg": 25_000,
        "p25": 20_000, "peak": 30_000, "viral_rate": 0.0,
        "pcpm": None, "floor": None,
    }}
    session.commit()
    lib.update_profile(session, "alice", rate_override=50.0)

    row = build_library(session, window="w60")[0]
    assert row["stats"]["w60"]["pcpm"] == 2.0
    assert row["stats"]["w60"]["floor"] == 2.5


def test_creators_without_data_rank_last(session):
    """An unknown CPM must not read as the cheapest option."""
    known = lib.get_or_create_profile(session, "known")
    known.stats = {"w60": {
        "posts": 1, "total": 10_000, "median": 10_000, "avg": 10_000,
        "p25": 10_000, "peak": 10_000, "viral_rate": 0.0,
        "pcpm": None, "floor": None,
    }}
    session.commit()
    lib.update_profile(session, "known", rate_override=10.0)
    lib.update_profile(session, "unknown", rate_override=10.0)

    order = [r["key"] for r in build_library(session, window="w60")]
    assert order.index("known") < order.index("unknown")


def test_display_casing_survives_the_roundtrip(session):
    camp = _campaign(session, "c1")
    _book(session, camp, "TheEllieBarker", rate=10.0, posts=1, added="2026-08-01")

    row = {r["key"]: r for r in build_library(session)}["theelliebarker"]
    assert row["username"] == "TheEllieBarker"


# ── booking auto-fill ──────────────────────────────────────────────────

def test_rate_for_booking_prefers_a_newer_manual_rate(session):
    camp = _campaign(session, "c1")
    _book(session, camp, "alice", rate=20.0, posts=1, added="2026-07-01")
    lib.update_profile(session, "alice", rate_override=40.0)

    result = rate_for_booking(session, "alice")
    assert result["rate"] == 40.0
    assert result["source"] == "override"
    assert result["last_rate"] == 20.0


def test_rate_for_booking_falls_back_to_the_last_booking(session):
    camp = _campaign(session, "c1")
    _book(session, camp, "alice", rate=22.5, posts=2, added="2026-07-01")

    result = rate_for_booking(session, "alice")
    assert result["rate"] == 22.5
    assert result["source"] == "booking"


def test_rate_for_booking_on_an_unknown_creator(session):
    result = rate_for_booking(session, "nobody")
    assert result["rate"] is None
    assert result["source"] == "none"
