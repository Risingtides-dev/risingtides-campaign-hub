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


class TestSameHandleBothPlatforms:
    def _both(self, client):
        slug = _setup(client)
        assert _add(client, slug, username="elliebarker", total_rate=300).status_code in (200, 201)
        res = _add(client, slug, username="elliebarker", platform="instagram", total_rate=200)
        assert res.status_code in (200, 201), res.get_json()
        return slug

    def _rows(self, client, slug):
        detail = client.get(f"/api/campaign/{slug}").get_json()
        return {c["platform"]: c for c in detail["creators"] if c["username"] == "elliebarker"}

    def test_can_book_tiktok_and_instagram(self, client):
        slug = self._both(client)
        rows = self._rows(client, slug)
        assert set(rows) == {"tiktok", "instagram"}
        assert rows["tiktok"]["total_rate"] == 300
        assert rows["instagram"]["total_rate"] == 200

    def test_same_platform_twice_still_blocked(self, client):
        slug = self._both(client)
        res = _add(client, slug, username="elliebarker", platform="instagram")
        assert res.status_code == 409
        assert "Instagram" in res.get_json()["error"]

    def test_edit_targets_one_platform(self, client):
        slug = self._both(client)
        res = client.post(
            f"/api/campaign/{slug}/creator/elliebarker/edit?platform=instagram",
            json={"posts_owed": 5, "total_rate": 500},
        )
        assert res.status_code == 200
        rows = self._rows(client, slug)
        assert rows["instagram"]["total_rate"] == 500
        assert rows["tiktok"]["total_rate"] == 300

    def test_toggle_paid_targets_one_platform(self, client):
        slug = self._both(client)
        client.post(f"/api/campaign/{slug}/creator/elliebarker/toggle-paid?platform=tiktok")
        rows = self._rows(client, slug)
        assert rows["tiktok"]["paid"] == "yes"
        assert rows["instagram"]["paid"] != "yes"

    def test_remove_targets_one_platform_and_readd_works(self, client):
        slug = self._both(client)
        res = client.post(
            f"/api/campaign/{slug}/creator/remove",
            json={"username": "elliebarker", "platform": "instagram"},
        )
        assert res.status_code == 200
        assert set(self._rows(client, slug)) == {"tiktok"}
        again = _add(client, slug, username="elliebarker", platform="instagram")
        assert again.status_code in (200, 201)
        assert set(self._rows(client, slug)) == {"tiktok", "instagram"}

    def test_ambiguous_action_without_platform_is_rejected(self, client):
        slug = self._both(client)
        res = client.post(f"/api/campaign/{slug}/creator/elliebarker/toggle-paid")
        assert res.status_code == 400
        rows = self._rows(client, slug)
        assert rows["tiktok"]["paid"] != "yes" and rows["instagram"]["paid"] != "yes"

    def test_single_booking_still_works_without_platform(self, client):
        slug = _setup(client)
        _add(client, slug, username="solo")
        res = client.post(f"/api/campaign/{slug}/creator/solo/toggle-paid")
        assert res.status_code == 200


def test_post_counts_split_by_platform():
    from campaign_manager.services.matching import update_creator_post_counts
    creators = [
        {"username": "EllieBarker", "platform": "tiktok"},
        {"username": "elliebarker", "platform": "instagram"},
    ]
    videos = [
        {"account": "@elliebarker", "platform": "tiktok"},
        {"account": "@elliebarker"},  # legacy rows without platform are TikTok
        {"account": "@elliebarker", "platform": "instagram"},
    ]
    out = update_creator_post_counts(creators, videos)
    assert [c["posts_matched"] for c in out] == [2, 1]
    assert "posts_matched" not in creators[0]  # inputs untouched
