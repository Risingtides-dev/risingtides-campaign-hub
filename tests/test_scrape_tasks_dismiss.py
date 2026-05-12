"""Smoke tests for the dismiss/undismiss endpoints (issue #32).

These cover the contract — what the HTTP API does and how dismissal
flows through the queue + mark-campaign-tracked endpoint. They do not
exercise the Postgres-specific migration path; that lives in
`db.init` and runs against the real DB on Railway boot.
"""
from __future__ import annotations

from campaign_manager import db
from campaign_manager.models import MatchedVideo


def _get_video(session, video_id):
    return session.query(MatchedVideo).filter_by(id=video_id).first()


def test_dismiss_sets_audit_fields(client, seeded_campaign):
    target_id = seeded_campaign["video_ids"][0]

    resp = client.post(
        "/api/scrape-tasks/dismiss",
        json={
            "matched_video_ids": [target_id],
            "dismissed_by": "jake",
            "reason": "wrong sound",
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["dismissed"] == 1
    assert body["requested"] == 1

    with db.get_session() as s:
        row = _get_video(s, target_id)
        assert row.dismissed_at is not None
        assert row.dismissed_by == "jake"
        assert row.dismissed_reason == "wrong sound"


def test_dismiss_is_idempotent(client, seeded_campaign):
    target_id = seeded_campaign["video_ids"][0]

    first = client.post(
        "/api/scrape-tasks/dismiss",
        json={"matched_video_ids": [target_id]},
    )
    assert first.status_code == 200
    assert first.get_json()["dismissed"] == 1

    # Second call should not re-dismiss the same row.
    second = client.post(
        "/api/scrape-tasks/dismiss",
        json={"matched_video_ids": [target_id]},
    )
    assert second.status_code == 200
    assert second.get_json()["dismissed"] == 0


def test_queue_hides_dismissed(client, seeded_campaign):
    dismissed_id = seeded_campaign["video_ids"][0]

    client.post(
        "/api/scrape-tasks/dismiss",
        json={"matched_video_ids": [dismissed_id]},
    )

    resp = client.get("/api/scrape-tasks/queue")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_untracked"] == 2

    campaigns = body["campaigns"]
    assert len(campaigns) == 1
    queue_ids = {v["id"] for v in campaigns[0]["videos"]}
    assert dismissed_id not in queue_ids


def test_undismiss_restores_row(client, seeded_campaign):
    target_id = seeded_campaign["video_ids"][0]

    client.post(
        "/api/scrape-tasks/dismiss",
        json={
            "matched_video_ids": [target_id],
            "dismissed_by": "jake",
            "reason": "wrong sound",
        },
    )

    resp = client.post(
        "/api/scrape-tasks/undismiss",
        json={"matched_video_ids": [target_id]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["undismissed"] == 1

    with db.get_session() as s:
        row = _get_video(s, target_id)
        assert row.dismissed_at is None
        assert row.dismissed_by == ""
        assert row.dismissed_reason == ""


def test_mark_campaign_tracked_skips_dismissed(client, seeded_campaign):
    dismissed_id = seeded_campaign["video_ids"][0]

    client.post(
        "/api/scrape-tasks/dismiss",
        json={"matched_video_ids": [dismissed_id]},
    )

    resp = client.post(
        "/api/scrape-tasks/mark-campaign-tracked",
        json={"slug": seeded_campaign["slug"]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    # Only the two non-dismissed rows should get marked tracked.
    assert body["marked_tracked"] == 2

    with db.get_session() as s:
        row = _get_video(s, dismissed_id)
        # Dismissed row stays untracked — dismiss and track are
        # independent states.
        assert row.tracked_at is None
        assert row.dismissed_at is not None


def test_dismiss_rejects_invalid_body(client, seeded_campaign):
    # Empty list
    resp = client.post("/api/scrape-tasks/dismiss", json={"matched_video_ids": []})
    assert resp.status_code == 400

    # Missing field
    resp = client.post("/api/scrape-tasks/dismiss", json={})
    assert resp.status_code == 400

    # Non-integer ids
    resp = client.post(
        "/api/scrape-tasks/dismiss",
        json={"matched_video_ids": ["not-an-id"]},
    )
    assert resp.status_code == 400
