"""Slack bot integration using slack-bolt.

Listens for booking messages in the configured channel, parses them with
Claude, and feeds structured data into the Campaign Hub inbox pipeline.
"""
from __future__ import annotations

import logging
import os
import traceback
from collections import deque
from datetime import datetime
from typing import List, Optional

from slack_bolt import App

from campaign_manager.services.llm import parse_booking_message

log = logging.getLogger(__name__)

_slack_app: Optional[App] = None

# In-memory log of recent events for debugging (last 20)
_event_log: deque = deque(maxlen=20)


def _log_event(msg: str):
    """Append a timestamped message to the debug event log."""
    entry = f"[{datetime.now().isoformat()}] {msg}"
    _event_log.append(entry)
    log.info(msg)


def get_event_log() -> List[str]:
    """Return recent event log entries."""
    return list(_event_log)


def init_slack_app() -> Optional[App]:
    """Initialize the Slack bolt app. Returns None if credentials aren't set."""
    global _slack_app

    token = os.environ.get("SLACK_BOT_TOKEN", "")
    secret = os.environ.get("SLACK_SIGNING_SECRET", "")

    if not token or not secret:
        log.info("Slack credentials not set, skipping Slack bot initialization")
        return None

    _slack_app = App(
        token=token,
        signing_secret=secret,
        process_before_response=True,
    )

    booking_channel = os.environ.get("SLACK_BOOKING_CHANNEL", "")

    @_slack_app.event("message")
    def handle_message(event, say):
        """Handle incoming channel messages."""
        _log_event(f"Event received: channel={event.get('channel')}, "
                   f"user={event.get('user')}, bot_id={event.get('bot_id')}, "
                   f"subtype={event.get('subtype')}, text={str(event.get('text', ''))[:80]}")

        # Ignore bot messages and message edits/deletes
        if event.get("bot_id") or event.get("subtype"):
            _log_event("Skipped: bot message or subtype")
            return

        # Only process messages in the configured booking channel
        if booking_channel and event.get("channel") != booking_channel:
            _log_event(f"Skipped: wrong channel {event.get('channel')} != {booking_channel}")
            return

        text = event.get("text", "")
        if not text.strip():
            _log_event("Skipped: empty text")
            return

        _log_event(f"Sending to LLM: {text[:100]}")

        try:
            # Get available campaigns for context
            from campaign_manager.blueprints.campaigns import get_campaigns
            campaigns = get_campaigns()

            # Parse with LLM
            result = parse_booking_message(text, campaigns)
            if result is None:
                from campaign_manager.services.llm import get_last_raw_response
                _log_event(f"LLM returned null — raw response: {get_last_raw_response()}")
                return

            _log_event(f"LLM parsed: {len(result.get('creators', []))} creator(s), "
                       f"campaign={result.get('campaign_name', '')}")

            # Feed into inbox pipeline
            from campaign_manager.blueprints.inbox import create_inbox_item
            item = create_inbox_item(
                source="slack",
                raw_message=text,
                campaign_name=result.get("campaign_name", ""),
                creators=result.get("creators", []),
                notes=result.get("notes", ""),
            )

            _log_event(f"Created inbox item {item['id']}")

        except Exception as e:
            _log_event(f"ERROR: {e}\n{traceback.format_exc()}")

    _log_event(f"Slack bot initialized, channel={booking_channel or '(all)'}")
    return _slack_app


def get_slack_app() -> Optional[App]:
    """Get the initialized Slack app, or None if not initialized."""
    return _slack_app
