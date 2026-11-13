"""Creator-only hostname serves the creator dashboard and nothing else."""
import pytest

HOST = "creators.example.com"


@pytest.fixture
def gated(app):
    app.config.update(CREATOR_HOST=HOST)
    return app


@pytest.mark.parametrize("path", [
    "/api/campaigns", "/api/campaign/live", "/api/library/creators", "/api/payouts/admin/creators",
    "/", "/payouts", "/campaign/live", "/creators",
])
def test_hub_paths_are_404_on_creator_host(gated, client, path):
    assert client.get(path, base_url=f"https://{HOST}").status_code == 404


def test_creator_api_allowed_on_creator_host(gated, client):
    resp = client.post("/api/creator/dashboard", json={"token": "x" * 43}, base_url=f"https://{HOST}")
    assert resp.status_code in (404, 503)  # reached the endpoint (unknown token / no DB) — not the gate
    assert resp.is_json


def test_hub_host_unaffected(gated, client):
    assert client.get("/api/campaigns", base_url="https://campaignhub.example.com").status_code != 404
    assert client.get("/api/campaigns", base_url=f"https://{HOST.upper()}:443").status_code == 404


def test_gate_off_when_unset(app, client):
    app.config.update(CREATOR_HOST="")
    assert client.get("/api/campaigns", base_url=f"https://{HOST}").status_code != 404
