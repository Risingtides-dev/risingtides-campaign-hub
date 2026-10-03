"""Dry compile checks for the fix/scrape-upserts statements.

The functional tests exercise merge_internal_cache / add_group_members /
_apply_membership_diff against in-memory sqlite, which takes the sqlite
branch of db.dialect_insert / db._sql_greatest. Production is Postgres,
so these tests force the postgresql branch and verify the exact statement
shapes those functions build actually render on the postgresql dialect
(ON CONFLICT target, GREATEST, RETURNING).
"""
import pytest
from sqlalchemy.dialects import postgresql

from campaign_manager import db
from campaign_manager.models import (
    InternalCreatorGroupMember,
    InternalVideoCache,
    InternalVideoGroupAttribution,
)


class _FakePgDialect:
    name = "postgresql"


class _FakePgEngine:
    dialect = _FakePgDialect()


@pytest.fixture
def pg_engine(monkeypatch):
    monkeypatch.setattr(db, "_engine", _FakePgEngine())


def _compile_pg(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_video_cache_upsert_compiles_for_postgres(pg_engine):
    cache_t = InternalVideoCache.__table__
    stmt = db.dialect_insert(cache_t).values([{
        "username": "alice",
        "url": "https://tiktok.com/v/1",
        "song": "s",
        "artist": "a",
        "account": "@alice",
        "views": 10,
        "likes": 2,
        "upload_date": "20260701",
        "timestamp": "",
        "cached_at": None,
    }])
    stmt = stmt.on_conflict_do_update(
        index_elements=["username", "url"],
        set_={
            "views": db._sql_greatest(cache_t.c.views, stmt.excluded.views),
            "likes": db._sql_greatest(cache_t.c.likes, stmt.excluded.likes),
            "cached_at": stmt.excluded.cached_at,
        },
    ).returning(cache_t.c.id, cache_t.c.url)

    sql = _compile_pg(stmt)
    assert "ON CONFLICT (username, url) DO UPDATE" in sql
    assert "greatest(coalesce(" in sql
    assert "excluded.views" in sql
    assert "RETURNING internal_video_cache.id, internal_video_cache.url" in sql


def test_attribution_insert_compiles_for_postgres(pg_engine):
    attr_t = InternalVideoGroupAttribution.__table__
    stmt = db.dialect_insert(attr_t).values([
        {"video_id": 1, "group_id": 2},
    ]).on_conflict_do_nothing(index_elements=["video_id", "group_id"])

    sql = _compile_pg(stmt)
    assert "ON CONFLICT (video_id, group_id) DO NOTHING" in sql


def test_group_member_insert_compiles_for_postgres(pg_engine):
    member_t = InternalCreatorGroupMember.__table__
    stmt = db.dialect_insert(member_t).values([
        {"group_id": 1, "username": "alice"},
    ]).on_conflict_do_nothing(
        index_elements=["group_id", "username"],
    ).returning(member_t.c.username)

    sql = _compile_pg(stmt)
    assert "ON CONFLICT (group_id, username) DO NOTHING" in sql
    assert "RETURNING internal_creator_group_members.username" in sql


def test_dialect_insert_picks_sqlite_branch():
    """With the test suite's sqlite engine wired, dialect_insert must return
    the sqlite construct (this is what every functional test runs on)."""

    class _FakeSqliteEngine:
        class dialect:
            name = "sqlite"

    prev = db._engine
    db._engine = _FakeSqliteEngine()
    try:
        from sqlalchemy.dialects.sqlite.dml import Insert as SqliteInsert
        stmt = db.dialect_insert(InternalCreatorGroupMember.__table__)
        assert isinstance(stmt, SqliteInsert)
    finally:
        db._engine = prev
