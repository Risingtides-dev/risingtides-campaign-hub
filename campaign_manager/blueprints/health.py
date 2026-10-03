"""Health check endpoint."""
import os

from flask import Blueprint, jsonify
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
    return jsonify({
        "ok": True,
        "db_active": _db.is_active(),
        "db_url_set": bool(db_url),
        "db_target": _safe_db_target(db_url),
    })
