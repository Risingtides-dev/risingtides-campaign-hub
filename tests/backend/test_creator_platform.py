"""Add Creator platform toggle: TikTok vs Instagram is saved and validated."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def _setup(client):
    res = client.post("/api/campaign/create", json={"title": "Platform Test", "budget": 5000})
    return res.get_json()["slug"]


def _add(client, slug, **body):
    payload = {"posts_owed": 2, "total_rate": 300, **body}
    return client.post(f"/api/campaign/{slug}/creator/add", json=payload)


def _creator(client, slug, username):
    detail = client.get(f"/api/campaign/{slug}").get_json()
    return next(c for c in detail["creators"] if c["username"] == username)


class TestCreatorPlatform:
    def test_defaults_to_tiktok(self, client):
        slug = _setup(client)
        assert _add(client, slug, username="ttguy").status_code in (200, 201)
        assert _creator(client, slug, "ttguy")["platform"] == "tiktok"

    def test_instagram_toggle_is_saved(self, client):
        slug = _setup(client)
        assert _add(client, slug, username="iggal", platform="Instagram").status_code in (200, 201)
        assert _creator(client, slug, "iggal")["platform"] == "instagram"

    def test_pasted_instagram_link_becomes_ig_handle(self, client):
        slug = _setup(client)
        res = _add(client, slug, username="https://www.instagram.com/Reel.Maker/?hl=en")
        assert res.status_code in (200, 201)
        c = _creator(client, slug, "reel.maker")
        assert c["platform"] == "instagram"

    def test_unknown_platform_rejected(self, client):
        slug = _setup(client)
        res = _add(client, slug, username="x", platform="youtube")
        assert res.status_code == 400
