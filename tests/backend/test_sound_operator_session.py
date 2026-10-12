"""Synthetic browser operator access; no production credentials or upstream calls."""
import pytest
import requests


@pytest.fixture(autouse=True)
def credentials(app, monkeypatch):
    monkeypatch.setenv("HUB_WRITE_KEY", "synthetic-hub-key")
    monkeypatch.setenv("SOUND_ASSIGNMENTS_OPERATOR_PASSWORD", "synthetic-operator-password-0123456789")
    app.config["CONTENT_LAB_HUB_API_KEY"] = "synthetic-lab-key"


def _login(client):
    response = client.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"}, headers={"Origin": "http://localhost"})
    assert response.status_code == 200
    return response.json["csrf_token"]


def test_browser_session_reads_and_writes_with_csrf(app, client, monkeypatch):
    app.config["CONTENT_LAB_HUB_API_KEY"] = "synthetic-lab-key"
    calls = []

    def upstream(method, url, **options):
        calls.append((method, url, options))
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response._content = b'{"ok":true}'
        return response

    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.requests.request", upstream)
    assert client.get("/api/sound-assignments/pages").status_code == 401
    assert client.post("/api/sound-assignments/login", json={"password": "wrong"}, headers={"Origin": "http://localhost"}).status_code == 401
    csrf = _login(client)
    assert client.get("/api/sound-assignments/session").json == {"authenticated": True, "csrf_token": csrf}
    assert client.get("/api/sound-assignments/pages").json == {"ok": True}
    assert client.post("/api/sound-assignments/sync").status_code == 403
    assert client.post("/api/sound-assignments/sync", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/sound-assignments/sync", headers={"X-CSRF-Token": csrf,
        "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/sound-assignments/sync", headers={"X-CSRF-Token": csrf, "Origin": "http://localhost"}).json == {"ok": True}
    assert len(calls) == 2
    assert all(call[2].get("headers") == {"X-API-Key": "synthetic-lab-key"} for call in calls)
    assert client.post("/api/sound-assignments/logout", headers={"X-CSRF-Token": csrf, "Origin": "http://localhost"}).status_code == 200
    assert client.get("/api/sound-assignments/pages").status_code == 401


def test_login_rejects_cross_origin_and_missing_configuration(app, client, monkeypatch):
    assert client.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"},
        headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"},
        headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"}).status_code == 403
    monkeypatch.delenv("SOUND_ASSIGNMENTS_OPERATOR_PASSWORD")
    assert client.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"}, headers={"Origin": "http://localhost"}).status_code == 503
    assert client.get("/api/sound-assignments/pages").status_code == 503
    assert client.get("/health").status_code in (200, 503)


def test_cookie_flags_and_unauthenticated_routes(app, client):
    response = client.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"}, headers={"Origin": "http://localhost"})
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert "synthetic-hub-key" not in cookie
    assert "synthetic-operator-password-0123456789" not in cookie
    assert client.get("/api/sound-assignments/session").status_code == 200


def test_attempt_limit_is_shared_across_clients_and_recovers(app, monkeypatch):
    first = app.test_client()
    second = app.test_client()
    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.time.time", lambda: 1000)
    for attempt in range(9):
        client = first if attempt % 2 else second
        assert client.post("/api/sound-assignments/login", json={"password": "wrong"},
            headers={"Origin": "http://localhost"}).status_code == 401
    assert second.post("/api/sound-assignments/login", json={"password": "wrong"},
        headers={"Origin": "http://localhost"}).status_code == 429
    assert first.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"},
        headers={"Origin": "http://localhost"}).status_code == 429
    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.time.time", lambda: 1301)
    assert first.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"},
        headers={"Origin": "http://localhost"}).status_code == 200


def test_authenticated_cookie_without_csrf_cannot_mutate(app, client, monkeypatch):
    with client.session_transaction() as state:
        state["sound_operator"] = True
    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.requests.request",
        lambda *args, **kwargs: pytest.fail("missing CSRF reached Content Lab"))
    assert client.post("/api/sound-assignments/sync", headers={"Origin": "http://localhost"}).status_code == 401
    assert client.post("/api/sound-assignments/sync", headers={"Origin": "http://localhost",
        "X-CSRF-Token": ""}).status_code == 401


def test_production_cookie_is_secure_without_railway_flag():
    from campaign_manager import create_app
    app = create_app({"DATABASE_URL": "", "SCHEDULER_ENABLED": False, "TESTING": False, "DEBUG": False,
        "IS_RAILWAY": False})
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_first_run_schema_exists_and_missing_limiter_fails_closed(app, client, db, monkeypatch):
    from sqlalchemy import inspect, text
    assert "sound_operator_login_state" in inspect(db._engine).get_table_names()
    assert _login(client)
    with db._engine.begin() as connection:
        connection.execute(text("DROP TABLE sound_operator_login_state"))
    response = client.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"},
        headers={"Origin": "http://localhost"})
    assert response.status_code == 503
    assert "synthetic-operator-password-0123456789" not in response.get_data(as_text=True)


def test_short_or_reused_operator_password_fails_closed(client, monkeypatch):
    monkeypatch.setenv("SOUND_ASSIGNMENTS_OPERATOR_PASSWORD", "short")
    assert client.post("/api/sound-assignments/login", json={"password": "short"},
        headers={"Origin": "http://localhost"}).status_code == 503
    monkeypatch.setenv("SOUND_ASSIGNMENTS_OPERATOR_PASSWORD", "synthetic-hub-key")
    assert client.get("/api/sound-assignments/pages").status_code == 503


def test_missing_lab_key_refuses_browser_login(app, client):
    app.config["CONTENT_LAB_HUB_API_KEY"] = ""
    assert client.post("/api/sound-assignments/login", json={"password": "synthetic-operator-password-0123456789"},
        headers={"Origin": "http://localhost"}).status_code == 503


def test_existing_service_key_contract_does_not_require_browser_password(app, client, monkeypatch):
    monkeypatch.delenv("SOUND_ASSIGNMENTS_OPERATOR_PASSWORD")
    app.config["CONTENT_LAB_HUB_API_KEY"] = ""
    calls = []
    def upstream(method, url, **options):
        calls.append((method, url, options))
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response._content = b'[]'
        return response
    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.requests.request", upstream)
    response = client.get("/api/sound-assignments/pages", headers={"X-Hub-Write-Key": "synthetic-hub-key"})
    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][2] == {"json": None, "timeout": 30}
    assert client.get("/api/sound-assignments/pages").status_code == 503
