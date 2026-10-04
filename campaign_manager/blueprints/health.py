"""Health check endpoint."""
import os

from flask import Blueprint, current_app, jsonify
from sqlalchemy.engine import make_url
from campaign_manager import db as _db

health_bp = Blueprint("health", __name__)


def _safe_db_target(db_url: str) -> str:
    """Return the runtime URL's scheme/host without credentials or path/query."""
    if not db_url:
        return ""
    try:
        target = make_url(db_url)
        if db_url.count("@") > 1:
            return "set"
        return f"{target.drivername}://{target.host}" if target.host else (target.drivername or "set")
    except Exception:
        return "set"


@health_bp.get("/health")
def health():
    db_url = os.environ.get("DATABASE_URL", "")
    schema_ok = _db.completion_status_repair_ok()
    if schema_ok:
        # A worker may have skipped scheduler startup while a transient schema
        # repair failed at boot. Reconcile after every recovered health probe.
        from campaign_manager import _maybe_start_scheduler
        _maybe_start_scheduler(current_app._get_current_object())
    response = jsonify({
        "ok": schema_ok,
        "db_active": _db.is_active(),
        "db_url_set": bool(db_url),
        "db_target": _safe_db_target(db_url),
        "schema_repair": "ok" if schema_ok else "failed",
    })
    return response, (200 if schema_ok else 503)
