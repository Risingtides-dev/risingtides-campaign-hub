"""Integration tests for one-time campaign imports."""
from __future__ import annotations


class TestCampaignFullMigration:
    def test_rejects_duplicate_canonical_official_sound_url(self, client, db):
        url = "https://www.tiktok.com/music/shared-1234567890123456789"
        db.save_campaign("existing", {"title": "Existing", "official_sound": url})

        response = client.post("/api/migrate/campaign-full", json={
            "slug": "imported", "campaign": {
                "title": "Imported", "official_sound":
                    "HTTPS://WWW.TIKTOK.COM:443/music/shared-1234567890123456789#share",
            },
        })

        assert response.status_code == 409
        assert response.get_json()["code"] == "duplicate"
        assert db.get_campaign("imported") is None

    def test_overwrite_cannot_replace_sound_with_another_campaigns_url(self, client, db):
        existing_url = "https://www.tiktok.com/music/old-1234567890123456789"
        duplicate_url = "https://www.tiktok.com/music/shared-1234567890123456789"
        db.save_campaign("target", {"title": "Target", "official_sound": existing_url})
        db.save_campaign("other", {"title": "Other", "official_sound": duplicate_url})

        response = client.post("/api/migrate/campaign-full?overwrite=1", json={
            "slug": "target", "campaign": {
                "title": "Replacement", "official_sound": duplicate_url,
            },
        })

        assert response.status_code == 409
        assert response.get_json()["code"] == "duplicate"
        saved = db.get_campaign("target")
        assert saved["title"] == "Target"
        assert saved["official_sound"] == existing_url

    def test_overwrite_preserves_explicit_overwrite_behavior_for_unique_url(self, client, db):
        old_url = "https://www.tiktok.com/music/old-1234567890123456789"
        new_url = "https://www.tiktok.com/music/new-1234567890123456789"
        db.save_campaign("target", {"title": "Target", "official_sound": old_url})

        response = client.post("/api/migrate/campaign-full?overwrite=1", json={
            "slug": "target", "campaign": {
                "title": "Replacement", "official_sound": new_url,
            },
        })

        assert response.status_code == 201
        saved = db.get_campaign("target")
        assert saved["title"] == "Replacement"
        assert saved["official_sound"] == new_url
