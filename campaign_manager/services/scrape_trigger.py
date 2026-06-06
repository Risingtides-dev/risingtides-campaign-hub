"""On-demand external-campaign scrape trigger (CAMP-24).

Exposes the scheduler's run_campaign_refresh() as a fire-and-poll job so the
Scrape Tasks UI can trigger a scrape (single campaign or all active) instead
of waiting for the daily cron.

Design mirrors the internal-scrape job registry in blueprints/internal.py:
in-process job dict + lock + TTL cleanup. The heavy lifting (bounded-concurrency
yt-dlp scrape, dedup, matching, stats) is ALL reused from
services/scheduler.run_campaign_refresh — this module only adds the
job lifecycle around it.

Concurrency: run_campaign_refresh already dedupes creators across campaigns and
scrapes them through one bounded ThreadPoolExecutor (DEFAULT_MAX_WORKERS), so
the "don't fan out 145 parallel processes" rule (CAMP-24) is satisfied by reuse
— we do NOT spawn a process per campaign. We additionally guard against TWO
overlapping trigger jobs running at once (single global lock).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_JOB_TTL_SECS = 6 * 3600  # keep finished jobs visible for 6h


def _prune_locked() -> None:
    """Drop finished jobs older than the TTL. Caller holds _jobs_lock."""
    now = time.monotonic()
    stale = [
        jid for jid, j in _jobs.items()
        if j.get("state") in ("done", "error")
        and (now - j.get("_ended_mono", now)) > _JOB_TTL_SECS
    ]
    for jid in stale:
        _jobs.pop(jid, None)


def active_job() -> Optional[Dict[str, Any]]:
    """Return the currently-running trigger job, if any (for debounce)."""
    with _jobs_lock:
        for jid, j in _jobs.items():
            if j.get("state") == "running":
                return {"job_id": jid, **{k: v for k, v in j.items() if not k.startswith("_")}}
    return None


def start_scrape(only_slugs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Kick a campaign refresh in a background thread. Returns the job stub.

    only_slugs=None -> all active campaigns. A list -> just those slugs.
    Debounced: if a trigger job is already running, returns it instead of
    starting a second (overlapping scrapes would double the scraper load).
    """
    existing = active_job()
    if existing:
        return {**existing, "already_running": True}

    job_id = uuid.uuid4().hex[:12]
    scope = "all_active" if not only_slugs else f"{len(only_slugs)} campaign(s)"
    with _jobs_lock:
        _prune_locked()
        _jobs[job_id] = {
            "state": "running",
            "scope": scope,
            "only_slugs": list(only_slugs) if only_slugs else None,
            "started_at": _now_iso(),
            "result": None,
            "error": None,
            "_started_mono": time.monotonic(),
        }

    t = threading.Thread(target=_run, args=(job_id, only_slugs), daemon=True)
    t.start()
    return {"job_id": job_id, "state": "running", "scope": scope, "started_at": _jobs[job_id]["started_at"]}


def _run(job_id: str, only_slugs: Optional[List[str]]) -> None:
    try:
        from campaign_manager.services.scheduler import run_campaign_refresh
        result = run_campaign_refresh(only_slugs=only_slugs)
        with _jobs_lock:
            j = _jobs.get(job_id)
            if j is not None:
                j["state"] = "done"
                j["result"] = result
                j["ended_at"] = _now_iso()
                j["_ended_mono"] = time.monotonic()
    except Exception as e:  # noqa: BLE001 — surface any scrape failure as job error
        log.exception("scrape trigger job %s failed", job_id)
        with _jobs_lock:
            j = _jobs.get(job_id)
            if j is not None:
                j["state"] = "error"
                j["error"] = str(e)
                j["ended_at"] = _now_iso()
                j["_ended_mono"] = time.monotonic()


def job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Public status for one job (no internal _-prefixed fields)."""
    with _jobs_lock:
        j = _jobs.get(job_id)
        if j is None:
            return None
        return {"job_id": job_id, **{k: v for k, v in j.items() if not k.startswith("_")}}


def _now_iso() -> str:
    # Local import so a future move off datetime.now is contained.
    from datetime import datetime
    return datetime.now().isoformat()
