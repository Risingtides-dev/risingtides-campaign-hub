"""Persistence for Cobrand Sideload — kept self-contained.

Two tables, both registered on the shared SQLAlchemy ``Base`` so the test
suite's ``Base.metadata.create_all`` picks them up automatically:

- ``cobrand_activation_map`` caches the resolved promotion_id -> activation_id
  mapping (avoids a get_promotion call on every sync).
- ``cobrand_sideload_tasks`` is the idempotency/audit ledger: one row per
  (activation_id, url), recording the bulk group handle and per-task outcome.

In production the existing ``campaigns`` table predates these, so rather than
relying on a fresh ``create_all`` we expose :func:`ensure_tables` which the
orchestrator calls (checkfirst) at entry. New tables don't need ALTER TABLE
migrations the way new columns on existing tables do.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from campaign_manager.models import Base


class CobrandActivationMap(Base):
    __tablename__ = "cobrand_activation_map"

    promotion_id = Column(String(100), primary_key=True)
    activation_id = Column(String(100), nullable=False)
    activation_name = Column(String(500), default="")
    campaign_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class CobrandSideloadTask(Base):
    __tablename__ = "cobrand_sideload_tasks"
    __table_args__ = (
        UniqueConstraint("activation_id", "url", name="uq_sideload_activation_url"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Not a hard FK: a matched_videos row can be deleted/re-scraped; the ledger
    # row should survive as an audit record keyed by (activation_id, url).
    matched_video_id = Column(Integer, nullable=True, index=True)

    activation_id = Column(String(100), nullable=False, index=True)
    url = Column(Text, nullable=False)
    group_id = Column(String(100), default="")
    status = Column(String(20), default="PENDING", index=True)
    collaboration_id = Column(String(100), default="")
    submission_id = Column(String(100), default="")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


def ensure_tables(engine) -> None:
    """Create the sideload tables if they don't already exist (idempotent)."""
    if engine is None:
        return
    Base.metadata.create_all(
        engine,
        tables=[CobrandActivationMap.__table__, CobrandSideloadTask.__table__],
        checkfirst=True,
    )
