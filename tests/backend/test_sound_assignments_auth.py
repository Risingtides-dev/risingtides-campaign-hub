"""Server-only Content Lab authentication; all upstream calls are test-owned."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
import requests


KEY = "synthetic-content-lab-service-key"
HUB_KEY = "synthetic-hub-write-key"


@pytest.fixture(autouse=True)
def hub_key(monkeypatch):
    monkeypatch.setenv("HUB_WRITE_KEY", HUB_KEY)
    monkeypatch.setenv("SOUND_ASSIGNMENTS_OPERATOR_PASSWORD", "synthetic-operator-password-0123456789")



@pytest.mark.parametrize(
    "method,path,upstream,body,timeout",
    [
        ("GET", "/posters", "/api/telegram/posters", None, 30),
        ("GET", "/pages", "/api/roster/", None, 30),
        ("GET", "/sounds?active_only=false", "/api/telegram/sounds?active_only=false", None, 30),
        ("GET", "/playlists", "/api/telegram/playlists", None, 30),
        ("GET", "/pages/page-1/playlist", "/api/telegram/pages/page-1/playlist", None, 30),
        ("GET", "/posters/poster-1/preview", "/api/telegram/posters/poster-1/preview", None, 30),
        ("GET", "/status", "/api/telegram/status", None, 30),
        ("PUT", "/pages/page-1/playlist", "/api/telegram/pages/page-1/playlist", {"sound_ids": ["sound-1"]}, 30),
        ("POST", "/pages/page-1/playlist/songs", "/api/telegram/pages/page-1/playlist/songs", {"sound_id": "sound-1"}, 30),
        ("DELETE", "/pages/page-1/playlist/songs/sound-1", "/api/telegram/pages/page-1/playlist/songs/sound-1", None, 30),
        ("DELETE", "/pages/page-1/playlist", "/api/telegram/pages/page-1/playlist", None, 30),
        ("POST", "/sync", "/api/telegram/sounds/sync", None, 60),
        ("POST", "/send/poster-1", "/api/telegram/sound-assignments/send/poster-1", None, 60),
        ("POST", "/send-all", "/api/telegram/sound-assignments/send-all", None, 120),
    ],
)
def test_server_key_covers_existing_read_and_write_routes(
    app, client, monkeypatch, method, path, upstream, body, timeout
):
    app.config.update(CONTENT_LAB_URL="https://content-lab.invalid", CONTENT_LAB_HUB_API_KEY=KEY)
    calls = []

    def upstream_request(received_method, url, **options):
        calls.append((received_method, url, options))
        response = requests.Response()
        response.status_code = 201
        response.headers["Content-Type"] = "application/json"
        response._content = b'{"unchanged":true}'
        return response

    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.requests.request", upstream_request)
    response = client.open(
        "/api/sound-assignments" + path,
        method=method,
        json=body,
        headers={"X-API-Key": "browser-forgery", "Authorization": "browser-token", "X-Hub-Write-Key": HUB_KEY},
    )
    assert response.status_code == 201
    assert response.json == {"unchanged": True}
    assert KEY not in response.get_data(as_text=True)
    assert KEY not in str(response.headers)
    assert calls == [(method, "https://content-lab.invalid" + upstream, {
        "json": body, "timeout": timeout, "headers": {"X-API-Key": KEY}, "allow_redirects": False,
    })]


def test_absent_key_preserves_legacy_options_and_ignores_browser_forgery(app, client, monkeypatch):
    app.config.update(CONTENT_LAB_URL="https://content-lab.invalid", CONTENT_LAB_HUB_API_KEY="")
    calls = []

    def upstream_request(method, url, **options):
        calls.append(options)
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response._content = b'[]'
        return response

    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.requests.request", upstream_request)
    assert client.get("/api/sound-assignments/pages", headers={"X-API-Key": "browser-forgery", "X-Hub-Write-Key": HUB_KEY}).json == []
    assert calls == [{"json": None, "timeout": 30}]


def test_configured_key_is_not_reflected_from_transport_error(app, client, monkeypatch, caplog):
    app.config["CONTENT_LAB_HUB_API_KEY"] = KEY

    def fail(*args, **kwargs):
        raise requests.exceptions.InvalidHeader("invalid header value: " + KEY)

    monkeypatch.setattr("campaign_manager.blueprints.sound_assignments.requests.request", fail)
    response = client.get("/api/sound-assignments/posters", headers={"X-Hub-Write-Key": HUB_KEY})
    assert response.status_code == 502
    assert response.json == {"error": "lab_unreachable", "detail": "Content Lab request failed"}
    assert KEY not in response.get_data(as_text=True)
    assert KEY not in caplog.text


@pytest.mark.parametrize("api_key,expected_requests", [(KEY, 1), ("", 2)])
def test_redirect_cannot_forward_configured_key_to_another_origin(
    app, client, api_key, expected_requests
):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.server.server_port, self.path, self.headers.get("X-API-Key")))
            payload = json.dumps({"redirect": self.path != "/target"}).encode()
            self.send_response(307 if self.path != "/target" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            if self.path != "/target":
                self.send_header("Location", f"http://127.0.0.1:{target.server_port}/target")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    target = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threads = [Thread(target=server.serve_forever, daemon=True) for server in (source, target)]
    for thread in threads:
        thread.start()
    try:
        app.config.update(
            CONTENT_LAB_URL=f"http://127.0.0.1:{source.server_port}",
            CONTENT_LAB_HUB_API_KEY=api_key,
        )
        response = client.get("/api/sound-assignments/posters", headers={"X-Hub-Write-Key": HUB_KEY})
        assert response.status_code == (307 if api_key else 200)
        assert len(calls) == expected_requests
        assert calls[0] == (source.server_port, "/api/telegram/posters", api_key or None)
        if api_key:
            assert not any(port == target.server_port for port, _, _ in calls)
        else:
            assert calls[1] == (target.server_port, "/target", None)
    finally:
        for server in (source, target):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


@pytest.mark.parametrize("method,path", [
    ("GET", "/pages"),
    ("GET", "/posters/poster-1/preview"),
    ("PUT", "/pages/page-1/playlist"),
    ("POST", "/sync"),
    ("POST", "/send-all"),
    ("DELETE", "/pages/page-1/playlist"),
])
def test_unauthenticated_requests_never_reach_lab(app, client, monkeypatch, method, path):
    monkeypatch.setattr(
        "campaign_manager.blueprints.sound_assignments.requests.request",
        lambda *args, **kwargs: pytest.fail("unauthenticated request reached Content Lab"),
    )
    app.config["CONTENT_LAB_HUB_API_KEY"] = KEY
    url = "/api/sound-assignments" + path
    for headers in ({}, {"X-API-Key": KEY}, {"X-Hub-Write-Key": "wrong"}):
        response = client.open(url, method=method, headers=headers, json={})
        assert response.status_code == 401
        assert KEY not in response.get_data(as_text=True)


def test_missing_hub_key_fails_closed(app, client, monkeypatch):
    monkeypatch.delenv("HUB_WRITE_KEY")
    monkeypatch.setattr(
        "campaign_manager.blueprints.sound_assignments.requests.request",
        lambda *args, **kwargs: pytest.fail("unconfigured request reached Content Lab"),
    )
    response = client.get("/api/sound-assignments/pages", headers={"X-Hub-Write-Key": HUB_KEY})
    assert response.status_code == 503
