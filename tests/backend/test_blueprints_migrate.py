"""Integration tests for one-time campaign imports."""
from __future__ import annotations

import pytest


_MIGRATION_KEY = "migration-test-secret"
_MIGRATION_HEADERS = {"X-Hub-Write-Key": _MIGRATION_KEY}


class TestCampaignFullMigration:
    def test_authenticated_unique_create_remains_available(self, client, db, monkeypatch):
        monkeypatch.setenv("HUB_WRITE_KEY", _MIGRATION_KEY)
        response = client.post("/api/migrate/campaign-full", json={
            "slug": "authorized", "campaign": {
                "title": "Authorized", "official_sound":
                    "https://www.tiktok.com/music/unique-1234567890123456789",
            },
        }, headers=_MIGRATION_HEADERS)
        assert response.status_code == 201
        assert db.get_campaign("authorized")["title"] == "Authorized"

    @pytest.mark.parametrize("query", ["", "?overwrite=1"])
    @pytest.mark.parametrize("headers", [{}, {"X-Hub-Write-Key": "wrong"}])
    def test_rejects_unauthenticated_create_or_overwrite(self, client, db, monkeypatch, query, headers):
        monkeypatch.setenv("HUB_WRITE_KEY", _MIGRATION_KEY)
        slug = "unauthorized"
        if query:
            slug = "protected_campaign"
            db.save_campaign(slug, {"title": "Protected", "budget": 100})
        response = client.post(f"/api/migrate/campaign-full{query}", json={
            "slug": slug, "campaign": {"title": "Unauthorized", "budget": 0},
        }, headers=headers)
        assert response.status_code == 401
        assert response.get_json()["code"] == "unauthorized"
        if query:
            saved = db.get_campaign(slug)
            assert saved["title"] == "Protected"
            assert saved["budget"] == 100
        else:
            assert db.get_campaign(slug) is None

    def test_fails_closed_when_no_migration_key_is_configured(self, client, db, monkeypatch):
        monkeypatch.delenv("HUB_WRITE_KEY", raising=False)
        db.save_campaign("protected_campaign", {"title": "Protected", "budget": 100})
        response = client.post("/api/migrate/campaign-full?overwrite=1", json={
            "slug": "protected_campaign", "campaign": {"title": "Disabled", "budget": 0},
        }, headers=_MIGRATION_HEADERS)
        assert response.status_code == 503
        assert response.get_json()["code"] == "migration_auth_unconfigured"
        saved = db.get_campaign("protected_campaign")
        assert saved["title"] == "Protected"
        assert saved["budget"] == 100

    def test_rejects_duplicate_canonical_official_sound_url(self, client, db, monkeypatch):
        monkeypatch.setenv("HUB_WRITE_KEY", _MIGRATION_KEY)
        url = "https://www.tiktok.com/music/shared-1234567890123456789"
        db.save_campaign("existing", {"title": "Existing", "official_sound": url})

        response = client.post("/api/migrate/campaign-full", json={
            "slug": "imported", "campaign": {
                "title": "Imported", "official_sound":
                    "HTTPS://WWW.TIKTOK.COM:443/music/shared-1234567890123456789#share",
            },
        }, headers=_MIGRATION_HEADERS)

        assert response.status_code == 409
        assert response.get_json()["code"] == "duplicate"
        assert db.get_campaign("imported") is None

    def test_overwrite_cannot_replace_sound_with_another_campaigns_url(self, client, db, monkeypatch):
        monkeypatch.setenv("HUB_WRITE_KEY", _MIGRATION_KEY)
        existing_url = "https://www.tiktok.com/music/old-1234567890123456789"
        duplicate_url = "https://www.tiktok.com/music/shared-1234567890123456789"
        db.save_campaign("target", {"title": "Target", "official_sound": existing_url})
        db.save_campaign("other", {"title": "Other", "official_sound": duplicate_url})

        response = client.post("/api/migrate/campaign-full?overwrite=1", json={
            "slug": "target", "campaign": {
                "title": "Replacement", "official_sound": duplicate_url,
            },
        }, headers=_MIGRATION_HEADERS)

        assert response.status_code == 409
        assert response.get_json()["code"] == "duplicate"
        saved = db.get_campaign("target")
        assert saved["title"] == "Target"
        assert saved["official_sound"] == existing_url

    def test_overwrite_preserves_explicit_overwrite_behavior_for_unique_url(self, client, db, monkeypatch):
        monkeypatch.setenv("HUB_WRITE_KEY", _MIGRATION_KEY)
        old_url = "https://www.tiktok.com/music/old-1234567890123456789"
        new_url = "https://www.tiktok.com/music/new-1234567890123456789"
        db.save_campaign("target", {"title": "Target", "official_sound": old_url})

        response = client.post("/api/migrate/campaign-full?overwrite=1", json={
            "slug": "target", "campaign": {
                "title": "Replacement", "official_sound": new_url,
            },
        }, headers=_MIGRATION_HEADERS)

        assert response.status_code == 201
        saved = db.get_campaign("target")
        assert saved["title"] == "Replacement"
        assert saved["official_sound"] == new_url
