from datetime import datetime, timedelta
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


def test_autolink_checked_at_and_field_only_update(app, monkeypatch):
    with db.get_session() as s:
        s.add(Campaign(slug="espresso", title="Espresso", artist="Sabrina Carpenter",
                       song="Espresso", start_date="2026-09-01", end_date="2026-09-30"))
        s.commit()
    monkeypatch.setenv("CHARTMETRIC_REFRESH_TOKEN", "secret-refresh")
    with patch.object(al, "get_client") as get_client:
        get_client.return_value.search_track.return_value = None
        result = al.autolink_campaigns()
    assert result["none"] == 1
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
        get_client.return_value.search_track.return_value = 118981138
        with patch.object(db, "update_campaign_fields", wraps=db.update_campaign_fields) as update:
            result = al.autolink_campaigns()
    assert result["linked"] == 1
    assert update.call_count == 1
    assert set(update.call_args.args[1]) <= {
        "chartmetric_track_id", "chartmetric_link", "chartmetric_autolink_checked_at"}
    with db.get_session() as s:
        c = s.query(Campaign).filter_by(slug="espresso").one()
        assert c.chartmetric_track_id == 118981138
        assert c.chartmetric_link == "https://app.chartmetric.com/track?id=118981138"


def test_autolink_respects_seven_day_checked_window_and_interval(monkeypatch):
    assert al.get_autolink_interval_minutes() == 360
    monkeypatch.setenv("CHARTMETRIC_AUTOLINK_INTERVAL_MINUTES", "1")
    assert al.get_autolink_interval_minutes() == 30
    monkeypatch.setenv("CHARTMETRIC_AUTOLINK_INTERVAL_MINUTES", "9999")
    assert al.get_autolink_interval_minutes() == 1440


def test_autolink_skips_recently_checked_campaign(app, monkeypatch):
    with db.get_session() as s:
        s.add(Campaign(slug="recent", title="Recent", artist="Artist", song="Song",
                       chartmetric_autolink_checked_at=datetime.now() - timedelta(days=6)))
        s.commit()
    monkeypatch.setenv("CHARTMETRIC_REFRESH_TOKEN", "secret-refresh")
    with patch.object(al, "get_client") as get_client:
        get_client.return_value.search_track.return_value = None
        result = al.autolink_campaigns()
    assert result == {"linked": 0, "none": 0}
    get_client.return_value.search_track.assert_not_called()


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
    assert auto[0][2]["minutes"] == 360
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
