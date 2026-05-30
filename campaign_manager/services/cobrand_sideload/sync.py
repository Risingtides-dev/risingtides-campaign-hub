"""Sideload orchestrator.

For a hub campaign: resolve the activation, (optionally) validate URLs, bulk
upload the untracked matched links, poll the async group to completion, then
record per-URL SUCCESS/FAILURE into the ledger and mirror the existing
"mark whole campaign tracked" semantics (set ``MatchedVideo.tracked_at`` on
success).

The whole entrypoint is gated by the ``COBRAND_SIDELOAD_ENABLED`` flag and is
dry-run capable. See ``docs/cobrand-sideload.md``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from campaign_manager import db as _db
from campaign_manager.models import Campaign, MatchedVideo
from campaign_manager.utils.helpers import video_posted_before_start

from .client import CobrandSideloadClient
from .config import SideloadConfig
from .models import CobrandActivationMap, CobrandSideloadTask, ensure_tables
from .types import STATUS_FAILURE, STATUS_PENDING, STATUS_SUCCESS


class SideloadDisabledError(RuntimeError):
    """Raised when sideload is invoked while the feature flag is off."""


class ActivationResolutionError(RuntimeError):
    """Raised when a promotion can't be mapped to a single activation."""


@dataclass
class UrlOutcome:
    url: str
    status: str
    matched_video_id: Optional[int] = None
    collaboration_id: str = ""
    submission_id: str = ""
    error: str = ""


@dataclass
class SyncReport:
    slug: str
    promotion_id: str = ""
    activation_id: str = ""
    dry_run: bool = False
    uploaded: int = 0
    skipped_already: int = 0
    succeeded: int = 0
    failed: int = 0
    invalid: int = 0
    outcomes: List[UrlOutcome] = field(default_factory=list)
    message: str = ""


def sync_campaign(
    slug: str,
    *,
    config: Optional[SideloadConfig] = None,
    client: Optional[CobrandSideloadClient] = None,
    dry_run: bool = False,
    tracked_by: str = "cobrand-sideload",
    sleep: Callable[[float], None] = time.sleep,
) -> SyncReport:
    """Sideload one campaign's untracked matched links into co:brand.

    Args:
        slug: campaign slug.
        config: SideloadConfig (defaults to ``from_env()``).
        client: injected CobrandSideloadClient (defaults to one built from config).
        dry_run: resolve activation + build the batch, but do not call the
            write endpoints. No co:brand writes occur.
        tracked_by: audit name stamped on MatchedVideo.tracked_at.
        sleep: injectable sleep for the poll loop (tests pass a no-op).
    """
    config = config or SideloadConfig.from_env()

    if not config.enabled and not dry_run:
        raise SideloadDisabledError(
            "COBRAND_SIDELOAD_ENABLED is not set — refusing to sideload. "
            "Confirm co:brand account/ToS authorization before enabling."
        )
    if not _db.is_active():
        raise RuntimeError("Sideload requires Postgres (DB) mode.")

    ensure_tables(_db._engine)

    report = SyncReport(slug=slug, dry_run=dry_run)
    client = client or CobrandSideloadClient(config)

    # 1) Load campaign + 2) build the untracked batch (mirrors the Scrape
    #    Tasks queue filters, incl. CAMP-42 pre-start-date exclusion).
    with _db.get_session() as s:
        camp = s.query(Campaign).filter_by(slug=slug).first()
        if not camp:
            report.message = "campaign not found"
            return report
        report.promotion_id = camp.cobrand_promotion_id or ""
        if not report.promotion_id:
            report.message = "campaign has no cobrand_promotion_id"
            return report

        rows = (
            s.query(MatchedVideo)
            .filter(MatchedVideo.campaign_id == camp.id)
            .filter(MatchedVideo.tracked_at.is_(None))
            .filter(MatchedVideo.dismissed_at.is_(None))
            .all()
        )
        start = camp.start_date or ""
        batch: List[Dict] = []
        for mv in rows:
            if video_posted_before_start(
                {"timestamp": mv.timestamp or "", "upload_date": mv.upload_date or ""},
                start,
            ):
                continue
            if mv.url:
                batch.append({"id": mv.id, "url": mv.url})

        camp_artist = camp.artist or ""
        camp_title = camp.title or camp.name or ""
        camp_id = camp.id

    # 3) Resolve activation_id (cache -> get_promotion).
    activation_id = _resolve_activation(
        client, report.promotion_id, camp_artist, camp_title, camp_id
    )
    report.activation_id = activation_id

    if not batch:
        report.message = "no untracked videos"
        return report

    # 4) Idempotency: drop URLs already pushed (non-FAILURE) for this activation.
    url_to_mv: Dict[str, int] = {b["url"]: b["id"] for b in batch}
    urls = list(url_to_mv.keys())
    already = _already_pushed_urls(activation_id, urls)
    report.skipped_already = len(already)
    pending_urls = [u for u in urls if u not in already]

    if not pending_urls:
        report.message = "all urls already pushed"
        return report

    # 5) Optional validation (shape unconfirmed; off by default).
    if config.validate_urls and not dry_run:
        valid: List[str] = []
        for u in pending_urls:
            try:
                res = client.validate_live_post_url(u)
            except Exception:  # noqa: BLE001 - validation is best-effort
                res = None
            ok = bool(res is None or res.get("valid", True))
            if ok:
                valid.append(u)
            else:
                report.invalid += 1
                report.outcomes.append(
                    UrlOutcome(url=u, status=STATUS_FAILURE,
                               matched_video_id=url_to_mv.get(u),
                               error="failed validation")
                )
        pending_urls = valid

    if not pending_urls:
        report.message = "no urls passed validation"
        return report

    if dry_run:
        report.message = f"dry-run: would upload {len(pending_urls)} urls"
        for u in pending_urls:
            report.outcomes.append(
                UrlOutcome(url=u, status=STATUS_PENDING, matched_video_id=url_to_mv.get(u))
            )
        return report

    # 6) Bulk upload -> group handle. Record PENDING ledger rows.
    group_id = client.bulk_upload(activation_id, pending_urls)
    report.uploaded = len(pending_urls)
    _record_pending(activation_id, group_id, camp_id, pending_urls, url_to_mv)

    # 7) Poll the async group until pending_count == 0.
    group = _poll_group(client, activation_id, group_id, config, sleep)
    if group is None:
        report.message = "bulk group not found after upload"
        return report
    if group.pending_count != 0:
        report.message = "poll timed out; tasks still pending"
        return report

    # 8) Record per-task outcomes; mark successes tracked.
    now = datetime.now()
    with _db.get_session() as s:
        for task in group.tasks:
            mvid = url_to_mv.get(task.url)
            row = (
                s.query(CobrandSideloadTask)
                .filter_by(activation_id=activation_id, url=task.url)
                .first()
            )
            if row is None:
                row = CobrandSideloadTask(
                    activation_id=activation_id, url=task.url,
                    campaign_id=camp_id, matched_video_id=mvid, group_id=group_id,
                )
                s.add(row)
            row.status = task.status
            row.group_id = group_id
            row.collaboration_id = task.collaboration_id or ""
            row.submission_id = task.submission_id or ""

            if task.status == STATUS_SUCCESS:
                report.succeeded += 1
                if mvid is not None:
                    mv = s.query(MatchedVideo).filter_by(id=mvid).first()
                    if mv is not None and mv.tracked_at is None:
                        mv.tracked_at = now
                        mv.tracked_by = tracked_by
            elif task.status == STATUS_FAILURE:
                report.failed += 1

            report.outcomes.append(
                UrlOutcome(
                    url=task.url, status=task.status, matched_video_id=mvid,
                    collaboration_id=task.collaboration_id or "",
                    submission_id=task.submission_id or "",
                )
            )
        s.commit()

    report.message = "ok"
    return report


# --- helpers --------------------------------------------------------------


def _resolve_activation(
    client: CobrandSideloadClient,
    promotion_id: str,
    artist: str,
    title: str,
    campaign_id: Optional[int],
) -> str:
    # Cache hit?
    with _db.get_session() as s:
        cached = s.query(CobrandActivationMap).filter_by(promotion_id=promotion_id).first()
        if cached and cached.activation_id:
            return cached.activation_id

    promo = client.get_promotion(promotion_id)
    acts = promo.activations
    if not acts:
        raise ActivationResolutionError(f"promotion {promotion_id} has no activations")

    if len(acts) == 1:
        chosen = acts[0]
    else:
        chosen = _disambiguate(acts, artist, title)
        if chosen is None:
            raise ActivationResolutionError(
                f"promotion {promotion_id} has {len(acts)} activations and none "
                f"uniquely matched artist={artist!r} / title={title!r}"
            )

    now = datetime.now()
    with _db.get_session() as s:
        row = s.query(CobrandActivationMap).filter_by(promotion_id=promotion_id).first()
        if row is None:
            row = CobrandActivationMap(promotion_id=promotion_id)
            s.add(row)
        row.activation_id = chosen.id
        row.activation_name = chosen.name or ""
        row.campaign_id = campaign_id
        row.updated_at = now
        s.commit()
    return chosen.id


def _disambiguate(acts, artist: str, title: str):
    artist_l = (artist or "").strip().lower()
    if artist_l:
        cands = [a for a in acts if (a.artist_name or "").strip().lower() == artist_l]
        if len(cands) == 1:
            return cands[0]
    title_l = (title or "").strip().lower()
    if title_l:
        cands = [a for a in acts if title_l in (a.name or "").strip().lower()]
        if len(cands) == 1:
            return cands[0]
    return None


def _already_pushed_urls(activation_id: str, urls: List[str]) -> set:
    if not urls:
        return set()
    pushed = set()
    with _db.get_session() as s:
        rows = (
            s.query(CobrandSideloadTask)
            .filter(CobrandSideloadTask.activation_id == activation_id)
            .filter(CobrandSideloadTask.url.in_(urls))
            .all()
        )
        for r in rows:
            if r.status != STATUS_FAILURE:
                pushed.add(r.url)
    return pushed


def _record_pending(
    activation_id: str,
    group_id: str,
    campaign_id: Optional[int],
    urls: List[str],
    url_to_mv: Dict[str, int],
) -> None:
    with _db.get_session() as s:
        for u in urls:
            row = (
                s.query(CobrandSideloadTask)
                .filter_by(activation_id=activation_id, url=u)
                .first()
            )
            if row is None:
                row = CobrandSideloadTask(activation_id=activation_id, url=u)
                s.add(row)
            row.campaign_id = campaign_id
            row.matched_video_id = url_to_mv.get(u)
            row.group_id = group_id
            row.status = STATUS_PENDING
            row.error = ""
        s.commit()


def _poll_group(client, activation_id, group_id, config, sleep):
    group = None
    for attempt in range(config.poll_max_attempts):
        groups = client.list_bulk_create_groups(activation_id, limit=99, offset=0)
        group = next((g for g in groups if g.id == group_id), None)
        if group is not None and group.pending_count == 0:
            return group
        sleep(config.poll_interval_seconds * (config.poll_backoff ** attempt))
    return group
