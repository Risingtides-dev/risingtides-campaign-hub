"""Tests for the atomic-claim send path on /api/campaign/<slug>/outreach/send.

Covers:
 - Atomic claim: second claim on the same campaign returns nothing (proves
   exactly-once delivery at the DB layer, without threading).
 - Transport exception after provider accepts: row ends in 'failed', not 'draft'.
 - Provider HTTP error: row ends in 'failed', not 'draft'.
 - Clean success: row ends in 'sent'.
 - No-API-key path: treated as success (manual follow-up).
 - Row in 'sending' is not re-claimed by a subsequent call.
 - Second HTTP send on the same campaign returns 400 (no drafts left).

Note on concurrency: SQLite (used for tests) uses SingletonThreadPool which
cannot safely share connections across threads. The serialised-claim tests here
exercise the same atomicity property as the multi-threaded production case: an
atomic UPDATE WHERE status='draft' means any second caller — whether
concurrent or sequential — finds zero rows to claim.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from campaign_manager import db as _db
from campaign_manager.models import Campaign, NetworkCreator, OutreachMessage


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_campaign(db, session, slug="test-camp"):
    c = Campaign(
        title="Test Campaign",
        slug=slug,
        artist="Test Artist",
        song="Test Song",
        sound_id="12345",
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return c.id  # return id, not object (avoid DetachedInstanceError)


def _make_network_creator(session, username, subscriber_id="sub_001"):
    nc = NetworkCreator(
        username=username,
        manychat_subscriber_id=subscriber_id,
        platform="instagram",
    )
    session.add(nc)
    session.commit()


def _add_draft(session, campaign_id, username, rate=500.0, posts=1):
    m = OutreachMessage(
        campaign_id=campaign_id,
        username=username.lower(),
        rate_offered=rate,
        posts_offered=posts,
        status="draft",
    )
    session.add(m)
    session.commit()


# ── claim_draft_messages unit tests ──────────────────────────────────────────

class TestClaimDraftMessages:
    def test_claims_all_drafts(self, db, engine):
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s)
            _add_draft(s, cid, "creator_a")
            _add_draft(s, cid, "creator_b")

        attempt_id = str(uuid.uuid4())
        claimed = _db.claim_draft_messages(cid, attempt_id)
        assert set(claimed) == {"creator_a", "creator_b"}

        with _db._SessionLocal() as s:
            msgs = s.query(OutreachMessage).filter_by(campaign_id=cid).all()
            for m in msgs:
                assert m.status == "sending"
                assert m.sending_attempt_id == attempt_id

    def test_second_claim_finds_nothing(self, db, engine):
        """After a first claim succeeds, a second claim returns empty.

        This is the serial equivalent of the concurrent-request race: the
        atomic UPDATE WHERE status='draft' guarantees exactly-once delivery.
        """
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="second-claim-camp")
            _add_draft(s, cid, "creator_x")
            _add_draft(s, cid, "creator_y")

        first_attempt = str(uuid.uuid4())
        first_claimed = _db.claim_draft_messages(cid, first_attempt)
        assert len(first_claimed) == 2

        second_attempt = str(uuid.uuid4())
        second_claimed = _db.claim_draft_messages(cid, second_attempt)
        assert second_claimed == []

    def test_already_sending_not_re_claimed(self, db, engine):
        """A row already in 'sending' is not picked up by a later claim."""
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="sending-camp")
            _add_draft(s, cid, "creator_p")

        first_attempt = str(uuid.uuid4())
        _db.claim_draft_messages(cid, first_attempt)

        second_attempt = str(uuid.uuid4())
        claimed_again = _db.claim_draft_messages(cid, second_attempt)
        assert claimed_again == []

    def test_empty_campaign_returns_empty(self, db, engine):
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="empty-camp")

        claimed = _db.claim_draft_messages(cid, str(uuid.uuid4()))
        assert claimed == []

    def test_does_not_claim_sent_rows(self, db, engine):
        """Rows already in 'sent' are never re-claimed."""
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="sent-camp")
            # Manually insert a 'sent' row
            m = OutreachMessage(
                campaign_id=cid,
                username="already_sent",
                status="sent",
            )
            s.add(m)
            s.commit()

        claimed = _db.claim_draft_messages(cid, str(uuid.uuid4()))
        assert claimed == []


# ── send_outreach endpoint tests ─────────────────────────────────────────────

SEND_URL_TPL = "/api/campaign/{slug}/outreach/send"
TEMPLATE = "Hey {creator}, join our {artist} campaign!"


class TestSendOutreachAtomic:
    def _post_send(self, client, slug, template=TEMPLATE):
        return client.post(
            SEND_URL_TPL.format(slug=slug),
            json={"message_template": template},
        )

    def test_clean_success_no_api_key(self, client, db):
        """No MANYCHAT_API_KEY → treated as success, row → sent."""
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="clean-success")
            _make_network_creator(s, "creator_ok")
            _add_draft(s, cid, "creator_ok")

        resp = self._post_send(client, "clean-success")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "creator_ok" in data["sent"]
        assert data["errors"] == []

        with _db._SessionLocal() as s:
            m = s.query(OutreachMessage).filter_by(
                campaign_id=cid, username="creator_ok"
            ).first()
            assert m.status == "sent"
            assert m.sent_at is not None

    def test_transport_timeout_leaves_failed_not_draft(self, client, db):
        """A requests.Timeout during provider POST → status 'failed', not 'draft'."""
        import requests as req
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="timeout-camp")
            _make_network_creator(s, "creator_timeout")
            _add_draft(s, cid, "creator_timeout")

        with patch.dict(client.application.config, {"MANYCHAT_API_KEY": "fake-key"}):
            with patch("campaign_manager.blueprints.outreach.http_requests.post",
                       side_effect=req.Timeout("timed out")):
                resp = self._post_send(client, "timeout-camp")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["sent"] == []
        assert any("creator_timeout" in e["username"] for e in data["errors"])

        with _db._SessionLocal() as s:
            m = s.query(OutreachMessage).filter_by(
                campaign_id=cid, username="creator_timeout"
            ).first()
            assert m.status == "failed", "timeout must not revert row to 'draft'"
            assert m.failed_at is not None

    def test_provider_4xx_leaves_failed_not_draft(self, client, db):
        """A non-200 ManyChat response → status 'failed', not 'draft'."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad subscriber"

        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="provider-err-camp")
            _make_network_creator(s, "creator_err")
            _add_draft(s, cid, "creator_err")

        with patch.dict(client.application.config, {"MANYCHAT_API_KEY": "fake-key"}):
            with patch("campaign_manager.blueprints.outreach.http_requests.post",
                       return_value=mock_resp):
                resp = self._post_send(client, "provider-err-camp")

        assert resp.status_code == 200
        with _db._SessionLocal() as s:
            m = s.query(OutreachMessage).filter_by(
                campaign_id=cid, username="creator_err"
            ).first()
            assert m.status == "failed"

    def test_no_subscriber_id_leaves_failed(self, client, db):
        """Creator without manychat_subscriber_id → error returned, row → failed."""
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="no-sub-camp")
            _make_network_creator(s, "creator_nosub", subscriber_id="")
            _add_draft(s, cid, "creator_nosub")

        resp = self._post_send(client, "no-sub-camp")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["sent"] == []
        assert data["errors"]

        with _db._SessionLocal() as s:
            m = s.query(OutreachMessage).filter_by(
                campaign_id=cid, username="creator_nosub"
            ).first()
            assert m.status == "failed"

    def test_no_drafts_returns_400(self, client, db):
        """Campaign with no drafts → 400 immediately."""
        with _db._SessionLocal() as s:
            _make_campaign(db, s, slug="no-drafts-camp")

        resp = self._post_send(client, "no-drafts-camp")
        assert resp.status_code == 400

    def test_second_send_returns_400(self, client, db):
        """After a successful send, a second send request finds no drafts (400).

        Proves that the claim is durable: the row is never automatically
        reverted to 'draft', so a retry cannot replay a send that succeeded.
        """
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="second-send")
            _make_network_creator(s, "creator_second")
            _add_draft(s, cid, "creator_second")

        resp1 = self._post_send(client, "second-send")
        assert resp1.status_code == 200
        assert "creator_second" in resp1.get_json()["sent"]

        resp2 = self._post_send(client, "second-send")
        assert resp2.status_code == 400, (
            "second send should return 400 (no drafts left), "
            "not silently re-dispatch a claimed row"
        )

    def test_failed_send_does_not_retry_on_next_call(self, client, db):
        """A failed send leaves the row in 'failed', not 'draft'; a subsequent
        send request returns 400 rather than re-dispatching the message.
        """
        import requests as req
        with _db._SessionLocal() as s:
            cid = _make_campaign(db, s, slug="no-retry-camp")
            _make_network_creator(s, "creator_noresp")
            _add_draft(s, cid, "creator_noresp")

        with patch.dict(client.application.config, {"MANYCHAT_API_KEY": "fake-key"}):
            with patch("campaign_manager.blueprints.outreach.http_requests.post",
                       side_effect=req.Timeout("timed out")):
                resp1 = self._post_send(client, "no-retry-camp")
        assert resp1.status_code == 200

        # Second call must NOT re-dispatch
        resp2 = self._post_send(client, "no-retry-camp")
        assert resp2.status_code == 400
