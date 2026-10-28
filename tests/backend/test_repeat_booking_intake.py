"""Tests for repeat-booking intake (F-HUB-REPEAT-BOOKING-DROPPED-1028).

A CRM booking whose title slugs to an existing campaign is a repeat booking,
not a duplicate: it must become its own round-suffixed campaign keyed by
notion_page_id. Both intake paths (/webhooks/notion and /webhooks/notion/sync)
share one implementation, so these tests run each scenario against both.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


pytestmark = pytest.mark.integration


SOUND = "https://www.tiktok.com/music/shared-1234567890123456789"


def _entry(page_id, title="Big Moochie grape - Still signed to Dolph", *,
           artist="Big Moochie Grape", song="Still Signed to Dolph",
           budget=1250.0, round_value="", captions=None,
           content_types=None, sound=SOUND):
    """A normalized CRM entry with the same shape as query_new_clients rows."""
    return {
        "notion_page_id": page_id,
        "title": title,
        "slug": "big_moochie_grape_still_signed_to_dolph",
        "artist": artist,
        "song": song,
        "official_sound": sound,
        "sound_id": "1234567890123456789",
        "insta_sound": "",
        "cobrand_share_url": "",
        "start_date": "",
        "budget": budget,
        "campaign_stage": "",
        "round": round_value,
        "label": "",
        "project_lead": [],
        "client_email": "",
        "content_types": content_types or [],
        "internal_captions": captions,
        "platform_split": {},
    }


def _post_webhook(client, page_id, *, round_value="", budget=1250.0, artist=None, song=None, sound=SOUND):
    return client.post("/api/webhooks/notion", json={
        "artist": artist or "Big Moochie Grape",
        "song": song or "Still Signed to Dolph",
        "title": "Big Moochie grape - Still signed to Dolph",
        "budget": str(budget),
        "round": round_value,
        "notion_page_id": page_id,
        "tiktok_sound_link": sound,
    })


def _post_sync(client, entries):
    with patch("campaign_manager.services.notion.query_new_clients", return_value=entries), patch(
        "campaign_manager.services.notion.fetch_page_campaign_fields", return_value=None,
    ):
        return client.post("/api/webhooks/notion/sync")


@pytest.mark.parametrize("path", ["webhook", "sync"])
def test_t1_two_rounds_same_title_sound_become_two_campaigns(client, db, path):
    """T1: two CRM entries, same title + sound, second 'Round 2' -> two campaigns;
    second slug '<base>_round_2'; its budget is its own Media Spend."""
    first = _entry("page-r1", budget=1000.0)
    second = _entry("page-r2", budget=1250.0, round_value="Round 2")

    if path == "webhook":
        r1 = _post_webhook(client, "page-r1", budget=1000.0)
        assert r1.status_code == 201
        r2 = _post_webhook(client, "page-r2", budget=1250.0, round_value="Round 2")
        assert r2.status_code == 201, r2.get_json()
        assert r2.get_json()["slug"] == "big_moochie_grape_still_signed_to_dolph_round_2"
    else:
        resp = _post_sync(client, [first, second])
        assert resp.status_code == 200
        body = resp.get_json()
        assert {c["slug"] for c in body["created"]} == {
            "big_moochie_grape_still_signed_to_dolph",
            "big_moochie_grape_still_signed_to_dolph_round_2",
        }, body

    base = db.get_campaign("big_moochie_grape_still_signed_to_dolph")
    round2 = db.get_campaign("big_moochie_grape_still_signed_to_dolph_round_2")
    assert base is not None
    assert round2 is not None
    assert base["budget"] == 1000.0
    assert round2["budget"] == 1250.0
    assert round2["round"] == "Round 2"
    # Each round tracks its own CRM page.
    assert round2["notion_page_id"] == "page-r2"


@pytest.mark.parametrize("path", ["webhook", "sync"])
def test_t2_same_page_id_is_idempotent(client, db, path):
    """T2: the SAME notion_page_id seen twice -> one campaign (no duplicate)."""
    entry = _entry("page-same", budget=1250.0)

    if path == "webhook":
        first = _post_webhook(client, "page-same", budget=1250.0)
        assert first.status_code == 201
        second = _post_webhook(client, "page-same", budget=1250.0)
        assert second.status_code == 200, second.get_json()
    else:
        resp = _post_sync(client, [entry, dict(entry)])
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["created"]) == 1, body
        assert {s["slug"] for s in body["skipped"]} == {
            "big_moochie_grape_still_signed_to_dolph"
        }

    assert db.get_campaign("big_moochie_grape_still_signed_to_dolph") is not None
    assert "big_moochie_grape_still_signed_to_dolph_round_2" not in db.get_campaign_slugs()


def test_t2b_sync_recreates_no_duplicate_after_webhook(client, db):
    """T2 race: webhook already created the page; sync must skip, not duplicate."""
    assert _post_webhook(client, "page-race").status_code == 201
    entry = _entry("page-race")
    resp = _post_sync(client, [entry])
    body = resp.get_json()
    assert body["created"] == []
    assert {s["slug"] for s in body["skipped"]} == {
        "big_moochie_grape_still_signed_to_dolph"
    }
    assert len(db.get_campaign_slugs()) == 1


@pytest.mark.parametrize("path", ["webhook", "sync"])
def test_t3_round_sibling_sound_allowed_but_different_song_refused(client, db, path):
    """T3: reused sound allowed only for a new round of the same artist+song;
    same sound on a DIFFERENT song is still 'duplicate sound URL'."""
    first = _entry("page-r1", budget=1000.0)

    # Different song, same sound -> refused.
    other_song = _entry(
        "page-other", title="Other - Different Song",
        artist="Other", song="Different Song", budget=500.0,
    )
    other_song["slug"] = "other_different_song"

    if path == "webhook":
        assert _post_webhook(client, "page-r1", budget=1000.0).status_code == 201
        dup = client.post("/api/webhooks/notion", json={
            "artist": "Other", "song": "Different Song",
            "title": "Other - Different Song", "budget": "500",
            "notion_page_id": "page-other", "tiktok_sound_link": SOUND,
        })
        assert dup.status_code == 409
        assert dup.get_json()["code"] == "duplicate"
        # Same artist+song, new page, explicit round -> allowed.
        r2 = _post_webhook(client, "page-r2", budget=1250.0, round_value="Round 2")
        assert r2.status_code == 201, r2.get_json()
    else:
        resp = _post_sync(client, [first, other_song])
        body = resp.get_json()
        assert {c["slug"] for c in body["created"]} == {
            "big_moochie_grape_still_signed_to_dolph"
        }
        assert {s["slug"] for s in body["skipped"]} == {"other_different_song"}
        assert any(s["reason"] == "duplicate sound URL" for s in body["skipped"])
        # Same artist+song, new page, explicit round -> allowed on next sync.
        resp = _post_sync(client, [_entry("page-r2", budget=1250.0, round_value="Round 2")])
        body = resp.get_json()
        assert {c["slug"] for c in body["created"]} == {
            "big_moochie_grape_still_signed_to_dolph_round_2"
        }

    assert db.campaign_exists("other_different_song") is False
    assert "big_moochie_grape_still_signed_to_dolph_round_2" in db.get_campaign_slugs()


@pytest.mark.parametrize("path", ["webhook", "sync"])
def test_t4_no_round_gets_next_free_round_number(client, db, path):
    """T4: no Round set but a new page id with the same title -> next free
    '_round_N' slug (N = existing count + 1), never a 409."""
    first = _entry("page-r1", budget=1000.0)
    second = _entry("page-no-round", budget=1250.0)

    if path == "webhook":
        assert _post_webhook(client, "page-r1", budget=1000.0).status_code == 201
        resp = _post_webhook(client, "page-no-round", budget=1250.0)
        assert resp.status_code == 201, resp.get_json()
        assert resp.get_json()["slug"] == "big_moochie_grape_still_signed_to_dolph_round_2"
    else:
        resp = _post_sync(client, [first, second])
        body = resp.get_json()
        assert {c["slug"] for c in body["created"]} == {
            "big_moochie_grape_still_signed_to_dolph",
            "big_moochie_grape_still_signed_to_dolph_round_2",
        }

    # A third round, still no explicit Round, gets the next free number.
    third = _entry("page-no-round-3", budget=750.0)
    if path == "webhook":
        resp = _post_webhook(client, "page-no-round-3", budget=750.0)
        assert resp.status_code == 201
        assert resp.get_json()["slug"] == "big_moochie_grape_still_signed_to_dolph_round_3"
    else:
        resp = _post_sync(client, [third])
        assert {c["slug"] for c in resp.get_json()["created"]} == {
            "big_moochie_grape_still_signed_to_dolph_round_3"
        }


def test_t5_existing_row_refresh_pass_unchanged(client, db):
    """T5: the existing-row refresh pass (content_types / internal_captions by
    notion_page_id) is unchanged for existing fixtures."""
    db.save_campaign("old_campaign", {
        "title": "Old", "notion_page_id": "page-old", "content_types": [],
    })
    with patch(
        "campaign_manager.services.notion.query_new_clients", return_value=[]
    ), patch(
        "campaign_manager.services.notion.fetch_page_campaign_fields",
        return_value={"content_types": ["Trucktok", "Coffee"], "internal_captions": None},
    ) as fetch:
        resp = client.post("/api/webhooks/notion/sync")
    body = resp.get_json()
    assert {"slug": "old_campaign", "content_types": ["Trucktok", "Coffee"]} in body["refreshed"]
    assert db.get_campaign("old_campaign")["content_types"] == ["Trucktok", "Coffee"]
    fetch.assert_called_once_with("page-old")


def test_t5b_unreadable_page_never_empties(client, db):
    db.save_campaign("unreadable", {
        "title": "U", "notion_page_id": "page-gone", "content_types": ["Trucktok"],
        "internal_captions": "kept line",
    })
    with patch(
        "campaign_manager.services.notion.query_new_clients", return_value=[]
    ), patch(
        "campaign_manager.services.notion.fetch_page_campaign_fields", return_value=None,
    ):
        resp = client.post("/api/webhooks/notion/sync")
    assert resp.get_json()["refreshed"] == []
    meta = db.get_campaign("unreadable")
    assert meta["content_types"] == ["Trucktok"]
    assert meta["internal_captions"] == "kept line"


def test_t7_operator_edited_fields_untouched(client, db):
    """T7: nothing on an existing campaign is stamped by a repeat-booking row."""
    db.save_campaign("big_moochie_grape_still_signed_to_dolph", {
        "title": "Big Moochie grape - Still signed to Dolph",
        "notion_page_id": "page-r1",
        "artist": "Big Moochie Grape",
        "song": "Still Signed to Dolph",
        "budget": 1000.0,
        "label": "Operator Edited Label",
        "internal_captions": "round one line",
        "content_types": [],
    })
    # New page, same title -> must become a separate round, leaving the
    # original row byte-identical on operator-edited fields.
    entry = _entry("page-r2", budget=1250.0, round_value="Round 2",
                   captions="round two line")
    resp = _post_sync(client, [entry])
    assert {c["slug"] for c in resp.get_json()["created"]} == {
        "big_moochie_grape_still_signed_to_dolph_round_2"
    }
    original = db.get_campaign("big_moochie_grape_still_signed_to_dolph")
    assert original["budget"] == 1000.0
    assert original["label"] == "Operator Edited Label"
    assert original["internal_captions"] == "round one line"
    assert original["notion_page_id"] == "page-r1"
