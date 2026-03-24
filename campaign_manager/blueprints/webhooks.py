"""Webhook endpoints for external integrations."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from campaign_manager import db as _db
from campaign_manager.utils.helpers import slugify, extract_sound_id

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")


@webhooks_bp.post("/slack/sounds")
def slack_active_sounds():
    """Post active campaign TikTok sound URLs to the #campaign-sounds Slack channel.

    Can be triggered manually via API call or wired into the daily scheduler.
    Uses the existing Slack bot to post — no additional Slack app setup needed.
    """
    import os
    from campaign_manager.services.slack_sounds import post_sounds_to_slack

    if not _db.is_active():
        return jsonify({"error": "Database not configured"}), 500

    channel = os.environ.get("SLACK_SOUNDS_CHANNEL", "")
    if not channel:
        return jsonify({"error": "SLACK_SOUNDS_CHANNEL not configured"}), 500

    result = post_sounds_to_slack(channel)
    return jsonify(result)


@webhooks_bp.post("/notion")
def notion_webhook():
    """Accept a campaign payload from Notion (via n8n, Make.com, or manual trigger).

    This endpoint receives pre-extracted campaign data and creates a new campaign.
    The caller is responsible for extracting fields from Notion's API format.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    artist = (data.get("artist") or "").strip()
    song = (data.get("song") or "").strip()

    # Build title and slug
    title = data.get("title", "")
    if not title:
        if artist and song:
            title = f"{artist} - {song}"
        elif artist:
            title = artist
        elif song:
            title = song
        else:
            return jsonify({"error": "At least artist or song is required"}), 400

    slug = data.get("slug") or slugify(title)

    if _db.is_active():
        if _db.campaign_exists(slug):
            return jsonify({"error": f"Campaign '{slug}' already exists", "slug": slug}), 409
    else:
        return jsonify({"error": "Database not configured"}), 500

    # Extract sound ID from TikTok sound link if provided
    tiktok_sound = (data.get("tiktok_sound_link") or "").strip()
    sound_id = data.get("sound_id", "")
    if tiktok_sound and not sound_id:
        sound_id = extract_sound_id(tiktok_sound)

    meta = {
        "title": title,
        "name": title,
        "slug": slug,
        "artist": artist,
        "song": song,
        "official_sound": tiktok_sound,
        "sound_id": sound_id,
        "start_date": data.get("start_date", ""),
        "budget": float(data.get("budget", 0) or 0),
        "status": "queued",
        "platform": "tiktok",
        "created_at": datetime.now().isoformat(),
        "stats": {"total_views": 0, "total_likes": 0},
        # Extended fields from Notion CRM
        "source": "notion",
        "notion_page_id": data.get("notion_page_id", ""),
        "insta_sound": (data.get("insta_sound_link") or "").strip(),
        "cobrand_share_url": (data.get("cobrand_link") or "").strip(),
        "campaign_stage": data.get("campaign_stage", ""),
        "round": data.get("round", ""),
        "label": data.get("label", ""),
        "project_lead": data.get("project_lead", []),
        "client_email": data.get("client_email", ""),
        "content_types": data.get("content_types", []),
        "platform_split": data.get("platform_split", {}),
    }

    _db.save_campaign(slug, meta)
    _db.save_creators(slug, [])

    return jsonify({
        "ok": True,
        "slug": slug,
        "title": title,
        "message": f"Campaign '{title}' created from Notion",
    }), 201


@webhooks_bp.post("/notion/sync")
def notion_sync():
    """Manual trigger: poll Notion CRM for new Client entries and create campaigns.

    Queries the Notion CRM database for entries with Pipeline Status = "Client"
    that haven't been synced yet, and creates campaigns for each one.
    """
    if not _db.is_active():
        return jsonify({"error": "Database not configured"}), 500

    from campaign_manager.services.notion import query_new_clients

    synced_ids = _db.get_synced_notion_ids()
    new_entries = query_new_clients(synced_ids)

    if not new_entries:
        return jsonify({
            "ok": True,
            "created": [],
            "skipped": [],
            "message": "No new campaigns to sync from Notion",
        })

    created = []
    skipped = []

    for entry in new_entries:
        slug = entry["slug"]

        if _db.campaign_exists(slug):
            skipped.append({"slug": slug, "reason": "already exists"})
            continue

        meta = {
            "title": entry["title"],
            "name": entry["title"],
            "slug": slug,
            "artist": entry["artist"],
            "song": entry["song"],
            "official_sound": entry["official_sound"],
            "sound_id": entry["sound_id"],
            "start_date": entry["start_date"],
            "budget": entry["budget"],
            "status": "queued",
            "platform": "tiktok",
            "created_at": datetime.now().isoformat(),
            "stats": {"total_views": 0, "total_likes": 0},
            # Extended fields
            "source": "notion",
            "notion_page_id": entry["notion_page_id"],
            "insta_sound": entry.get("insta_sound", ""),
            "cobrand_share_url": entry.get("cobrand_share_url", ""),
            "campaign_stage": entry.get("campaign_stage", ""),
            "round": entry.get("round", ""),
            "label": entry.get("label", ""),
            "project_lead": entry.get("project_lead", []),
            "client_email": entry.get("client_email", ""),
            "content_types": entry.get("content_types", []),
            "platform_split": entry.get("platform_split", {}),
        }

        _db.save_campaign(slug, meta)
        _db.save_creators(slug, [])
        created.append({"slug": slug, "title": entry["title"]})

    return jsonify({
        "ok": True,
        "created": created,
        "skipped": skipped,
        "message": f"Synced {len(created)} new campaign(s) from Notion"
            + (f", {len(skipped)} skipped" if skipped else ""),
    })
