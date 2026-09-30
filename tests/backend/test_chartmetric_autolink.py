from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from campaign_manager import db
from campaign_manager.models import Campaign
from campaign_manager.services import chartmetric as cm
from campaign_manager.services import chartmetric_autolink as al


def _resp(body):
    r = MagicMock(status_code=200)
    r.json.return_value = body
    r.text = "ok"
    return r


def _search_client(artist_rows, pages):
    http = MagicMock()
    http.post.return_value = _resp({"token": "access", "expires_in": 3600})
    def get(url, params=None, **_kwargs):
        if url.endswith("/search"):
            return _resp({"obj": {"artists": artist_rows}})
        artist_id = int(url.rstrip("/").split("/")[-2])
        return _resp({"obj": pages.get((artist_id, params["offset"]), [])})
    http.get.side_effect = get
    return cm.ChartmetricClient("secret-refresh", session=http), http


def _row(i, name="Espresso", artist="Sabrina Carpenter", streams=None, popularity=None):
    return {"id": i, "name": name, "artist_names": [artist],
            "cm_statistics": {"sp_streams": streams, "sp_popularity": popularity}}


def test_search_track_pages_exact_name_artist_profiles_and_picks_most_streams():
    artists = [{"id": 4550, "name": "Sabrina Carpenter"},
               {"id": 15991411, "name": "Sabrina Carpenter"},
               {"id": 7, "name": "Sabrina Carpenterrs"}]
    filler = [_row(1000 + i, name=f"Other {i}") for i in range(100)]
    pages = {(4550, 0): filler, (4550, 100): [_row(118981138, streams=900)],
             (15991411, 0): [_row(118981139, streams=1000)]}
    client, http = _search_client(artists, pages)
    assert client.search_track("Espresso", "Sabrina Carpenter") == 118981139
    requested = [call.kwargs["params"] for call in http.get.call_args_list]
    assert requested[0] == {"q": "Sabrina Carpenter", "type": "artists", "limit": 10}
    assert {p["offset"] for p in requested[1:]} == {0, 100}


def test_search_track_rejects_wrong_artist_and_no_exact_artist():
    artists = [{"id": 1, "name": "Sabrina Carpenter"}]
    client, _ = _search_client(artists, {(1, 0): [_row(1, artist="Someone Else")]})
    assert client.search_track("Espresso", "Sabrina Carpenter") is None
    client, http = _search_client([{"id": 7, "name": "Sabrina Carpenterrs"}], {})
    assert client.search_track("Espresso", "Sabrina Carpenter") is None
    assert http.get.call_count == 1


def test_search_track_uses_popularity_then_lowest_id_as_fallbacks():
    artists = [{"id": 1, "name": "Sabrina Carpenter"}]
    pages = {(1, 0): [_row(3, streams=None, popularity=80),
                      _row(2, streams=None, popularity=80),
                      _row(1, streams=None, popularity=70)]}
    client, _ = _search_client(artists, pages)
    assert client.search_track("Espresso", "Sabrina Carpenter") == 2
    assert client.search_track("", "Sabrina Carpenter") is None
    assert client.search_track("   ", "Sabrina Carpenter") is None
    assert client.search_track("Original Sound", "Sabrina Carpenter") is None


def test_autolink_normalizer_collaborators_suffixes_and_version_requirement():
    normalize = cm.ChartmetricClient.normalize_autolink_title
    assert normalize("Beyoncé's Song!", True) == "beyonce s song"
    assert normalize("Straße", True) == "strasse"
    assert normalize("Song & Dance", True) == "song and dance"
    assert normalize("Track (feat. Alex)" , True) == "track"
    assert normalize("Track - Radio Edit", True) == "track"
    assert normalize("Track (Remix)") == "track remix"
    assert cm.ChartmetricClient.split_artist_names("X & Y feat. Z, W and Q") == ["X", "Y", "Z", "W", "Q"]


def test_round_title_cleanup_exact_production_titles_and_real_digits():
    clean = cm.ChartmetricClient._clean_campaign_title
    for raw in ("Changes (Round 2)", "What You Got (Round 2)", "Ahi (Round 2)",
                "Unethical (Round 2)", "Back To Funk (Round 3)", "New Religion R3",
                "Evergreen Rd 3"):
        assert clean(raw)[0] in {"Changes", "What You Got", "Ahi", "Unethical", "Back To Funk", "New Religion", "Evergreen"}
    assert clean("Song Round 21")[0] == "Song Round 21"
    assert clean("Song 3")[0] == "Song 3"
    assert clean("Changes", "Round 2")[0] == "Changes"
    for raw in ("Song Round 4", "Song - Round 5", "Song (R 6)", "Song (R7)",
                "Song R8", "Song R 9", "Song Rd 10", "Song (Rd 11)"):
        assert clean(raw)[0] == "Song"
    norm = cm.ChartmetricClient.normalize_autolink_title
    assert norm("PØPA æß café") == "popa aess cafe"


def test_exact_round_marked_campaign_songs_match_unmarked_catalogue_titles():
    examples = (("Changes (Round 2)", "Changes"),
                ("What You Got (Round 2)", "What You Got"),
                ("Ahi (Round 2)", "Ahi"),
                ("Unethical (Round 2)", "Unethical"),
                ("Back To Funk (Round 3)", "Back To Funk"),
                ("New Religion R3", "New Religion"),
                ("Evergreen Rd 3", "Evergreen"))
    for campaign_title, catalogue_title in examples:
        client, _ = _resolver_client([{"id": 1, "name": "Artist"}], {
            (1, 0): [_row(100, name=catalogue_title, artist="Artist")],
        })
        result = client.resolve_campaign({"song": campaign_title, "artist": "Artist"})
        assert result["status"] == "linked_auto", campaign_title
    client, _ = _resolver_client([{"id": 1, "name": "Artist"}], {
        (1, 0): [_row(101, name="Changes (Round 2)", artist="Artist")],
    })
    assert client.resolve_campaign({"song": "Changes", "artist": "Artist"})["track_id"] == 101


def test_bare_campaign_title_may_match_one_non_version_subtitle():
    artists = [{"id": 1, "name": "Omar Apollo"}]
    track = _row(204, "Evergreen (You Didn't Deserve Me At All)", "Omar Apollo")
    for title in ("Evergreen (Round 2)", "Evergreen Rd 3"):
        client, _ = _resolver_client(artists, {(1, 0): [track]})
        result = client.resolve_campaign({"song": title, "artist": "Omar Apollo"})
        assert result["status"] == "linked_auto" and result["track_id"] == 204

    client, _ = _resolver_client(artists, {(1, 0): [_row(205, "Evergreen (Remix)", "Omar Apollo")]})
    result = client.resolve_campaign({"song": "Evergreen (Round 2)", "artist": "Omar Apollo"})
    assert result["status"] != "linked_auto"

    client, _ = _resolver_client(artists, {(1, 0): [
        _row(206, "Evergreen (You Didn't Deserve Me At All)", "Omar Apollo"),
        _row(207, "Evergreen (Another Subtitle)", "Omar Apollo"),
    ]})
    result = client.resolve_campaign({"song": "Evergreen Rd 3", "artist": "Omar Apollo"})
    assert result["status"] == "ambiguous"


def test_artist_miss_is_never_not_released_and_multi_song_is_ambiguous():
    client, _ = _resolver_client([], {})
    miss = client.resolve_campaign({"song": "Track", "artist": "Unknown", "start_date": "2999-01-01"})
    assert miss == {"status": "artist_not_found", "detail": "Artist was not found in Chartmetric."}
    multi = client.resolve_campaign({"song": "Singularity / Ballon", "artist": "ROMANS"})
    assert multi == {"status": "ambiguous", "detail": "campaign lists more than one song"}


def test_feat_fallback_requires_credited_campaign_artist_and_version_is_strict():
    client, _ = _resolver_client([{"id": 1, "name": "Limage"}], {
        (1, 0): [_row(44, name="Unforgettable", artist="Limage")],
    })
    result = client.resolve_campaign({"song": "Unforgettable (feat. Malikaa)", "artist": "Limage"})
    assert result["status"] == "linked_auto" and result["track_id"] == 44
    for title in ("Unforgettable (Remix)", "Unforgettable (String Section)", "Unforgettable (September)"):
        result = client.resolve_campaign({"song": title, "artist": "Limage"})
        assert result == {"status": "ambiguous", "detail": "version not found in Chartmetric catalogue"}


def test_each_explicit_version_suffix_is_kept_strict():
    client, _ = _resolver_client([{"id": 1, "name": "Artist"}], {(1, 0): [_row(1, name="Song", artist="Artist")]})
    for suffix in ("remix", "mix", "edit", "version", "sped up", "slowed", "acoustic", "live",
                   "instrumental", "extended", "radio edit", "club mix"):
        result = client.resolve_campaign({"song": f"Song ({suffix})", "artist": "Artist"})
        assert result == {"status": "ambiguous", "detail": "version not found in Chartmetric catalogue"}, suffix


def _resolver_client(artists, tracks_by_artist, sound_ids=None):
    http = MagicMock()
    http.post.return_value = _resp({"token": "access", "expires_in": 3600})
    def get(url, params=None, **_kwargs):
        if url.endswith("/get-ids"):
            return _resp({"obj": sound_ids or []})
        if url.endswith("/search"):
            return _resp({"obj": {"artists": artists}})
        artist_id = int(url.rstrip("/").split("/")[-2])
        offset = params["offset"]
        return _resp({"obj": tracks_by_artist.get((artist_id, offset), [])})
    http.get.side_effect = get
    return cm.ChartmetricClient("secret-refresh", session=http), http


def test_resolver_sound_id_exact_hit_precedes_metadata():
    client, http = _resolver_client([], {}, [{"chartmetric_ids": [77]}])
    result = client.resolve_campaign({"song": "Wrong", "artist": "Wrong", "sound_id": "123"})
    assert result == {"track_id": 77, "method": "tiktok_sound", "status": "linked_auto", "detail": "Matched TikTok sound ID."}
    assert len(http.get.call_args_list) == 1
    client, _ = _resolver_client([], {}, [{"chartmetric_ids": [77, 78]}])
    assert client.resolve_campaign({"song": "", "artist": "", "sound_id": "123"})["status"] == "ambiguous"


def test_resolver_all_artists_and_title_labels_collapses_versions_by_streams():
    artists = [{"id": 1, "name": "Artist One"}, {"id": 2, "name": "Artist Two"}]
    tracks = {
        (1, 0): [{**_row(30, name="MiXed Song (Remix)", artist="Artist One", streams=900), "artist_names": ["Artist One", "Artist Two"]},
                 {**_row(20, name="Mixed Song", artist="Artist One", streams=100), "artist_names": ["Artist One", "Artist Two"]}],
        (2, 0): [{**_row(10, name="Mixed Song - Radio Edit", artist="Artist Two", streams=800), "artist_names": ["Artist One", "Artist Two"]}],
    }
    client, _ = _resolver_client(artists, tracks)
    result = client.resolve_campaign({"song": "mixed song!", "artist": "Artist One & Artist Two", "tt_track_name": ""})
    assert result["status"] == "linked_auto" and result["track_id"] == 20
    result = client.resolve_campaign({"song": "Mixed Song", "artist": "Unknown", "tt_artist_label": "Artist Two"})
    assert result["status"] == "not_released"


def test_resolver_ambiguous_generic_missing_and_pre_release_states():
    client, _ = _resolver_client([], {})
    assert client.resolve_campaign({"song": ""})["status"] == "no_song_info"
    assert client.resolve_campaign({"song": "Original Sound", "artist": "A"})["status"] == "generic_title"
    assert client.resolve_campaign({"song": "Song", "artist": "Missing", "start_date": "2020-01-01"})["status"] == "artist_not_found"
    assert client.resolve_campaign({"song": "Song", "artist": "Missing", "start_date": "2026-09-30"})["status"] == "artist_not_found"
    client, _ = _resolver_client([{"id": 1, "name": "Artist One"}, {"id": 2, "name": "Artist Two"}], {
        (1, 0): [_row(31, "Song", "Artist One")], (2, 0): [_row(32, "Song", "Artist Two")],
    })
    assert client.resolve_campaign({"song": "Song", "artist": "Artist One & Artist Two", "start_date": "2020-01-01"})["status"] == "ambiguous"


def test_resolver_retries_feat_clause_but_requires_explicit_campaign_version():
    client, _ = _resolver_client([{"id": 1, "name": "Limage"}], {
        (1, 0): [_row(44, name="Unforgettable", artist="Limage")],
    })
    result = client.resolve_campaign({"song": "Unforgettable (feat. Malikaa)", "artist": "Limage", "start_date": "2020-01-01"})
    assert result["status"] == "linked_auto"


def test_resolver_requires_a_credited_campaign_artist():
    client, _ = _resolver_client([{"id": 1, "name": "Artist One"}], {
        (1, 0): [_row(55, name="Song", artist="Someone Else")],
    })
    result = client.resolve_campaign({"song": "Song", "artist": "Artist One", "start_date": "2020-01-01"})
    assert result["status"] == "not_released"


def test_resolver_paginates_artist_tracks_until_short_page():
    filler = [_row(1000 + i, name=f"Other {i}") for i in range(100)]
    client, http = _resolver_client([{"id": 1, "name": "Artist"}], {
        (1, 0): filler, (1, 100): [_row(9001, name="Wanted", artist="Artist", streams=25)],
    })
    result = client.resolve_campaign({"song": "Wanted", "artist": "Artist"})
    assert result["track_id"] == 9001
    assert [call.kwargs["params"]["offset"] for call in http.get.call_args_list if "/tracks" in call.args[0]] == [0, 100]


def test_autolink_checked_at_and_field_only_update(app, monkeypatch):
    with db.get_session() as s:
        s.add(Campaign(slug="espresso", title="Espresso", artist="Sabrina Carpenter",
                       song="Espresso", start_date="2026-09-01", end_date="2026-09-30"))
        s.commit()
    monkeypatch.setenv("CHARTMETRIC_REFRESH_TOKEN", "secret-refresh")
    with patch.object(al, "get_client") as get_client:
        get_client.return_value.resolve_campaign.return_value = {"status": "no_song_info", "detail": "Song title is missing."}
        result = al.autolink_campaigns()
    assert result["checked"] == 1
    with db.get_session() as s:
        c = s.query(Campaign).filter_by(slug="espresso").one()
        assert c.chartmetric_autolink_checked_at is not None
        assert c.end_date == "2026-09-30"


def test_autolink_sets_link_and_preserves_existing_link(app, monkeypatch):
    with db.get_session() as s:
        s.add(Campaign(slug="espresso", title="Espresso", artist="Sabrina Carpenter", song="Espresso"))
        s.add(Campaign(slug="manual", title="Manual", artist="Sabrina Carpenter", song="Espresso",
                       chartmetric_link="manual-link", chartmetric_track_id=9))
        s.commit()
    monkeypatch.setenv("CHARTMETRIC_REFRESH_TOKEN", "secret-refresh")
    with patch.object(al, "get_client") as get_client:
        get_client.return_value.resolve_campaign.return_value = {"track_id": 118981138, "method": "artist_tracks", "status": "linked_auto", "detail": "exact"}
        with patch.object(db, "update_campaign_fields", wraps=db.update_campaign_fields) as update:
            result = al.autolink_campaigns()
    assert result["linked"] == 1
    assert update.call_count == 1
    assert set(update.call_args.args[1]) <= {
        "chartmetric_track_id", "chartmetric_link", "chartmetric_autolink_checked_at",
        "chartmetric_link_status", "chartmetric_link_detail"}
    with db.get_session() as s:
        c = s.query(Campaign).filter_by(slug="espresso").one()
        assert c.chartmetric_track_id == 118981138
        assert c.chartmetric_link == "https://app.chartmetric.com/track?id=118981138"
        assert c.chartmetric_link_status == "linked_auto"
        assert c.chartmetric_link_detail.startswith("artist_tracks:")


def test_autolink_respects_cadence_and_interval(monkeypatch):
    assert al.get_autolink_interval_minutes() == 120
    assert al.retry_days("not_released") == 1
    assert al.retry_days("ambiguous") == 3
    assert al.retry_days("artist_not_found") == 3
    assert al.retry_days("generic_title") == 7
    monkeypatch.setenv("CHARTMETRIC_AUTOLINK_INTERVAL_MINUTES", "1")
    assert al.get_autolink_interval_minutes() == 30
    monkeypatch.setenv("CHARTMETRIC_AUTOLINK_INTERVAL_MINUTES", "9999")
    assert al.get_autolink_interval_minutes() == 1440


def test_autolink_skips_recently_checked_campaign(app, monkeypatch):
    with db.get_session() as s:
        s.add(Campaign(slug="recent", title="Recent", artist="Artist", song="Song",
                       chartmetric_link_status="no_song_info",
                       chartmetric_autolink_checked_at=datetime.now() - timedelta(days=6)))
        s.commit()
    monkeypatch.setenv("CHARTMETRIC_REFRESH_TOKEN", "secret-refresh")
    with patch.object(al, "get_client") as get_client:
        get_client.return_value.resolve_campaign.return_value = {"status": "no_song_info", "detail": "missing"}
        result = al.autolink_campaigns()
    assert result == {"linked": 0, "checked": 0}
    get_client.return_value.resolve_campaign.assert_not_called()


def test_legacy_timestamp_without_status_is_due(app, monkeypatch):
    with db.get_session() as s:
        s.add(Campaign(slug="legacy", title="Legacy", song="Song", artist="Artist",
                       chartmetric_link_status=None,
                       chartmetric_autolink_checked_at=datetime.now() - timedelta(hours=1)))
        s.commit()
    monkeypatch.setenv("CHARTMETRIC_REFRESH_TOKEN", "secret-refresh")
    with patch.object(al, "get_client") as get_client:
        get_client.return_value.resolve_campaign.return_value = {"status": "ambiguous", "detail": "checked"}
        result = al.autolink_campaigns()
    assert result["checked"] == 1
    get_client.return_value.resolve_campaign.assert_called_once()


def test_status_specific_retry_windows_and_never_retry_linked_or_manual(app, monkeypatch):
    utcnow = datetime.now(timezone.utc).replace(tzinfo=None)
    old = utcnow - timedelta(days=4)
    with db.get_session() as s:
        s.add(Campaign(slug="daily", title="Daily", song="Song", artist="Artist",
                       chartmetric_link_status="not_released", chartmetric_autolink_checked_at=utcnow - timedelta(hours=23)))
        s.add(Campaign(slug="ambig", title="Ambig", song="Song", artist="Artist",
                       chartmetric_link_status="ambiguous", chartmetric_autolink_checked_at=old))
        s.add(Campaign(slug="manual", title="Manual", song="Song", artist="Artist", chartmetric_track_id=88,
                       chartmetric_link_status="manual", chartmetric_autolink_checked_at=old))
        s.commit()
    monkeypatch.setenv("CHARTMETRIC_REFRESH_TOKEN", "safe-test-token")
    with patch.object(al, "get_client") as get_client:
        get_client.return_value.resolve_campaign.return_value = {"status": "ambiguous", "detail": "ambiguous"}
        result = al.autolink_campaigns()
    assert result["checked"] == 1
    assert [args.args[0]["slug"] for args in get_client.return_value.resolve_campaign.call_args_list] == ["ambig"]


def test_create_and_song_metadata_edit_request_immediate_resolution(client):
    from unittest.mock import patch
    with patch.object(al, "request_immediate_resolve") as request_resolve:
        response = client.post("/api/campaign/create", json={"title": "Artist - New Song"})
        assert response.status_code == 201
        request_resolve.assert_called_once_with("artist_new_song")
    with patch.object(al, "request_immediate_resolve") as request_resolve:
        response = client.post("/api/campaign/artist_new_song/edit", json={
            "song": "Changed Song", "tt_artist_label": "TikTok Artist"})
        assert response.status_code == 200
        request_resolve.assert_called_once_with("artist_new_song")
    with patch.object(al, "request_immediate_resolve") as request_resolve:
        client.post("/api/campaign/artist_new_song/edit", json={"budget": 99})
        request_resolve.assert_not_called()


def test_scheduler_registers_autolink_only_with_token(monkeypatch):
    from campaign_manager.services import scheduler

    class FakeScheduler:
        def __init__(self, **_kwargs):
            self.jobs = []
        def add_job(self, fn, trigger, **kwargs):
            self.jobs.append((fn, trigger, kwargs))
        def start(self):
            pass

    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(scheduler, "SQLAlchemyJobStore", lambda **_kw: object())
    monkeypatch.setenv("CHARTMETRIC_REFRESH_TOKEN", "secret-refresh")
    scheduler.init_scheduler("sqlite://")
    jobs = scheduler._scheduler.jobs
    auto = [job for job in jobs if job[2].get("id") == "chartmetric_autolink"]
    assert len(auto) == 1 and auto[0][1] == "interval"
    assert auto[0][2]["minutes"] == 120
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.delenv("CHARTMETRIC_REFRESH_TOKEN")
    scheduler.init_scheduler("sqlite://")
    assert not [job for job in scheduler._scheduler.jobs if job[2].get("id") == "chartmetric_autolink"]
    monkeypatch.setattr(scheduler, "_scheduler", None)


def test_token_not_logged_on_api_failure(app, monkeypatch, caplog):
    with db.get_session() as s:
        s.add(Campaign(slug="espresso", title="Espresso", artist="Sabrina Carpenter", song="Espresso"))
        s.commit()
    monkeypatch.setenv("CHARTMETRIC_REFRESH_TOKEN", "top-secret-token")
    with patch.object(al, "get_client", side_effect=cm.ChartmetricError("login failed")):
        al.autolink_campaigns()
    assert "top-secret-token" not in caplog.text
