"""Booking efficiency uses the same paid cohort and round ownership everywhere."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from campaign_manager.models import Campaign, Creator, MatchedVideo
from campaign_manager.services.booking_efficiency import (
    calculate_creator_metrics,
    generate_efficiency_report,
)


def _campaign(session, slug, start="", sound="123456", **kwargs):
    campaign = Campaign(slug=slug, title=slug, start_date=start, sound_id=sound, **kwargs)
    session.add(campaign)
    session.flush()
    return campaign


def _booking(session, campaign, username="creator", platform="tiktok", spend=100, posts=1):
    session.add(Creator(campaign_id=campaign.id, username=username, platform=platform,
                        total_rate=spend, posts_owed=posts))


def _video(session, campaign, url, posted, views, username="@creator", platform="tiktok",
           sound="123456", dismissed=False, first_seen=None):
    session.add(MatchedVideo(
        campaign_id=campaign.id, url=url, account=username, platform=platform,
        upload_date=posted, extracted_sound_id=sound, views=views, likes=views // 10,
        first_seen_at=first_seen or datetime.now(),
        dismissed_at=datetime.now() if dismissed else None,
    ))


def test_round_ownership_excludes_wrong_round_and_keeps_secondary_sound(db):
    with db.get_session() as session:
        first = _campaign(session, "first", "2026-04-01", additional_sounds=["654321"])
        second = _campaign(session, "second", "2026-05-01", completion_status="completed")
        _booking(session, first)
        _booking(session, second)
        _video(session, first, "first-ok", "20260415", 100)
        _video(session, first, "first-late", "20260515", 10000)
        _video(session, first, "secondary", "20260515", 200, sound="654321")
        _video(session, second, "second-early", "20260415", 20000)
        _video(session, second, "second-ok", "20260515", 300)
        _video(session, second, "undated", "", 30000)
        _video(session, second, "dismissed", "20260515", 40000, dismissed=True)
        session.commit()

        metrics = calculate_creator_metrics(session, "creator")
        assert metrics.total_spend == 200
        assert metrics.total_views == 600
        assert metrics.total_engagement == 60
        assert generate_efficiency_report(session).total_views == 600


def test_identity_variants_merge_within_platform_but_platforms_stay_separate(db, client):
    with db.get_session() as session:
        first = _campaign(session, "variants-first")
        second = _campaign(session, "variants-second")
        _booking(session, first, " @Creator ", spend=100)
        _booking(session, second, "CREATOR", spend=200)
        _booking(session, second, "creator", platform="instagram", spend=50)
        _video(session, first, "tt-first", "", 1000, username=" Creator ")
        _video(session, second, "tt-second", "", 2000, username="@CREATOR")
        _video(session, second, "ig", "", 50000, username="creator", platform="instagram")
        session.commit()

        metrics = calculate_creator_metrics(session, "@Creator")
        assert metrics.total_spend == 300
        assert metrics.total_views == 3000
        assert metrics.platform == "tiktok"
        report = generate_efficiency_report(session)
        assert report.total_creators_analyzed == 2
        assert report.total_spend == 350
        assert report.total_views == 53000

    rows = client.get("/api/efficiency/leaderboard").get_json()
    ranked = [row for tier in ("elite", "high_value", "solid", "standard", "undervalued", "overpriced")
              for row in rows[tier]]
    assert {(row["creator_username"], row["platform"]) for row in ranked} == {
        ("creator", "tiktok"), ("creator", "instagram"),
    }
    instagram = client.get("/api/efficiency/creator/creator?platform=instagram").get_json()
    assert instagram["total_views"] == 50000
    assert instagram["total_spend"] == 50


def test_valid_round_posts_do_not_depend_on_scraper_observation_timestamp(db):
    with db.get_session() as session:
        campaign = _campaign(session, "old-observation", "2026-04-01")
        _booking(session, campaign)
        _video(session, campaign, "old-seen", "20260415", 100,
               first_seen=datetime.now() - timedelta(days=120))
        session.flush()
        session.add(MatchedVideo(campaign_id=campaign.id, url="never-stamped", account="@creator",
                                 upload_date="20260416", extracted_sound_id="123456",
                                 views=200, likes=20, first_seen_at=None))
        session.commit()
        assert calculate_creator_metrics(session, "creator").total_views == 300


def test_report_and_single_creator_share_ranked_metrics(db, client):
    with db.get_session() as session:
        campaign = _campaign(session, "rank-parity")
        for index in range(12):
            username = f"creator-{index:02d}"
            _booking(session, campaign, username, spend=100)
            _video(session, campaign, username, "", 12000 - index * 500, username=username)
        session.commit()

    leaderboard = client.get("/api/efficiency/leaderboard").get_json()
    row = next(row for row in leaderboard["elite"] if row["creator_username"] == "creator-00")
    single = client.get("/api/efficiency/creator/creator-00").get_json()
    assert single == row


def test_price_opportunities_match_gap_direction_and_insights_are_consistent(db, client):
    with db.get_session() as session:
        campaign = _campaign(session, "price-opportunities")
        for index in range(40):
            username = f"priced-{index:02d}"
            # Rates vary independently of descending ROI, within each rank band.
            rate = 400 if index % 2 == 0 else 100
            _booking(session, campaign, username, spend=rate)
            _video(session, campaign, username, "", (1000 - index * 20) * rate, username=username)
        session.commit()

    report = client.get("/api/efficiency/report").get_json()
    under = report["undervalued_deals"]
    over = report["overpriced_creators"]
    assert under and over
    assert all(row["pricing_gap_pct"] < -20 and row["total_views"] > 0 for row in under)
    assert all(row["pricing_gap_pct"] > 20 for row in over)
    assert not ({row["creator_username"] for row in under} & {row["creator_username"] for row in over})
    insights = client.get("/api/efficiency/insights").get_json()
    findings = {row["category"]: row for row in insights["key_findings"]}
    assert set(findings["undervalued_opportunity"]["creators"]) == {
        row["creator_username"] for row in under
    }
    assert set(findings["pricing_opportunity"]["creators"]) == {
        row["creator_username"] for row in over
    }
    # Historical outcomes alone cannot support fixed future uplift/savings.
    assert insights["recommendations"] == []


def test_low_spend_concentration_is_not_a_dependency_warning(db, client):
    with db.get_session() as session:
        campaign = _campaign(session, "low-concentration")
        for index in range(40):
            username = f"concentration-{index:02d}"
            spend = 1 if index < 10 else 1000
            _booking(session, campaign, username, spend=spend)
            _video(session, campaign, username, "", (10000 - index * 100) * spend, username=username)
        session.commit()
    insights = client.get("/api/efficiency/insights").get_json()
    assert not any(row["category"] == "elite_concentration" for row in insights["key_findings"])


def test_cohort_boundary_uses_campaign_creation_not_post_observation(db):
    with db.get_session() as session:
        older = _campaign(session, "outside-cohort", created_at=datetime.now() - timedelta(days=120))
        recent = _campaign(session, "inside-cohort")
        _booking(session, older, spend=10000)
        _booking(session, recent, spend=100)
        _video(session, older, "old-campaign", "", 50000)
        _video(session, recent, "recent-campaign", "", 1000)
        session.commit()
        report = generate_efficiency_report(session, days=90)
        assert report.total_campaigns == 1
        assert report.total_spend == 100
        assert report.total_views == 1000


def test_zero_promised_posts_cannot_create_a_false_discount(db):
    with db.get_session() as session:
        campaign = _campaign(session, "no-promised-posts")
        for index in range(20):
            username = f"no-posts-{index:02d}"
            _booking(session, campaign, username, posts=0)
            _video(session, campaign, username, "", 1000 - index, username=username)
        session.commit()
        report = generate_efficiency_report(session)
        assert report.undervalued_deals == []
        assert all(row.pricing_gap_pct == 0 for row in report.creators)


def test_even_cohort_median_averages_the_two_middle_rois(db):
    with db.get_session() as session:
        campaign = _campaign(session, "median")
        _booking(session, campaign, "one")
        _booking(session, campaign, "two")
        _video(session, campaign, "one", "", 100, username="one")
        _video(session, campaign, "two", "", 300, username="two")
        session.commit()
        assert generate_efficiency_report(session).median_roi == 2


@pytest.mark.parametrize("size", [1, 25])
def test_report_query_count_is_bounded_as_creator_cohort_grows(db, size):
    with db.get_session() as session:
        campaign = _campaign(session, "bounded-cohort")
        for index in range(size):
            username = f"bounded-{index:02d}"
            _booking(session, campaign, username)
            _video(session, campaign, username, "", 1000, username=username)
        session.commit()
        selects = []

        def record(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(db._engine, "before_cursor_execute", record)
        try:
            report = generate_efficiency_report(session)
        finally:
            event.remove(db._engine, "before_cursor_execute", record)
        assert report.total_creators_analyzed == size
        assert len(selects) <= 5


@pytest.mark.parametrize("days", ["0", "-1", "999999999999999"])
def test_invalid_analysis_window_returns_validation_error(client, days):
    assert client.get(f"/api/efficiency/report?days={days}").status_code == 400
