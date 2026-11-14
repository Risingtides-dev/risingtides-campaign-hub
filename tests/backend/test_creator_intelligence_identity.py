"""Creator analysis keeps handles, platforms and campaign rounds distinct."""
from datetime import datetime, timedelta

from sqlalchemy import event

from campaign_manager.models import Campaign, Creator, MatchedVideo
from campaign_manager.services.creator_intelligence import (
    breaker_leaderboard, creator_drilldown, list_sounds, rebook_suggestions, sound_fit,
)


def campaign(session, slug, sound="sound-1", **kwargs):
    row = Campaign(slug=slug, title=slug, artist="Artist", song=slug, sound_id=sound, **kwargs)
    session.add(row)
    session.flush()
    return row


def post(session, camp, account, views=100_000, **kwargs):
    row = MatchedVideo(
        campaign_id=camp.id, account=account, views=views,
        url=f"https://example.test/post/{len(session.new)}-{account}-{views}",
        extracted_sound_id=camp.sound_id, upload_date="20261101", **kwargs,
    )
    session.add(row)
    session.flush()
    return row


def seed_variants(session, camp):
    for i, account in enumerate(["@Alice", "alice", " @ALICE ", "Alice", "@alice/"]):
        row = post(session, camp, account, views=(i + 1) * 100_000)
        row.url = f"https://example.test/variant/{i}"
    post(session, camp, "@Alice", views=90_000_000, dismissed_at=datetime.now())
    post(session, camp, "@Alice", views=80_000_000, platform="instagram")
    post(session, camp, "  @  ", views=70_000_000)


def test_normalized_leaderboard_and_drilldown_use_the_same_tiktok_posts(db):
    with db.get_session() as session:
        camp = campaign(session, "first")
        seed_variants(session, camp)
        session.commit()
        rows = breaker_leaderboard(session)
        assert len(rows) == 1
        row = rows[0]
        assert row["account"] == "@alice"
        assert row["posts"] == 5
        assert row["total_views"] == 1_500_000
        assert row["median_views"] == 300_000
        assert row["viral_rate"] == 20
        for alias in ["alice", "@ALICE", " @Alice/ "]:
            detail = creator_drilldown(session, alias)
            assert detail["account"] == "@alice"
            assert detail["posts"] == row["posts"]
            assert detail["avg_views"] == row["avg_views"]
            assert detail["median_views"] == row["median_views"]
        assert creator_drilldown(session, " @ ") is None


def test_sound_fit_joins_normalized_exact_and_artist_history(db):
    with db.get_session() as session:
        target = campaign(session, "target")
        other = campaign(session, "other", sound="sound-2")
        other.artist = " Artist "
        seed_variants(session, target)
        post(session, other, " @ALICE ", views=500_000)
        session.commit()
        fit = sound_fit(session, target.sound_id)
        assert len(fit["creators"]) == 1
        row = fit["creators"][0]
        assert row["account"] == "@alice"
        assert row["on_sound_avg"] == 300_000
        assert row["posted_this_artist"] is True
        assert row["fit_score"] == row["breaker_score"] + 15 + 12


def test_drilldown_keeps_same_sound_campaign_timings_separate(db):
    with db.get_session() as session:
        first = campaign(session, "round-1", start_date="2026-10-31")
        second = campaign(session, "round-2", start_date="2026-10-01")
        post(session, first, "@alice")
        post(session, second, "ALICE").upload_date = "20261020"
        session.commit()
        detail = creator_drilldown(session, "alice")
        assert detail["distinct_sounds"] == 1
        assert {row["campaign_slug"]: row["timing"] for row in detail["sounds"]} == {
            "round-1": "early", "round-2": "late",
        }
        assert detail["early_adopter_rate"] == 100


def test_rebooking_combines_booking_aliases_but_not_other_platforms(db):
    now = datetime.now()
    with db.get_session() as session:
        first = campaign(session, "old", created_at=now - timedelta(days=30))
        second = campaign(session, "new", created_at=now)
        seed_variants(session, first)
        session.add_all([
            Creator(campaign_id=first.id, username="@Alice", posts_owed=2, posts_done=1),
            Creator(campaign_id=second.id, username=" ALICE ", posts_owed=3, posts_done=2),
            Creator(campaign_id=second.id, username="@Alice", platform="instagram", posts_owed=99),
        ])
        session.commit()
        result = rebook_suggestions(session)
        assert len(result) == 1
        row = result[0]
        assert row["campaigns_booked"] == 2
        assert row["posts_owed"] == 5
        assert row["posts_done"] == 3
        assert row["repeat_rate"] == .6
        assert row["days_since_booked"] == 0
        # A booking today must not receive the 365-day cold-booking boost.
        assert row["opportunity_score"] == round(row["breaker_score"] * .84, 1)


def test_picker_keeps_both_rounds_and_fit_selects_the_requested_campaign(db, client):
    with db.get_session() as session:
        first = campaign(session, "round-1", created_at=datetime(2026, 1, 1), round="1", start_date="2026-01-01")
        second = campaign(session, "round-2", created_at=datetime(2026, 2, 1), round="2", start_date="2026-02-01")
        first.song = second.song = "Same Song"
        wrong = campaign(session, "different-sound", sound="sound-2")
        session.commit()
        sounds = list_sounds(session)
        assert {row["campaign_slug"] for row in sounds} == {first.slug, second.slug, wrong.slug}
        rounds = {row["campaign_slug"]: (row["song"], row["round"], row["start_date"]) for row in sounds}
        assert rounds["round-1"] == ("Same Song", "1", "2026-01-01")
        assert rounds["round-2"] == ("Same Song", "2", "2026-02-01")
        assert sound_fit(session, "sound-1")["campaign_slug"] == "round-2"
    response = client.get("/api/intelligence/sound-fit/sound-1?campaign_slug=round-1")
    assert response.status_code == 200
    assert response.json["campaign_slug"] == "round-1"
    response = client.get("/api/intelligence/sound-fit/sound-1?campaign_slug=round-2")
    assert response.json["campaign_slug"] == "round-2"
    assert client.get("/api/intelligence/sound-fit/sound-1?campaign_slug=different-sound").status_code == 404
    assert client.get("/api/intelligence/sound-fit/sound-1?campaign_slug=missing").status_code == 404


def test_fit_limit_can_reach_candidates_beyond_default_top_40(db, client):
    with db.get_session() as session:
        camp = campaign(session, "target")
        for creator in range(43):
            for i in range(5):
                session.add(MatchedVideo(
                    campaign_id=camp.id, account=f"@creator{creator}",
                    url=f"https://example.test/{creator}/{i}", views=500_000,
                    extracted_sound_id=camp.sound_id,
                ))
        session.commit()
    assert len(client.get("/api/intelligence/sound-fit/sound-1").json["creators"]) == 40
    response = client.get("/api/intelligence/sound-fit/sound-1?limit=1000")
    assert len(response.json["creators"]) == 43
    assert len(client.get("/api/intelligence/sound-fit/sound-1?limit=-5").json["creators"]) == 1


def test_empty_identity_or_instagram_posts_cannot_qualify_as_tiktok_breakers(db, client):
    with db.get_session() as session:
        camp = campaign(session, "target")
        for i in range(5):
            session.add(MatchedVideo(
                campaign_id=camp.id, account="@ig_only", platform="instagram",
                url=f"https://example.test/ig/{i}", views=1_000_000,
            ))
        session.commit()
    assert client.get("/api/intelligence/breakers").json["breakers"] == []
    assert client.get("/api/intelligence/creator/@ig_only").status_code == 404
    assert client.get("/api/intelligence/rebook-suggestions").json["suggestions"] == []


def test_all_analysis_paths_use_round_qualified_posts_and_per_sound_successors(db):
    with db.get_session() as session:
        first = campaign(session, "round-1", sound="123456789", start_date="2026-10-01")
        first.additional_sounds = ["987654321"]
        second = campaign(session, "round-2", sound="123456789", start_date="2026-11-01", completion_status="completed")
        # Three primary posts correctly owned by round 1.
        for i in range(3):
            row = post(session, first, "@alice", views=100 + i)
            row.upload_date = f"2026100{i + 5}"
        # The same November post is stored on both rounds; only round 2 owns it.
        row = post(session, first, "@ALICE", views=50_000_000)
        row.url = "https://example.test/november"
        row = post(session, second, "alice", views=200)
        row.url = "https://example.test/november"
        # Primary advancing must not close a known secondary sound.
        row = post(session, first, "@alice", views=300)
        row.extracted_sound_id = "987654321"
        # Missing identity cannot cross the earliest overlapping successor.
        row = post(session, first, "@alice", views=60_000_000)
        row.extracted_sound_id = ""
        row = post(session, second, "@alice", views=70_000_000)
        row.upload_date = ""
        session.commit()
        leader = breaker_leaderboard(session)[0]
        assert leader["posts"] == 5
        assert leader["total_views"] == 803
        assert leader["distinct_sounds"] == 2
        detail = creator_drilldown(session, "alice")
        assert detail["posts"] == 5
        assert sum(row["total_views"] for row in detail["sounds"]) == 803
        assert len(detail["sounds"]) == 3  # first primary, first secondary, second primary
        fit = sound_fit(session, "123456789")["creators"][0]
        assert fit["on_sound_avg"] == 126
        sounds = list_sounds(session)
        assert all(row["post_count"] == 4 for row in sounds)
        assert rebook_suggestions(session)[0]["avg_views"] == round(803 / 5)


def test_legacy_duplicate_urls_count_once_but_empty_urls_remain_separate(db):
    with db.get_session() as session:
        first = campaign(session, "legacy-old", created_at=datetime(2026, 1, 1))
        second = campaign(session, "legacy-new", created_at=datetime(2026, 2, 1))
        row = post(session, first, "@ALICE", views=9_000_000)
        row.url = "https://example.test/duplicate"
        row = post(session, second, "alice", views=500_000)
        row.url = "https://example.test/duplicate"
        post(session, first, "@alice", views=100).url = ""
        post(session, second, "Alice", views=200).url = ""
        session.commit()
        leader = breaker_leaderboard(session, min_posts=1)[0]
        assert leader["posts"] == 3
        assert leader["total_views"] == 500_300
        detail = creator_drilldown(session, "alice")
        assert detail["posts"] == 3
        assert sum(row["total_views"] for row in detail["sounds"]) == 500_300


def test_analysis_query_count_does_not_grow_per_creator(db, engine):
    with db.get_session() as session:
        camp = campaign(session, "target")
        for i in range(6):
            post(session, camp, f"@creator{i}")
        session.commit()
        queries = []
        def record(_conn, _cursor, statement, _parameters, _context, _executemany):
            queries.append(statement)
        event.listen(engine, "before_cursor_execute", record)
        try:
            assert len(breaker_leaderboard(session, min_posts=1)) == 6
            assert len(queries) == 2
            queries.clear()
            assert sound_fit(session, "sound-1") is not None
            assert len(queries) == 2
            queries.clear()
            assert len(list_sounds(session)) == 1
            assert len(queries) == 2
        finally:
            event.remove(engine, "before_cursor_execute", record)


def test_unknown_sound_does_not_invent_diversity_or_early_adoption(db):
    with db.get_session() as session:
        camp = campaign(session, "unknown-sound", sound="", start_date="2026-11-01")
        for i in range(5):
            session.add(MatchedVideo(
                campaign_id=camp.id, account="@alice", url=f"https://example.test/unknown/{i}",
                views=100, upload_date="20261101",
            ))
        session.commit()
        leader = breaker_leaderboard(session)[0]
        assert leader["distinct_sounds"] == 0
        detail = creator_drilldown(session, "alice")
        assert detail["distinct_sounds"] == 0
        assert detail["early_adopter_rate"] == 0
        assert detail["score_balanced"] == leader["score_balanced"]
