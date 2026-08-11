"""Creator Library HTTP surface."""
from __future__ import annotations

import pytest

from campaign_manager.models import Campaign, Creator


@pytest.fixture
def booked(db):
    """One creator with two bookings, the newer one at $40/post."""
    with db.get_session() as s:
        camp_a = Campaign(slug="old", title="Old")
        camp_b = Campaign(slug="new", title="New")
        s.add_all([camp_a, camp_b])
        s.flush()
        s.add(Creator(
            campaign_id=camp_a.id, username="alice", per_post_rate=10.0,
            total_rate=10.0, posts_owed=1, posts_done=1,
            added_date="2026-01-01", status="active",
        ))
        s.add(Creator(
            campaign_id=camp_b.id, username="alice", per_post_rate=40.0,
            total_rate=80.0, posts_owed=2, posts_done=2,
            added_date="2026-08-01", status="active",
        ))
        s.commit()


# ── vocabulary ─────────────────────────────────────────────────────────

def test_niches_are_seeded_on_first_read(client):
    body = client.get("/api/library/niches").get_json()
    names = [n["name"] for n in body["niches"]]

    assert "pov" in names
    assert "anime" in names
    assert "pinterest moodboard" in names
    assert body["count"] == len(names)


def test_create_niche_then_see_it_listed(client):
    made = client.post("/api/library/niches", json={"name": "Drift Cars"})
    assert made.status_code == 201
    assert made.get_json()["name"] == "drift cars"

    names = [n["name"] for n in client.get("/api/library/niches").get_json()["niches"]]
    assert "drift cars" in names


def test_create_niche_rejects_a_blank_name(client):
    assert client.post("/api/library/niches", json={"name": "  "}).status_code == 400


def test_rename_and_merge_over_http(client):
    a = client.post("/api/library/niches", json={"name": "gym"}).get_json()
    b = client.post("/api/library/niches", json={"name": "gym motivation"}).get_json()

    client.post(f"/api/library/niches/{a['id']}/apply", json={"usernames": ["alice"]})
    client.post(f"/api/library/niches/{a['id']}/merge", json={"into": b["id"]})

    names = [n["name"] for n in client.get("/api/library/niches").get_json()["niches"]]
    assert "gym" not in names

    creators = client.get("/api/library/creators").get_json()["creators"]
    alice = next(c for c in creators if c["key"] == "alice")
    assert alice["niches"] == ["gym motivation"]


def test_delete_niche(client):
    made = client.post("/api/library/niches", json={"name": "temp"}).get_json()
    assert client.delete(f"/api/library/niches/{made['id']}").status_code == 200
    assert client.delete(f"/api/library/niches/{made['id']}").status_code == 404


def test_bulk_apply_tags_a_batch(client):
    made = client.post("/api/library/niches", json={"name": "gym"}).get_json()
    res = client.post(
        f"/api/library/niches/{made['id']}/apply",
        json={"usernames": ["alice", "bob", "carol"]},
    )
    assert res.get_json() == {"ok": True, "tagged": 3, "requested": 3}


def test_bulk_apply_requires_usernames(client):
    made = client.post("/api/library/niches", json={"name": "gym"}).get_json()
    res = client.post(f"/api/library/niches/{made['id']}/apply", json={"usernames": []})
    assert res.status_code == 400


def test_apply_to_a_missing_niche_is_404(client):
    res = client.post("/api/library/niches/9999/apply", json={"usernames": ["alice"]})
    assert res.status_code == 404


# ── roster ─────────────────────────────────────────────────────────────

def test_listing_uses_the_most_recent_booking_rate(client, booked):
    creators = client.get("/api/library/creators").get_json()["creators"]
    alice = next(c for c in creators if c["key"] == "alice")

    assert alice["rate"] == 40.0
    assert alice["rate_source"] == "booking"
    assert alice["campaigns"] == 2
    assert alice["scouted"] is False


def test_window_parameter_is_validated(client):
    body = client.get("/api/library/creators?window=nonsense").get_json()
    assert body["window"] == "w60"


def test_add_a_scouted_creator(client):
    res = client.post("/api/library/creators", json={
        "username": "@sarah.lifts", "rate": 35.0, "niches": ["gym", "grwm"],
    })
    assert res.status_code == 201

    creators = client.get("/api/library/creators").get_json()["creators"]
    sarah = next(c for c in creators if c["key"] == "sarah.lifts")
    assert sarah["scouted"] is True
    assert sarah["rate"] == 35.0
    assert sarah["niches"] == ["grwm", "gym"]
    assert sarah["campaigns"] == 0


def test_adding_the_same_creator_twice_conflicts(client):
    client.post("/api/library/creators", json={"username": "sarah"})
    assert client.post(
        "/api/library/creators", json={"username": "sarah"}
    ).status_code == 409


def test_add_creator_requires_a_username(client):
    assert client.post("/api/library/creators", json={}).status_code == 400


def test_add_creator_rejects_a_non_numeric_rate(client):
    res = client.post("/api/library/creators", json={"username": "x", "rate": "cheap"})
    assert res.status_code == 400


# ── rate memory ────────────────────────────────────────────────────────

def test_saved_rate_beats_an_older_booking(client, booked):
    client.patch("/api/library/creators/alice", json={"rate": 55.0})

    body = client.get("/api/library/creators/alice/rate").get_json()
    assert body["rate"] == 55.0
    assert body["source"] == "override"
    assert body["last_rate"] == 40.0


def test_clearing_the_saved_rate_restores_the_booking_rate(client, booked):
    client.patch("/api/library/creators/alice", json={"rate": 55.0})
    client.patch("/api/library/creators/alice", json={"rate": None})

    body = client.get("/api/library/creators/alice/rate").get_json()
    assert body["rate"] == 40.0
    assert body["source"] == "booking"


def test_rate_endpoint_on_an_unknown_creator(client):
    body = client.get("/api/library/creators/nobody/rate").get_json()
    assert body["rate"] is None and body["source"] == "none"


def test_patch_rejects_a_bad_rate(client):
    res = client.patch("/api/library/creators/alice", json={"rate": "free"})
    assert res.status_code == 400


def test_patch_with_nothing_to_change_is_rejected(client):
    assert client.patch("/api/library/creators/alice", json={}).status_code == 400


def test_slow_flag_and_note_round_trip(client):
    client.patch(
        "/api/library/creators/alice",
        json={"slow": True, "note": "needs a nudge"},
    )
    creators = client.get("/api/library/creators").get_json()["creators"]
    alice = next(c for c in creators if c["key"] == "alice")

    assert alice["slow"] is True
    assert alice["note"] == "needs a nudge"


# ── tagging a single creator ───────────────────────────────────────────

def test_put_niches_replaces_the_set(client):
    client.put("/api/library/creators/alice/niches", json={"niches": ["gym", "anime"]})
    res = client.put("/api/library/creators/alice/niches", json={"niches": ["gym"]})

    assert res.get_json()["niches"] == ["gym"]


def test_put_niches_creates_unknown_names(client):
    client.put(
        "/api/library/creators/alice/niches",
        json={"niches": ["something ultra specific"]},
    )
    names = [n["name"] for n in client.get("/api/library/niches").get_json()["niches"]]
    assert "something ultra specific" in names


def test_put_niches_requires_a_list(client):
    res = client.put("/api/library/creators/alice/niches", json={"niches": "gym"})
    assert res.status_code == 400


def test_usernames_with_dots_survive_routing(client):
    """`4real.corey` must not be truncated at the dot by URL routing."""
    client.put(
        "/api/library/creators/4real.corey/niches", json={"niches": ["meme"]},
    )
    creators = client.get("/api/library/creators").get_json()["creators"]
    assert any(c["key"] == "4real.corey" for c in creators)
