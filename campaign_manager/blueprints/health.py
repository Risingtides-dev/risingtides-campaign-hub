"""Health check endpoint."""
import os
from urllib.parse import urlsplit

from flask import Blueprint, jsonify
from campaign_manager import db as _db

health_bp = Blueprint("health", __name__)


def _safe_db_target(db_url: str) -> str:
    """Scheme + host only, credentials stripped — safe to expose publicly.

    The old `db_url[:30]` leaked the user and the start of the password
    (e.g. `postgresql://postgres:GQmtAI...`). Never echo credentials.
    """
    if not db_url:
        return ""
    try:
        p = urlsplit(db_url)
        return f"{p.scheme}://{p.hostname}" if p.hostname else (p.scheme or "set")
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
