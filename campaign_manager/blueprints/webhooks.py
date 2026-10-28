"""Webhook endpoints for external integrations."""
import re
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


# ── Shared campaign intake ─────────────────────────────────────────────
#
# Both the webhook (/notion) and the sync (/notion/sync) endpoints funnel
# through the one function below so repeat bookings behave identically on
# every path. A repeat booking is keyed by notion_page_id, not by the title
# slug: a second CRM page whose title slugs to an existing campaign becomes a
# new round-suffixed campaign instead of being skipped or 409'd.

def _round_number(round_value) -> int | None:
    """Round N from a CRM round value like 'Round 2' (None when unset)."""
    match = re.search(r"\d+", str(round_value or ""))
    return int(match.group()) if match else None


def _existing_round_siblings(base_slug: str) -> int:
    """Campaigns that are this title's rounds: base or base_round_<digits>."""
    prefix = f"{base_slug}_round_"
    count = 0
    for slug in _db.get_campaign_slugs():
        if slug == base_slug:
            count += 1
        elif slug.startswith(prefix) and slug[len(prefix):].isdigit():
            count += 1
    return count


def _resolve_round_slug(base_slug: str, round_value) -> str:
    """Round-suffixed slug for a repeat booking, never colliding.

    An explicit CRM round ('Round 2') picks its number; otherwise the next
    free number after the existing rounds (existing count + 1). If that
    suffix is already taken, keep incrementing so intake never 409s.
    """
    number = _round_number(round_value)
    if not number or number < 2:
        number = _existing_round_siblings(base_slug) + 1
    while _db.campaign_exists(f"{base_slug}_round_{number}"):
        number += 1
    return f"{base_slug}_round_{number}"


def _build_campaign_meta(slug: str, entry: dict) -> dict:
    """Campaign meta dict for save_campaign, from a normalized intake entry."""
    return {
        "title": entry["title"],
        "name": entry["title"],
        "slug": slug,
        "artist": entry.get("artist", ""),
        "song": entry.get("song", ""),
        "official_sound": entry.get("official_sound", ""),
        "sound_id": entry.get("sound_id", ""),
        "start_date": entry.get("start_date", ""),
        "budget": float(entry.get("budget", 0) or 0),
        "status": "queued",
        "platform": "tiktok",
        "created_at": datetime.now().isoformat(),
        "stats": {"total_views": 0, "total_likes": 0},
        "source": "notion",
        "notion_page_id": entry.get("notion_page_id", ""),
        "insta_sound": entry.get("insta_sound", ""),
        "cobrand_share_url": entry.get("cobrand_share_url", ""),
        "campaign_stage": entry.get("campaign_stage", ""),
        "round": entry.get("round", ""),
        "label": entry.get("label", ""),
        "project_lead": entry.get("project_lead", []),
        "client_email": entry.get("client_email", ""),
        "content_types": entry.get("content_types", []),
        "internal_captions": entry.get("internal_captions"),
        "platform_split": entry.get("platform_split", {}),
    }


def _intake_campaign(entry: dict) -> dict:
    """Create (or idempotently skip) one campaign from a normalized entry.

    Returns a result dict with ``status`` in:
      created | existing | conflict | skipped | error

    ``entry`` uses the same keys as ``services.notion.query_new_clients``
    rows: notion_page_id, title, slug, artist, song, official_sound,
    sound_id, start_date, budget, round, and the extended CRM fields.
    """
    page_id = (entry.get("notion_page_id") or "").strip()
    base_slug = (entry.get("slug") or "").strip() or slugify(entry.get("title") or "")

    # Idempotency: the same CRM page is one campaign no matter how often it
    # arrives (re-sync, or a webhook racing the sync). Never overwrite the
    # existing row — operator-edited Hub fields stay untouched.
    if page_id:
        existing = _db.get_campaign_by_notion_page_id(page_id)
        if existing:
            return {"status": "existing", "slug": existing["slug"]}

    slug = base_slug
    if _db.campaign_exists(slug):
        # Without a CRM page id we cannot tell a repeat booking from a plain
        # duplicate, so keep the old slug-uniqueness refusal.
        if not page_id:
            return {"status": "conflict", "slug": slug}
        # A different CRM page with the same title is a repeat booking.
        slug = _resolve_round_slug(slug, entry.get("round"))

    meta = _build_campaign_meta(slug, entry)
    sound_url = _db._canonical_sound_url(meta["official_sound"])
    result = _db.save_campaign(
        slug, meta,
        expected_official_sound="" if sound_url is not None else None,
        allow_round_sibling_sound=True,
    )
    if result not in (None, "updated"):
        if result == "duplicate":
            return {"status": "skipped", "slug": slug, "reason": "duplicate sound URL"}
        if result in ("conflict", "missing_revision"):
            return {"status": "skipped", "slug": slug, "reason": "campaign changed during creation"}
        return {"status": "error", "slug": slug, "reason": "campaign save failed"}
    _db.save_creators(slug, [])
    return {"status": "created", "slug": slug}


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

    # Build title
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

    if not _db.is_active():
        return jsonify({"error": "Database not configured"}), 500

    # Extract sound ID from TikTok sound link if provided
    tiktok_sound = (data.get("tiktok_sound_link") or "").strip()
    sound_id = data.get("sound_id", "")
    if tiktok_sound and not sound_id:
        sound_id = extract_sound_id(tiktok_sound)

    entry = {
        "notion_page_id": data.get("notion_page_id", ""),
        "title": title,
        "slug": data.get("slug") or slugify(title),
        "artist": artist,
        "song": song,
        "official_sound": tiktok_sound,
        "sound_id": sound_id,
        "start_date": data.get("start_date", ""),
        "budget": float(data.get("budget", 0) or 0),
        "insta_sound": (data.get("insta_sound_link") or "").strip(),
        "cobrand_share_url": (data.get("cobrand_link") or "").strip(),
        "campaign_stage": data.get("campaign_stage", ""),
        "round": data.get("round", ""),
        "label": data.get("label", ""),
        "project_lead": data.get("project_lead", []),
        "client_email": data.get("client_email", ""),
        "content_types": data.get("content_types", []),
        "internal_captions": data["internal_captions"]
            if isinstance(data.get("internal_captions"), str) else None,
        "platform_split": data.get("platform_split", {}),
    }

    result = _intake_campaign(entry)
    slug = result["slug"]

    if result["status"] == "created":
        return jsonify({
            "ok": True,
            "slug": slug,
            "title": title,
            "message": f"Campaign '{title}' created from Notion",
        }), 201
    if result["status"] == "existing":
        return jsonify({
            "ok": True,
            "slug": slug,
            "title": title,
            "message": f"Campaign '{title}' already synced from Notion",
        }), 200
    if result["status"] == "conflict":
        return jsonify({"error": f"Campaign '{slug}' already exists", "slug": slug}), 409
    if result["status"] == "skipped":
        if result.get("reason") == "duplicate sound URL":
            return jsonify({"error": "That link already belongs to another campaign", "slug": slug,
                            "code": "duplicate"}), 409
        return jsonify({"error": "Campaign changed while it was being created; retry the sync", "slug": slug,
                        "code": "conflict"}), 409
    return jsonify({"error": "Campaign could not be saved", "slug": slug,
                    "code": "save_failed"}), 500


@webhooks_bp.post("/notion/sync")
def notion_sync():
    """Manual trigger: poll Notion CRM for new Client entries and create campaigns.

    Queries the Notion CRM database for entries with Pipeline Status = "Client"
    that haven't been synced yet, and creates campaigns for each one.
    """
    if not _db.is_active():
        return jsonify({"error": "Database not configured"}), 500

    from campaign_manager.services.notion import query_new_clients

    # Fetch ALL client rows, not just unsynced ones: the sync is add-only by
    # design, but content_types was empty for every campaign imported before
    # the property-name fix (0 of 326 populated while 286 of 300 CRM rows
    # carry tags). Existing campaigns are REFRESHED (content_types only —
    # operator-edited Hub fields are never touched), new ones are created.
    new_entries = query_new_clients(set())

    created = []
    skipped = []
    errors = []
    refreshed = []

    for entry in new_entries:
        page_id = entry.get("notion_page_id") or ""
        base_slug = entry["slug"]

        # Refresh (not create) when this CRM page was already imported, or when
        # the title slug maps to a legacy campaign with no recorded page id
        # (the content_types backfill). A repeat booking — a different page id
        # where the existing campaign already has one — falls through to the
        # shared intake below and becomes a round-suffixed campaign.
        refresh_slug = None
        if page_id:
            existing_by_page = _db.get_campaign_by_notion_page_id(page_id)
            if existing_by_page:
                refresh_slug = existing_by_page["slug"]
        if refresh_slug is None:
            existing = _db.get_campaign(base_slug)
            if existing is not None and not (existing.get("notion_page_id") or ""):
                refresh_slug = base_slug

        if refresh_slug is not None:
            entry_types = sorted(entry.get("content_types") or [])
            existing = _db.get_campaign(refresh_slug) or {}
            existing_types = sorted(existing.get("content_types") or [])
            changes = {}
            if entry_types != existing_types:
                changes["content_types"] = entry.get("content_types") or []
            # Captions follow the CRM row this campaign was imported from; a
            # same-titled row that is not its row never overwrites them.
            entry_captions = entry.get("internal_captions")
            if (entry_captions is not None
                    and existing.get("notion_page_id") == entry["notion_page_id"]
                    and entry_captions != existing.get("internal_captions")):
                changes["internal_captions"] = entry_captions
            if changes:
                _db.update_campaign_fields(refresh_slug, changes)
                refreshed.append({"slug": refresh_slug, **changes})
            else:
                skipped.append({"slug": refresh_slug, "reason": "already exists"})
            continue

        result = _intake_campaign(entry)
        if result["status"] == "created":
            created.append({"slug": result["slug"], "title": entry["title"]})
        elif result["status"] == "existing":
            skipped.append({"slug": result["slug"], "reason": "already exists"})
        elif result["status"] == "skipped":
            reason = result.get("reason")
            if reason == "duplicate sound URL":
                skipped.append({"slug": result["slug"], "reason": "duplicate sound URL"})
            else:
                skipped.append({"slug": result["slug"], "reason": "campaign changed during creation"})
        else:
            errors.append({"slug": result["slug"], "reason": "campaign save failed"})

    # Refresh pass for the EXISTING fleet, keyed by stored notion_page_id —
    # independent of Pipeline Status. The client-import funnel above only
    # sees 'Client' rows, but 782 of 783 CRM rows are 'Lead', and a
    # campaign's niche targets must keep syncing wherever the row lives.
    # A page we cannot read is skipped (never emptied); only actual changes
    # are written.
    from campaign_manager.services.notion import fetch_page_campaign_fields

    for link in _db.get_campaign_notion_links():
        fields = fetch_page_campaign_fields(link["notion_page_id"])
        if fields is None:
            continue
        changes = {}
        fresh = fields["content_types"]
        if fresh is not None and sorted(fresh) != sorted(link["content_types"]):
            changes["content_types"] = fresh
        captions = fields["internal_captions"]
        if captions is not None and captions != link["internal_captions"]:
            changes["internal_captions"] = captions
        if changes:
            _db.update_campaign_fields(link["slug"], changes)
            refreshed.append({"slug": link["slug"], **changes})

    return jsonify({
        "ok": not errors,
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "refreshed": refreshed,
        "message": f"Synced {len(created)} new campaign(s) from Notion"
            + (f", {len(refreshed)} refreshed" if refreshed else "")
            + (f", {len(skipped)} skipped" if skipped else ""),
    })
