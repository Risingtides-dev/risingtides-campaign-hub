"""Slack Events API endpoint.

Receives event payloads from Slack's Events API and delegates to the
slack-bolt app for processing. Also handles the URL verification challenge
required during Slack app setup.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

slack_events_bp = Blueprint("slack_events", __name__, url_prefix="/api/webhooks/slack")


@slack_events_bp.post("/events")
def slack_events():
    """Handle Slack Events API requests."""
    body = request.get_json(silent=True) or {}

    log.info("Slack event received: type=%s", body.get("type", "unknown"))

    # URL verification challenge (sent once during Slack app setup)
    if body.get("type") == "url_verification":
        return jsonify({"challenge": body.get("challenge", "")})

    # Log event details for debugging
    event = body.get("event", {})
    log.info(
        "Slack event detail: event_type=%s, channel=%s, text=%.80s, bot_id=%s, subtype=%s",
        event.get("type"),
        event.get("channel"),
        event.get("text", ""),
        event.get("bot_id"),
        event.get("subtype"),
    )

    # Delegate to slack-bolt handler
    from campaign_manager.services.slack_bot import get_slack_app
    slack_app = get_slack_app()

    if slack_app is None:
        log.error("Slack bot not initialized — missing SLACK_BOT_TOKEN or SLACK_SIGNING_SECRET")
        return jsonify({"error": "Slack bot not initialized"}), 503

    from slack_bolt.adapter.flask import SlackRequestHandler
    handler = SlackRequestHandler(slack_app)
    return handler.handle(request)


@slack_events_bp.get("/debug")
def slack_debug():
    """Debug endpoint to check Slack bot status."""
    import os
    from campaign_manager.services.slack_bot import get_slack_app

    slack_app = get_slack_app()
    return jsonify({
        "bot_initialized": slack_app is not None,
        "token_set": bool(os.environ.get("SLACK_BOT_TOKEN")),
        "secret_set": bool(os.environ.get("SLACK_SIGNING_SECRET")),
        "channel_configured": os.environ.get("SLACK_BOOKING_CHANNEL", ""),
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    })
