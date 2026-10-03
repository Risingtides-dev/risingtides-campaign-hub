"""Tests for the sideload orchestrator: happy path, partial failure,
idempotent re-run, dry-run, disabled flag, multi-activation resolution."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from campaign_manager import db as _db
from campaign_manager.models import Base, Campaign, MatchedVideo
# Import registers the sideload tables on Base.metadata.
import campaign_manager.services.cobrand_sideload.models  # noqa: F401
from campaign_manager.services.cobrand_sideload.models import CobrandSideloadTask
from campaign_manager.services.cobrand_sideload.config import SideloadConfig
from campaign_manager.services.cobrand_sideload.sync import (
    sync_campaign,
    SideloadDisabledError,
)
from campaign_manager.services.cobrand_sideload.types import (
    Activation,
    BulkCreateGroup,
    GetPromotionResponse,
    Task,
)

U1 = "https://www.tiktok.com/@a/video/1"
U2 = "https://www.tiktok.com/@b/video/2"


@pytest.fixture
def db_env():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    _db._engine = engine
    _db._SessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    try:
        yield _db
    finally:
        _db._engine = None
        _db._SessionLocal = None


def _seed(slug="camp", promo="promo-1", artist="Artist", title="Song", urls=(U1, U2)):
    with _db.get_session() as s:
        c = Campaign(
            slug=slug, title=title, name=title, artist=artist,
            cobrand_promotion_id=promo, start_date="2020-01-01",
        )
        s.add(c)
        s.flush()
        cid = c.id
        for u in urls:
            s.add(MatchedVideo(
                campaign_id=cid, url=u,
                timestamp="2024-01-01T00:00:00", upload_date="20240101",
            ))
        s.commit()
    return cid


class FakeClient:
    def __init__(self, activations, task_map, group_id="group-1", pending_first=True):
        self.activations = activations
        self.task_map = task_map  # url -> (status, collaboration_id, submission_id)
        self.group_id = group_id
        self.pending_first = pending_first
        self.poll_calls = 0
        self.uploaded = None
        self.validated = []

    def get_promotion(self, promotion_id):
        return GetPromotionResponse(
            id=promotion_id, name="P", status="active", activations=self.activations
        )

    def validate_live_post_url(self, url):
        self.validated.append(url)
        return {"valid": True}

    def bulk_upload(self, activation_id, urls):
        self.uploaded = (activation_id, list(urls))
        return self.group_id

    def list_bulk_create_groups(self, activation_id, limit=99, offset=0):
        self.poll_calls += 1
        urls = list(self.uploaded[1]) if self.uploaded else list(self.task_map)
        if self.pending_first and self.poll_calls == 1:
            return [BulkCreateGroup(
                id=self.group_id, activation_id=activation_id,
                total_count=len(urls), pending_count=len(urls),
            )]
        tasks, succ, fail = [], 0, 0
        for u in urls:
            status, collab, sub = self.task_map.get(u, ("SUCCESS", None, None))
            tasks.append(Task(id="t-" + u[-1], url=u, status=status,
                              collaboration_id=collab, submission_id=sub))
            if status == "SUCCESS":
                succ += 1
            else:
                fail += 1
        return [BulkCreateGroup(
            id=self.group_id, activation_id=activation_id, total_count=len(urls),
            pending_count=0, success_count=succ, failure_count=fail, tasks=tasks,
        )]


def _act(id="act-1", name="Song", artist="Artist"):
    return Activation(id=id, name=name, artist_name=artist)


def _enabled_cfg():
    return SideloadConfig(enabled=True, poll_interval_seconds=0.0, poll_max_attempts=5)


def test_happy_path_partial_failure(db_env):
    _seed()
    client = FakeClient(
        activations=[_act()],
        task_map={U1: ("SUCCESS", "collab-1", "sub-1"), U2: ("FAILURE", None, None)},
    )
    report = sync_campaign(
        "camp", config=_enabled_cfg(), client=client, sleep=lambda d: None
    )

    assert report.activation_id == "act-1"
    assert report.uploaded == 2
    assert report.succeeded == 1
    assert report.failed == 1
    assert client.uploaded[0] == "act-1"
    assert sorted(client.uploaded[1]) == sorted([U1, U2])

    # MatchedVideo: success tracked, failure left in the queue.
    with _db.get_session() as s:
        mv1 = s.query(MatchedVideo).filter_by(url=U1).first()
        mv2 = s.query(MatchedVideo).filter_by(url=U2).first()
        assert mv1.tracked_at is not None
        assert mv1.tracked_by == "cobrand-sideload"
        assert mv2.tracked_at is None

        # Ledger reflects per-task outcomes.
        t1 = s.query(CobrandSideloadTask).filter_by(url=U1).first()
        t2 = s.query(CobrandSideloadTask).filter_by(url=U2).first()
        assert t1.status == "SUCCESS"
        assert t1.collaboration_id == "collab-1"
        assert t1.submission_id == "sub-1"
        assert t2.status == "FAILURE"


def test_poll_loop_waits_for_pending(db_env):
    _seed(urls=(U1,))
    client = FakeClient(activations=[_act()], task_map={U1: ("SUCCESS", "c", "s")},
                        pending_first=True)
    report = sync_campaign("camp", config=_enabled_cfg(), client=client,
                           sleep=lambda d: None)
    assert client.poll_calls == 2  # first pending, second done
    assert report.succeeded == 1


def test_idempotent_rerun_skips_ledgered_urls(db_env):
    _seed()
    client = FakeClient(activations=[_act()],
                        task_map={U1: ("SUCCESS", "c1", "s1"), U2: ("SUCCESS", "c2", "s2")})
    sync_campaign("camp", config=_enabled_cfg(), client=client, sleep=lambda d: None)

    # Simulate the U1 row re-entering the queue (tracked_at cleared) while its
    # ledger row stays SUCCESS — the ledger must prevent a duplicate upload.
    with _db.get_session() as s:
        mv1 = s.query(MatchedVideo).filter_by(url=U1).first()
        mv1.tracked_at = None
        s.commit()

    client2 = FakeClient(activations=[_act()], task_map={})
    report = sync_campaign("camp", config=_enabled_cfg(), client=client2,
                           sleep=lambda d: None)
    assert report.skipped_already == 1
    assert report.uploaded == 0
    assert client2.uploaded is None  # bulk_upload never called


def test_dry_run_makes_no_writes(db_env):
    _seed()
    client = FakeClient(activations=[_act()], task_map={})
    # enabled=False but dry_run=True must be allowed.
    report = sync_campaign("camp", config=SideloadConfig(enabled=False),
                           client=client, dry_run=True, sleep=lambda d: None)
    assert report.dry_run is True
    assert report.uploaded == 0
    assert "dry-run" in report.message
    assert client.uploaded is None
    with _db.get_session() as s:
        assert s.query(CobrandSideloadTask).count() == 0


def test_disabled_without_dry_run_raises(db_env):
    _seed()
    client = FakeClient(activations=[_act()], task_map={})
    with pytest.raises(SideloadDisabledError):
        sync_campaign("camp", config=SideloadConfig(enabled=False), client=client)


def test_multi_activation_resolves_by_artist(db_env):
    _seed(artist="Artist")
    client = FakeClient(
        activations=[
            _act(id="act-x", name="Other", artist="Someone Else"),
            _act(id="act-y", name="Song", artist="Artist"),
        ],
        task_map={U1: ("SUCCESS", "c", "s"), U2: ("SUCCESS", "c", "s")},
    )
    report = sync_campaign("camp", config=_enabled_cfg(), client=client,
                           sleep=lambda d: None)
    assert report.activation_id == "act-y"
    assert client.uploaded[0] == "act-y"


def test_no_promotion_id_is_noop(db_env):
    _seed(promo="")
    client = FakeClient(activations=[_act()], task_map={})
    report = sync_campaign("camp", config=_enabled_cfg(), client=client,
                           sleep=lambda d: None)
    assert report.uploaded == 0
    assert "promotion" in report.message
