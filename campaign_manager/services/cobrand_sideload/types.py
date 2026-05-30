"""Typed mirrors of the co:brand API request/response shapes.

These mirror the reverse-engineered TypeScript interfaces in
``docs/cobrand-sideload.md`` (§3.5). All IDs are UUIDv7-style strings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Task status values returned by the bulk-create poll endpoint.
STATUS_PENDING = "PENDING"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"


@dataclass
class Activation:
    id: str
    name: str = ""
    artist_id: str = ""
    artist_name: str = ""

    @classmethod
    def from_api(cls, d: dict) -> "Activation":
        artist = d.get("artist") or {}
        if not isinstance(artist, dict):
            artist = {}
        return cls(
            id=d.get("id", "") or "",
            name=d.get("name", "") or "",
            artist_id=artist.get("id", "") or "",
            artist_name=artist.get("name", "") or "",
        )


@dataclass
class GetPromotionResponse:
    id: str
    name: str = ""
    status: str = ""
    activations: List[Activation] = field(default_factory=list)

    @classmethod
    def from_api(cls, d: dict) -> "GetPromotionResponse":
        return cls(
            id=d.get("id", "") or "",
            name=d.get("name", "") or "",
            status=d.get("status", "") or "",
            activations=[Activation.from_api(a) for a in (d.get("activations") or [])],
        )


@dataclass
class Task:
    id: str
    url: str = ""
    status: str = STATUS_PENDING
    collaboration_id: Optional[str] = None
    submission_id: Optional[str] = None

    @classmethod
    def from_api(cls, d: dict) -> "Task":
        return cls(
            id=d.get("id", "") or "",
            url=d.get("url", "") or "",
            status=d.get("status", STATUS_PENDING) or STATUS_PENDING,
            collaboration_id=d.get("collaboration_id"),
            submission_id=d.get("submission_id"),
        )


@dataclass
class BulkCreateGroup:
    id: str
    activation_id: str = ""
    total_count: int = 0
    pending_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    tasks: List[Task] = field(default_factory=list)

    @classmethod
    def from_api(cls, d: dict) -> "BulkCreateGroup":
        return cls(
            id=d.get("id", "") or "",
            activation_id=d.get("activation_id", "") or "",
            total_count=int(d.get("total_count", 0) or 0),
            pending_count=int(d.get("pending_count", 0) or 0),
            success_count=int(d.get("success_count", 0) or 0),
            failure_count=int(d.get("failure_count", 0) or 0),
            tasks=[Task.from_api(t) for t in (d.get("tasks") or [])],
        )
