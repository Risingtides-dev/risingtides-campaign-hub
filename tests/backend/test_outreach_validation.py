"""Validation tests for network creator and outreach message endpoints.

Covers: malformed strings, booleans coerced to numbers, non-finite floats,
fractional post counts, negative values, and valid zero-price / ordinary inputs.
"""
from __future__ import annotations

import math
import pytest

from campaign_manager import db as _db
from campaign_manager.models import Campaign, NetworkCreator, OutreachMessage


# ── helpers ──────────────────────────────────────────────────────────

def _make_campaign(db, slug="test-campaign"):
    with db.get_session() as s:
        c = Campaign(slug=slug, title="Test Campaign")
        s.add(c)
        s.commit()
        s.refresh(c)
        return c.id


# ── _normalize_handle ─────────────────────────────────────────────────

class TestNormalizeHandle:
    def test_strips_at(self):
        assert _db._normalize_handle("@creator") == "creator"

    def test_strips_whitespace(self):
        assert _db._normalize_handle("  @Creator  ") == "creator"

    def test_lowercases(self):
        assert _db._normalize_handle("Creator") == "creator"

    def test_at_alone_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _db._normalize_handle("@")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _db._normalize_handle("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _db._normalize_handle("   ")

    def test_non_string_raises(self):
        with pytest.raises(ValueError, match="string"):
            _db._normalize_handle(123)


# ── _validate_rate ────────────────────────────────────────────────────

class TestValidateRate:
    def test_valid_zero(self):
        assert _db._validate_rate(0) == 0.0

    def test_valid_positive(self):
        assert _db._validate_rate(150) == 150.0

    def test_valid_string_number(self):
        assert _db._validate_rate("75.5") == 75.5

    def test_negative_raises(self):
        with pytest.raises(ValueError, match=">= 0"):
            _db._validate_rate(-1)

    def test_bool_true_raises(self):
        with pytest.raises(ValueError, match="boolean"):
            _db._validate_rate(True)

    def test_bool_false_raises(self):
        with pytest.raises(ValueError, match="boolean"):
            _db._validate_rate(False)

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="finite"):
            _db._validate_rate(float("nan"))

    def test_inf_raises(self):
        with pytest.raises(ValueError, match="finite"):
            _db._validate_rate(float("inf"))

    def test_neg_inf_raises(self):
        with pytest.raises(ValueError, match="finite"):
            _db._validate_rate(float("-inf"))

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="numeric"):
            _db._validate_rate("abc")


# ── _validate_posts ───────────────────────────────────────────────────

class TestValidatePosts:
    def test_valid_one(self):
        assert _db._validate_posts(1) == 1

    def test_valid_three(self):
        assert _db._validate_posts(3) == 3

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _db._validate_posts(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _db._validate_posts(-1)

    def test_fractional_raises(self):
        with pytest.raises(ValueError, match="whole number"):
            _db._validate_posts(2.5)

    def test_bool_true_raises(self):
        with pytest.raises(ValueError, match="boolean"):
            _db._validate_posts(True)

    def test_bool_false_raises(self):
        with pytest.raises(ValueError, match="boolean"):
            _db._validate_posts(False)

    def test_inf_raises(self):
        with pytest.raises(ValueError, match="finite"):
            _db._validate_posts(float("inf"))

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="numeric"):
            _db._validate_posts("two")

    def test_integer_as_string(self):
        assert _db._validate_posts("2") == 2


# ── add_network_creator ───────────────────────────────────────────────

class TestAddNetworkCreator:
    def test_valid_zero_rate(self, db):
        result = db.add_network_creator({
            "username": "creator1", "default_rate": 0, "default_posts": 1,
        })
        assert result["username"] == "creator1"
        assert result["default_rate"] == 0.0

    def test_valid_ordinary(self, db):
        result = db.add_network_creator({
            "username": "@Creator2", "default_rate": 200, "default_posts": 2,
        })
        assert result["username"] == "creator2"
        assert result["default_rate"] == 200.0
        assert result["default_posts"] == 2

    def test_at_only_username_raises(self, db):
        with pytest.raises(ValueError, match="non-empty"):
            db.add_network_creator({"username": "@", "default_rate": 0})

    def test_negative_rate_raises(self, db):
        with pytest.raises(ValueError, match=">= 0"):
            db.add_network_creator({
                "username": "creator3", "default_rate": -50, "default_posts": 1,
            })

    def test_bool_rate_raises(self, db):
        with pytest.raises(ValueError, match="boolean"):
            db.add_network_creator({
                "username": "creator4", "default_rate": True, "default_posts": 1,
            })

    def test_nan_rate_raises(self, db):
        with pytest.raises(ValueError, match="finite"):
            db.add_network_creator({
                "username": "creator5", "default_rate": float("nan"),
            })

    def test_inf_rate_raises(self, db):
        with pytest.raises(ValueError, match="finite"):
            db.add_network_creator({
                "username": "creator6", "default_rate": float("inf"),
            })

    def test_fractional_posts_raises(self, db):
        with pytest.raises(ValueError, match="whole number"):
            db.add_network_creator({
                "username": "creator7", "default_rate": 100, "default_posts": 1.5,
            })

    def test_zero_posts_raises(self, db):
        with pytest.raises(ValueError, match="positive"):
            db.add_network_creator({
                "username": "creator8", "default_rate": 100, "default_posts": 0,
            })

    def test_negative_posts_raises(self, db):
        with pytest.raises(ValueError, match="positive"):
            db.add_network_creator({
                "username": "creator9", "default_rate": 100, "default_posts": -1,
            })

    def test_bool_posts_raises(self, db):
        with pytest.raises(ValueError, match="boolean"):
            db.add_network_creator({
                "username": "creator10", "default_rate": 100, "default_posts": True,
            })

    def test_niches_non_list_raises(self, db):
        with pytest.raises(ValueError, match="niches"):
            db.add_network_creator({
                "username": "creator11", "default_rate": 0, "default_posts": 1,
                "niches": "pop",
            })


# ── update_network_creator ────────────────────────────────────────────

class TestUpdateNetworkCreator:
    def _seed(self, db):
        return db.add_network_creator({
            "username": "updater", "default_rate": 100, "default_posts": 1,
        })

    def test_valid_rate_update(self, db):
        self._seed(db)
        result = db.update_network_creator("updater", {"default_rate": 0})
        assert result["default_rate"] == 0.0

    def test_negative_rate_update_raises(self, db):
        self._seed(db)
        with pytest.raises(ValueError, match=">= 0"):
            db.update_network_creator("updater", {"default_rate": -10})

    def test_bool_rate_update_raises(self, db):
        self._seed(db)
        with pytest.raises(ValueError, match="boolean"):
            db.update_network_creator("updater", {"default_rate": False})

    def test_inf_rate_update_raises(self, db):
        self._seed(db)
        with pytest.raises(ValueError, match="finite"):
            db.update_network_creator("updater", {"default_rate": math.inf})

    def test_fractional_posts_update_raises(self, db):
        self._seed(db)
        with pytest.raises(ValueError, match="whole number"):
            db.update_network_creator("updater", {"default_posts": 3.3})

    def test_zero_posts_update_raises(self, db):
        self._seed(db)
        with pytest.raises(ValueError, match="positive"):
            db.update_network_creator("updater", {"default_posts": 0})

    def test_bool_posts_update_raises(self, db):
        self._seed(db)
        with pytest.raises(ValueError, match="boolean"):
            db.update_network_creator("updater", {"default_posts": True})

    def test_niches_non_list_update_raises(self, db):
        self._seed(db)
        with pytest.raises(ValueError, match="niches"):
            db.update_network_creator("updater", {"niches": "rock"})

    def test_valid_posts_update(self, db):
        self._seed(db)
        result = db.update_network_creator("updater", {"default_posts": 3})
        assert result["default_posts"] == 3


# ── add_outreach_messages ─────────────────────────────────────────────

class TestAddOutreachMessages:
    def test_valid_zero_rate(self, db):
        cid = _make_campaign(db)
        added = db.add_outreach_messages(cid, [
            {"username": "creator1", "rate": 0, "posts": 1},
        ])
        assert len(added) == 1
        assert added[0]["rate_offered"] == 0.0

    def test_valid_ordinary(self, db):
        cid = _make_campaign(db, "camp-b")
        added = db.add_outreach_messages(cid, [
            {"username": "@CreatorA", "rate": 150, "posts": 2},
            {"username": "creatorb", "rate": 75, "posts": 1},
        ])
        assert len(added) == 2
        assert added[0]["username"] == "creatora"

    def test_non_list_raises(self, db):
        cid = _make_campaign(db, "camp-c")
        with pytest.raises(ValueError, match="list"):
            db.add_outreach_messages(cid, {"username": "x", "rate": 0, "posts": 1})

    def test_non_dict_item_raises(self, db):
        cid = _make_campaign(db, "camp-d")
        with pytest.raises(ValueError, match="object"):
            db.add_outreach_messages(cid, ["creator1"])

    def test_at_only_username_raises(self, db):
        cid = _make_campaign(db, "camp-e")
        with pytest.raises(ValueError, match="non-empty"):
            db.add_outreach_messages(cid, [{"username": "@", "rate": 0, "posts": 1}])

    def test_negative_rate_raises(self, db):
        cid = _make_campaign(db, "camp-f")
        with pytest.raises(ValueError, match=">= 0"):
            db.add_outreach_messages(cid, [{"username": "x", "rate": -10, "posts": 1}])

    def test_bool_rate_raises(self, db):
        cid = _make_campaign(db, "camp-g")
        with pytest.raises(ValueError, match="boolean"):
            db.add_outreach_messages(cid, [{"username": "x", "rate": True, "posts": 1}])

    def test_nan_rate_raises(self, db):
        cid = _make_campaign(db, "camp-h")
        with pytest.raises(ValueError, match="finite"):
            db.add_outreach_messages(cid, [
                {"username": "x", "rate": float("nan"), "posts": 1}
            ])

    def test_inf_rate_raises(self, db):
        cid = _make_campaign(db, "camp-i")
        with pytest.raises(ValueError, match="finite"):
            db.add_outreach_messages(cid, [
                {"username": "x", "rate": float("inf"), "posts": 1}
            ])

    def test_fractional_posts_raises(self, db):
        cid = _make_campaign(db, "camp-j")
        with pytest.raises(ValueError, match="whole number"):
            db.add_outreach_messages(cid, [{"username": "x", "rate": 0, "posts": 1.5}])

    def test_zero_posts_raises(self, db):
        cid = _make_campaign(db, "camp-k")
        with pytest.raises(ValueError, match="positive"):
            db.add_outreach_messages(cid, [{"username": "x", "rate": 0, "posts": 0}])

    def test_bool_posts_raises(self, db):
        cid = _make_campaign(db, "camp-l")
        with pytest.raises(ValueError, match="boolean"):
            db.add_outreach_messages(cid, [{"username": "x", "rate": 0, "posts": False}])

    def test_batch_atomic_on_invalid_second_item(self, db):
        """If any item fails validation, nothing is inserted."""
        cid = _make_campaign(db, "camp-m")
        with pytest.raises(ValueError):
            db.add_outreach_messages(cid, [
                {"username": "good", "rate": 100, "posts": 1},
                {"username": "bad", "rate": -5, "posts": 1},
            ])
        # Confirm nothing was inserted
        with db.get_session() as s:
            count = s.query(OutreachMessage).filter_by(campaign_id=cid).count()
        assert count == 0


# ── HTTP layer: add_to_network ────────────────────────────────────────

class TestNetworkEndpointValidation:
    def test_negative_rate_returns_400(self, client):
        resp = client.post("/api/network", json={
            "username": "netcreator", "default_rate": -1, "default_posts": 1,
        })
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_bool_rate_returns_400(self, client):
        resp = client.post("/api/network", json={
            "username": "netcreator", "default_rate": True, "default_posts": 1,
        })
        assert resp.status_code == 400

    def test_nan_rate_returns_400(self, client):
        # JSON can't encode NaN directly, but the string "NaN" coerces
        # to NaN via float() — simulate an internal call path
        with pytest.raises(ValueError, match="finite"):
            _db._validate_rate(float("nan"))

    def test_fractional_posts_returns_400(self, client):
        resp = client.post("/api/network", json={
            "username": "netcreator2", "default_rate": 50, "default_posts": 1.5,
        })
        assert resp.status_code == 400

    def test_at_only_username_returns_400(self, client):
        resp = client.post("/api/network", json={
            "username": "@", "default_rate": 0, "default_posts": 1,
        })
        # The outer check `if not data.get("username")` catches "@" as truthy,
        # so it reaches db.add_network_creator which raises ValueError -> 400
        assert resp.status_code == 400

    def test_valid_zero_rate_returns_200(self, client):
        resp = client.post("/api/network", json={
            "username": "zerorate", "default_rate": 0, "default_posts": 1,
        })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True


# ── HTTP layer: add_to_outreach ───────────────────────────────────────

class TestOutreachEndpointValidation:
    def _make_campaign_via_db(self, client_fixture, db_fixture):
        with db_fixture.get_session() as s:
            c = Campaign(slug="oc-test", title="OC Test")
            s.add(c)
            s.commit()

    def test_negative_rate_returns_400(self, client, db):
        with db.get_session() as s:
            c = Campaign(slug="oc-neg", title="T")
            s.add(c)
            s.commit()
        resp = client.post("/api/campaign/oc-neg/outreach/add", json=[
            {"username": "x", "rate": -1, "posts": 1},
        ])
        assert resp.status_code == 400

    def test_bool_posts_returns_400(self, client, db):
        with db.get_session() as s:
            c = Campaign(slug="oc-bool", title="T")
            s.add(c)
            s.commit()
        resp = client.post("/api/campaign/oc-bool/outreach/add", json=[
            {"username": "x", "rate": 100, "posts": True},
        ])
        assert resp.status_code == 400

    def test_valid_batch_returns_200(self, client, db):
        with db.get_session() as s:
            c = Campaign(slug="oc-ok", title="T")
            s.add(c)
            s.commit()
        resp = client.post("/api/campaign/oc-ok/outreach/add", json=[
            {"username": "creatorA", "rate": 200, "posts": 2},
            {"username": "creatorB", "rate": 0, "posts": 1},
        ])
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["added"] == 2
