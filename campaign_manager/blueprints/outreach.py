"""Network creator roster and campaign outreach endpoints."""
import logging
from datetime import datetime

import requests as http_requests
from flask import Blueprint, current_app, jsonify, request

from campaign_manager import db

log = logging.getLogger(__name__)

outreach_bp = Blueprint("outreach", __name__)


# ── Network CRUD ─────────────────────────────────────────────────────

@outreach_bp.route("/api/network", methods=["GET"])
def list_network():
    """List all creators in the network."""
    creators = db.get_network_creators()
    return jsonify(creators)


@outreach_bp.route("/api/network", methods=["POST"])
def add_to_network():
    """Add a creator to the network."""
    data = request.get_json(force=True)
    if not data.get("username"):
        return jsonify({"error": "username is required"}), 400
    try:
        creator = db.add_network_creator(data)
        return jsonify({"ok": True, "creator": creator})
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return jsonify({"error": f"@{data['username']} is already in the network"}), 409
        raise


@outreach_bp.route("/api/network/<username>", methods=["PUT"])
def edit_network_creator(username):
    """Edit a network creator."""
    data = request.get_json(force=True)
    result = db.update_network_creator(username, data)
    if not result:
        return jsonify({"error": "Creator not found"}), 404
    return jsonify({"ok": True, "creator": result})


@outreach_bp.route("/api/network/<username>", methods=["DELETE"])
def remove_from_network(username):
    """Remove a creator from the network."""
    if db.remove_network_creator(username):
        return jsonify({"ok": True})
    return jsonify({"error": "Creator not found"}), 404


# ── Campaign Outreach ────────────────────────────────────────────────

@outreach_bp.route("/api/campaign/<slug>/outreach", methods=["GET"])
def get_outreach(slug):
    """Get outreach state for a campaign: messages + network creators with in_outreach flags."""
    campaign_id = db.get_campaign_id(slug)
    if not campaign_id:
        return jsonify({"error": "Campaign not found"}), 404

    campaign = db.get_campaign(slug)
    messages = db.get_outreach_messages(campaign_id)
    network = db.get_network_creators()

    # Mark which network creators are already in outreach
    outreach_usernames = {m["username"].lower() for m in messages}
    for nc in network:
        nc["in_outreach"] = nc["username"].lower() in outreach_usernames

    return jsonify({
        "campaign": campaign,
        "messages": messages,
        "network_creators": network,
        "templates": {
            "offer": 'Hey {creator}! We have a new campaign for {artist} - "{song}". Your rate would be ${rate} for {posts} post(s).\n\nLet me know if you\'re interested!',
        },
    })


@outreach_bp.route("/api/campaign/<slug>/outreach/add", methods=["POST"])
def add_to_outreach(slug):
    """Add creators to outreach as drafts."""
    campaign_id = db.get_campaign_id(slug)
    if not campaign_id:
        return jsonify({"error": "Campaign not found"}), 404

    data = request.get_json(force=True)
    creators = data if isinstance(data, list) else data.get("creators", [])
    added = db.add_outreach_messages(campaign_id, creators)
    return jsonify({"ok": True, "added": len(added), "messages": added})


@outreach_bp.route("/api/campaign/<slug>/outreach/remove", methods=["POST"])
def remove_from_outreach(slug):
    """Remove a draft outreach message."""
    campaign_id = db.get_campaign_id(slug)
    if not campaign_id:
        return jsonify({"error": "Campaign not found"}), 404

    data = request.get_json(force=True)
    username = data.get("username", "")
    if db.remove_outreach_message(campaign_id, username):
        return jsonify({"ok": True})
    return jsonify({"error": "Message not found or not a draft"}), 404


@outreach_bp.route("/api/campaign/<slug>/outreach/send", methods=["POST"])
def send_outreach(slug):
    """Send all draft outreach messages via ManyChat.

    For now this marks drafts as 'sent' and stores the message text.
    ManyChat integration will be added when the webhook is set up.
    """
    campaign_id = db.get_campaign_id(slug)
    if not campaign_id:
        return jsonify({"error": "Campaign not found"}), 404

    data = request.get_json(force=True)
    message_template = data.get("message_template", "")
    campaign = db.get_campaign(slug)

    # Get all draft messages
    messages = db.get_outreach_messages(campaign_id)
    draft_usernames = [m["username"] for m in messages if m["status"] == "draft"]

    if not draft_usernames:
        return jsonify({"error": "No draft messages to send"}), 400

    sent = []
    errors = []

    for username in draft_usernames:
        # Personalize template
        nc = db.get_network_creator(username)
        msg = db.get_outreach_message(campaign_id, username)
        if not msg:
            continue

        personalized = message_template\
            .replace("{creator}", username)\
            .replace("{artist}", campaign.get("artist", ""))\
            .replace("{song}", campaign.get("song", ""))\
            .replace("{rate}", str(int(msg["rate_offered"])))\
            .replace("{posts}", str(msg["posts_offered"]))

        if nc and nc.get("manychat_subscriber_id"):
            # Send via ManyChat API if key is configured
            manychat_key = current_app.config.get("MANYCHAT_API_KEY", "")
            mc_success = False
            if manychat_key:
                try:
                    mc_resp = http_requests.post(
                        "https://api.manychat.com/fb/sending/sendContent",
                        headers={
                            "Authorization": f"Bearer {manychat_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "subscriber_id": nc["manychat_subscriber_id"],
                            "data": {"version": "v2", "content": {"messages": [{"type": "text", "text": personalized}]}},
                            "message_tag": "CONFIRMED_EVENT_UPDATE",
                        },
                        timeout=10,
                    )
                    if mc_resp.status_code == 200:
                        mc_success = True
                        mc_data = mc_resp.json()
                        log.info("ManyChat sent to %s: %s", username, mc_data)
                    else:
                        log.warning("ManyChat error for %s: %s %s", username, mc_resp.status_code, mc_resp.text)
                        errors.append({"username": username, "error": f"ManyChat API error: {mc_resp.status_code}"})
                except Exception as e:
                    log.error("ManyChat request failed for %s: %s", username, e)
                    errors.append({"username": username, "error": f"ManyChat request failed: {str(e)}"})
            else:
                # No API key — mark as sent anyway (manual follow-up)
                mc_success = True

            if mc_success:
                db.update_outreach_message(campaign_id, username, {
                    "status": "sent",
                    "message_text": personalized,
                    "sent_at": datetime.now(),
                })
                sent.append(username)
        else:
            errors.append({"username": username, "error": "No ManyChat subscriber ID"})

    return jsonify({"ok": True, "sent": sent, "errors": errors})


@outreach_bp.route("/api/campaign/<slug>/outreach/status", methods=["GET"])
def outreach_status(slug):
    """Get current outreach status with counts."""
    campaign_id = db.get_campaign_id(slug)
    if not campaign_id:
        return jsonify({"error": "Campaign not found"}), 404

    messages = db.get_outreach_messages(campaign_id)
    counts = {}
    for m in messages:
        status = m["status"]
        counts[status] = counts.get(status, 0) + 1

    return jsonify({"messages": messages, "counts": counts})


@outreach_bp.route("/api/campaign/<slug>/outreach/confirm", methods=["POST"])
def confirm_outreach_endpoint(slug):
    """Confirm an outreach (accept and add creator to campaign)."""
    campaign_id = db.get_campaign_id(slug)
    if not campaign_id:
        return jsonify({"error": "Campaign not found"}), 404

    data = request.get_json(force=True)
    username = data.get("username", "")
    result = db.confirm_outreach(campaign_id, username)
    if not result:
        return jsonify({"error": "Outreach message not found"}), 404
    return jsonify({"ok": True, "message": result})


# ── ManyChat Webhook ─────────────────────────────────────────────────

@outreach_bp.route("/api/manychat/webhook", methods=["POST"])
def manychat_webhook():
    """Receive reply notifications from ManyChat.

    Expected payload: { subscriber_id, text }
    """
    data = request.get_json(force=True)
    subscriber_id = data.get("subscriber_id", "")
    text = data.get("text", "")

    if not subscriber_id:
        return jsonify({"error": "subscriber_id required"}), 400

    # Find the network creator by subscriber ID
    from campaign_manager.models import NetworkCreator as NC, OutreachMessage as OM
    session = db.get_session()
    try:
        nc = session.query(NC).filter_by(manychat_subscriber_id=subscriber_id).first()
        if not nc:
            return jsonify({"ok": False, "error": "Unknown subscriber"}), 404

        # Find the most recent sent outreach for this creator
        msg = session.query(OM).filter_by(
            username=nc.username, status="sent"
        ).order_by(OM.sent_at.desc()).first()

        if msg:
            msg.status = "responded"
            msg.reply_text = text
            msg.responded_at = datetime.now()
            session.commit()
            return jsonify({"ok": True, "username": nc.username, "status": "responded"})

        return jsonify({"ok": False, "error": "No pending outreach for this creator"}), 404
    finally:
        session.close()
