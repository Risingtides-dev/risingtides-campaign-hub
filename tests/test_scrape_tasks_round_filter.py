"""CAMP-42 — round 1 posts must not leak into round 2's scrape-tasks queue.

When a campaign reuses creators from a previous round, the previous
round's matched_videos rows persist (they're scoped per-campaign, but
the same creators show up on both). Cobrand only dedupes within a
single round, so leaking those pre-start-date posts into the round-2
queue produces duplicate uploads in the client report.

The queue endpoint now filters matched_videos by the campaign's
``start_date`` and the ``video_posted_before_start`` helper.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from campaign_manager import db
from campaign_manager.models import Campaign, MatchedVideo
from campaign_manager.utils.helpers import video_posted_before_start


@pytest.fixture
def round2_campaign(app):
    """Round-2 campaign with three matched videos: one before start, two on/after."""
    with db.get_session() as s:
        camp = Campaign(
            slug="going-gone-r2",
            title="Going Gone R2",
            artist="Josiah and the Bonnevilles",
            song="Going Gone",
            start_date="2026-05-01",
            round="2",
        )
        s.add(camp)
        s.commit()
        camp_id = camp.id

        s.add(MatchedVideo(
            campaign_id=camp_id,
            url="https://www.tiktok.com/@r1user/video/1",
            account="@r1user",
            timestamp="2026-04-15T14:32:00",
            upload_date="20260415",
            match_strategy="sound_id",
        ))
        s.add(MatchedVideo(
            campaign_id=camp_id,
            url="https://www.tiktok.com/@r2user/video/2",
            account="@r2user",
            timestamp="2026-05-01T08:00:00",
            upload_date="20260501",
            match_strategy="sound_id",
        ))
        s.add(MatchedVideo(
            campaign_id=camp_id,
            url="https://www.tiktok.com/@r2user2/video/3",
            account="@r2user2",
            timestamp="2026-05-10T18:15:00",
            upload_date="20260510",
            match_strategy="sound_id",
        ))
        s.commit()

        ids = [
            v.id for v in s.query(MatchedVideo)
            .filter_by(campaign_id=camp_id)
            .order_by(MatchedVideo.id)
            .all()
        ]

    return {"slug": "going-gone-r2", "campaign_id": camp_id, "video_ids": ids}


def test_queue_excludes_videos_before_campaign_start(client, round2_campaign):
    """The pre-start-date row must not appear in the queue."""
    body = client.get("/api/scrape-tasks/queue").get_json()

    assert body["total_untracked"] == 2

    assert len(body["campaigns"]) == 1
    bucket = body["campaigns"][0]
    assert bucket["slug"] == round2_campaign["slug"]
    assert bucket["round"] == "2"

    queue_urls = {v["url"] for v in bucket["videos"]}
    assert "https://www.tiktok.com/@r1user/video/1" not in queue_urls
    assert "https://www.tiktok.com/@r2user/video/2" in queue_urls
    assert "https://www.tiktok.com/@r2user2/video/3" in queue_urls


def test_queue_keeps_legacy_rows_without_dates(client, round2_campaign):
    """Rows with no timestamp/upload_date should fail open (kept in queue)."""
    with db.get_session() as s:
        s.add(MatchedVideo(
            campaign_id=round2_campaign["campaign_id"],
            url="https://www.tiktok.com/@legacy/video/9",
            account="@legacy",
            timestamp="",
            upload_date="",
            match_strategy="sound_id",
        ))
        s.commit()

    body = client.get("/api/scrape-tasks/queue").get_json()
    urls = {v["url"] for c in body["campaigns"] for v in c["videos"]}
    assert "https://www.tiktok.com/@legacy/video/9" in urls


def test_queue_no_start_date_passes_everything(client):
    """A campaign without a start_date should keep its existing behavior:
    no rows are filtered. This guards against an over-eager filter that
    would empty the queue for the legacy in-flight campaigns that never
    had a start_date set."""
    with db.get_session() as s:
        camp = Campaign(
            slug="legacy-no-start",
            title="Legacy",
            start_date="",
        )
        s.add(camp)
        s.commit()
        camp_id = camp.id

        s.add(MatchedVideo(
            campaign_id=camp_id,
            url="https://www.tiktok.com/@u/video/old",
            account="@u",
            timestamp="2020-01-01T00:00:00",
            upload_date="20200101",
        ))
        s.commit()

    body = client.get("/api/scrape-tasks/queue").get_json()
    urls = {v["url"] for c in body["campaigns"] for v in c["videos"]}
    assert "https://www.tiktok.com/@u/video/old" in urls


def test_mark_campaign_tracked_skips_pre_start_rows(client, round2_campaign):
    """``mark-campaign-tracked`` must mirror the queue's date scope so we
    don't claim we uploaded round-1 posts under round 2."""
    resp = client.post(
        "/api/scrape-tasks/mark-campaign-tracked",
        json={"slug": round2_campaign["slug"], "tracked_by": "jake"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["marked_tracked"] == 2

    pre_start_id = round2_campaign["video_ids"][0]
    with db.get_session() as s:
        row = s.query(MatchedVideo).filter_by(id=pre_start_id).first()
        assert row.tracked_at is None
        assert row.tracked_by == ""


# ---------------------------------------------------------------------------
# Unit tests for the helper itself
# ---------------------------------------------------------------------------

def test_video_posted_before_start_uses_timestamp():
    assert video_posted_before_start(
        {"timestamp": "2026-04-30T23:59:59", "upload_date": "20260430"},
        "2026-05-01",
    )
    assert not video_posted_before_start(
        {"timestamp": "2026-05-01T00:00:00", "upload_date": "20260501"},
        "2026-05-01",
    )
    assert not video_posted_before_start(
        {"timestamp": "2026-05-10T18:15:00", "upload_date": "20260510"},
        "2026-05-01",
    )


def test_video_posted_before_start_falls_back_to_upload_date():
    assert video_posted_before_start(
        {"timestamp": "", "upload_date": "20260415"},
        "2026-05-01",
    )
    assert not video_posted_before_start(
        {"timestamp": "", "upload_date": "20260501"},
        "2026-05-01",
    )


def test_video_posted_before_start_fails_open_on_missing_data():
    assert not video_posted_before_start({}, "2026-05-01")
    assert not video_posted_before_start({"timestamp": "", "upload_date": ""}, "2026-05-01")
    assert not video_posted_before_start({"timestamp": "garbage"}, "2026-05-01")


def test_video_posted_before_start_no_campaign_start():
    assert not video_posted_before_start(
        {"timestamp": "2020-01-01T00:00:00"},
        "",
    )
