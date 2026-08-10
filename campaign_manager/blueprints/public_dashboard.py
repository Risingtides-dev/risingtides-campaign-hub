"""Public dashboard API endpoints.

Token-based, no-auth endpoints for client-facing campaign dashboards,
plus internal token management endpoints.
"""
from __future__ import annotations

import csv
import io
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request, Response

from campaign_manager import db as _db

public_dashboard_bp = Blueprint("public_dashboard", __name__)


# ---------------------------------------------------------------------------
# Helper: build public dashboard payload (NO budget/rate/payment/CPV data)
# ---------------------------------------------------------------------------

def _build_dashboard_data(
    campaign_meta: Dict,
    creators: List[Dict],
    videos: List[Dict],
    stats_history: List[Dict],
    round_filter: str = "",
) -> Dict:
    """Assemble the public-safe dashboard JSON from raw campaign data."""

    # Filter by round if specified
    if round_filter:
        videos = [v for v in videos if v.get("round", "") == round_filter]

    # Aggregate stats from matched videos
    total_views = sum(v.get("views", 0) for v in videos)
    total_likes = sum(v.get("likes", 0) for v in videos)
    total_shares = sum(v.get("shares", 0) for v in videos)
    total_comments = sum(v.get("comments", 0) for v in videos)

    engagement_total = total_likes + total_comments + total_shares
    engagement_pct = round((engagement_total / total_views * 100), 2) if total_views > 0 else 0.0

    # Build public creator list (no rates, payment, paypal)
    public_creators = []
    for cr in creators:
        creator_videos = [v for v in videos if v.get("account", "") == cr.get("username", "")]
        public_creators.append({
            "username": cr.get("username", ""),
            "profile_pic_url": cr.get("profile_pic_url", ""),
            "posts_done": cr.get("posts_done", 0),
            "total_views": sum(v.get("views", 0) for v in creator_videos),
        })

    # Build public posts list
    public_posts = []
    for v in videos:
        public_posts.append({
            "url": v.get("url", ""),
            "thumbnail_url": v.get("thumbnail_url", ""),
            "account": v.get("account", ""),
            "views": v.get("views", 0),
            "likes": v.get("likes", 0),
            "shares": v.get("shares", 0),
            "comments": v.get("comments", 0),
            "upload_date": v.get("upload_date", ""),
            "platform": v.get("platform", "tiktok"),
            "round": campaign_meta.get("round", ""),
        })

    # Collect unique rounds
    rounds = sorted(set(
        v.get("round", "") for v in public_posts if v.get("round", "")
    ))
    if not rounds and campaign_meta.get("round"):
        rounds = [campaign_meta["round"]]

    # Stats history for the chart
    formatted_history = []
    for snap in stats_history:
        formatted_history.append({
            "date": snap.get("snapshot_date", ""),
            "views": snap.get("total_views", 0),
            "likes": snap.get("total_likes", 0),
            "posts": snap.get("post_count", 0),
        })

    return {
        "title": campaign_meta.get("title", ""),
        "artist": campaign_meta.get("artist", ""),
        "song": campaign_meta.get("song", ""),
        "created_at": campaign_meta.get("created_at", ""),
        "rounds": rounds,
        "stats": {
            "total_views": total_views,
            "total_likes": total_likes,
            "total_shares": total_shares,
            "total_comments": total_comments,
            "engagement_pct": engagement_pct,
            "live_post_count": len(videos),
        },
        "creators": public_creators,
        "posts": public_posts,
        "stats_history": formatted_history,
    }


def _build_csv(posts: List[Dict]) -> str:
    """Build CSV string from public posts."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Post URL", "Creator", "Views", "Likes", "Shares", "Comments", "Date", "Platform"])
    for p in posts:
        writer.writerow([
            p.get("url", ""),
            p.get("account", ""),
            p.get("views", 0),
            p.get("likes", 0),
            p.get("shares", 0),
            p.get("comments", 0),
            p.get("upload_date", ""),
            p.get("platform", ""),
        ])
    return output.getvalue()


# ---------------------------------------------------------------------------
# Public endpoints (no auth, token-based)
# ---------------------------------------------------------------------------

@public_dashboard_bp.route("/api/public/dashboard/<token>", methods=["GET"])
def get_public_dashboard(token: str):
    """Main public dashboard data endpoint."""
    token_data = _db.get_share_token(token)
    if not token_data:
        return jsonify({"error": "Invalid or expired share link"}), 404

    _db.record_token_access(token)

    campaign_id = token_data.get("campaign_id")
    campaign_slugs = token_data.get("campaign_slugs", [])
    round_filter = token_data.get("round_filter", "")

    # Determine which campaign(s) to fetch
    if campaign_id:
        # Single campaign mode: look up slug from campaign_id
        slug = _resolve_slug_from_id(campaign_id)
        if not slug:
            return jsonify({"error": "Campaign not found"}), 404
        slugs = [slug]
    elif campaign_slugs:
        slugs = campaign_slugs
    else:
        return jsonify({"error": "Token has no associated campaign"}), 400

    # For now, support single campaign (first slug)
    # Multi-campaign aggregation can be added later
    slug = slugs[0]
    campaign_meta = _db.get_campaign(slug)
    if not campaign_meta:
        return jsonify({"error": "Campaign not found"}), 404

    creators = _db.get_creators(slug)
    videos = _db.get_matched_videos(slug)

    cid = _db.get_campaign_id(slug)
    stats_history = _db.get_stats_history(cid, days=90) if cid else []

    data = _build_dashboard_data(campaign_meta, creators, videos, stats_history, round_filter)
    return jsonify(data)


@public_dashboard_bp.route("/api/public/dashboard/<token>/csv", methods=["GET"])
def download_csv(token: str):
    """CSV download for public dashboard."""
    token_data = _db.get_share_token(token)
    if not token_data:
        return jsonify({"error": "Invalid or expired share link"}), 404

    _db.record_token_access(token)

    campaign_id = token_data.get("campaign_id")
    campaign_slugs = token_data.get("campaign_slugs", [])
    round_filter = token_data.get("round_filter", "")

    if campaign_id:
        slug = _resolve_slug_from_id(campaign_id)
        if not slug:
            return jsonify({"error": "Campaign not found"}), 404
    elif campaign_slugs:
        slug = campaign_slugs[0]
    else:
        return jsonify({"error": "Token has no associated campaign"}), 400

    campaign_meta = _db.get_campaign(slug)
    if not campaign_meta:
        return jsonify({"error": "Campaign not found"}), 404

    videos = _db.get_matched_videos(slug)
    if round_filter:
        videos = [v for v in videos if v.get("round", "") == round_filter]

    # Build public posts for CSV
    posts = []
    for v in videos:
        posts.append({
            "url": v.get("url", ""),
            "account": v.get("account", ""),
            "views": v.get("views", 0),
            "likes": v.get("likes", 0),
            "shares": v.get("shares", 0),
            "comments": v.get("comments", 0),
            "upload_date": v.get("upload_date", ""),
            "platform": v.get("platform", "tiktok"),
        })

    csv_content = _build_csv(posts)
    title = campaign_meta.get("title", "campaign")
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "" for c in title).strip().replace(" ", "_")

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}_analytics.csv"',
        },
    )


# ---------------------------------------------------------------------------
# Internal token management endpoints
# ---------------------------------------------------------------------------

@public_dashboard_bp.route("/api/campaign/<slug>/share-token", methods=["POST"])
def create_share_token(slug: str):
    """Generate a new share token for a campaign."""
    campaign_id = _db.get_campaign_id(slug)
    if not campaign_id:
        return jsonify({"error": "Campaign not found"}), 404

    body = request.get_json(silent=True) or {}
    label = body.get("label", "")
    expires_days = body.get("expires_days")

    token_str = secrets.token_urlsafe(32)
    expires_at = None
    if expires_days:
        expires_at = datetime.now() + timedelta(days=int(expires_days))

    token_data = _db.create_share_token(
        campaign_id=campaign_id,
        token=token_str,
        label=label,
        campaign_slugs=[slug],
        expires_at=expires_at,
    )

    # Build the shareable URL
    # Use request.host_url or the known frontend URL
    base_url = request.headers.get("Origin", request.host_url.rstrip("/"))
    share_url = f"{base_url}/share/{token_str}"

    return jsonify({"ok": True, "token": token_data, "url": share_url})


@public_dashboard_bp.route("/api/share-tokens", methods=["GET"])
def list_share_tokens():
    """List all share tokens."""
    tokens = _db.list_share_tokens()
    return jsonify(tokens)


@public_dashboard_bp.route("/api/share-token/<token_str>", methods=["DELETE"])
def revoke_share_token(token_str: str):
    """Revoke a share token."""
    revoked = _db.revoke_share_token(token_str)
    if not revoked:
        return jsonify({"error": "Token not found"}), 404
    return jsonify({"ok": True, "message": "Token revoked"})


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _resolve_slug_from_id(campaign_id: int) -> Optional[str]:
    """Look up campaign slug from campaign_id."""
    from campaign_manager.models import Campaign
    with _db.get_session() as s:
        c = s.query(Campaign).filter_by(id=campaign_id).first()
        return c.slug if c else None
