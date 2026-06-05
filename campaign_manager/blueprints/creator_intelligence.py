"""Creator Intelligence API — sound-breaking leaderboard + per-creator drilldown.

Endpoints:
  GET /api/intelligence/breakers?lens=balanced&limit=100&min_posts=5
  GET /api/intelligence/creator/<account>
"""
from flask import Blueprint, jsonify, request

from campaign_manager import db as _db
from campaign_manager.services.creator_intelligence import (
    breaker_leaderboard,
    creator_drilldown,
)

creator_intelligence_bp = Blueprint("creator_intelligence", __name__)

VALID_LENSES = {"ceiling", "volume", "balanced"}


@creator_intelligence_bp.get("/api/intelligence/breakers")
def get_breakers():
    """Sound-breaking leaderboard, ranked by the chosen lens.

    Query params:
      - lens: ceiling | volume | balanced (default balanced)
      - limit: max rows (default 100)
      - min_posts: min tracked posts to qualify (default 5)
    """
    lens = request.args.get("lens", "balanced")
    if lens not in VALID_LENSES:
        lens = "balanced"
    limit = request.args.get("limit", 100, type=int)
    min_posts = request.args.get("min_posts", 5, type=int)

    session = _db.get_session()
    try:
        rows = breaker_leaderboard(session, lens=lens, limit=limit, min_posts=min_posts)
        return jsonify({
            "lens": lens,
            "count": len(rows),
            "min_posts": min_posts,
            "breakers": rows,
        })
    finally:
        session.close()


@creator_intelligence_bp.get("/api/intelligence/creator/<path:account>")
def get_creator(account: str):
    """Full sound-breaking drilldown for one creator.

    Query params:
      - outcomes: "1" to enrich with Cobrand per-creator outcome data
        (shares/comments — slower, opt-in)
    """
    with_outcomes = request.args.get("outcomes") == "1"
    session = _db.get_session()
    try:
        data = creator_drilldown(session, account, with_outcomes=with_outcomes)
        if data is None:
            return jsonify({"error": "creator not found or has no tracked posts"}), 404
        return jsonify(data)
    finally:
        session.close()
