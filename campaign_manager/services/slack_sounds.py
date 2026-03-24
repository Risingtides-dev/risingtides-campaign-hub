"""Post active campaign sound URLs to a dedicated Slack channel.

Uses the existing slack-bolt bot client — no additional Slack app or
permissions needed beyond what's already configured.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from campaign_manager import db as _db

EST = ZoneInfo("America/New_York")
log = logging.getLogger(__name__)


def _get_slack_client():
    try:
        from campaign_manager.services.slack_bot import _slack_app
        if _slack_app and _slack_app.client:
            return _slack_app.client
    except Exception:
        pass
    return None


def build_sounds_blocks(campaigns: list[dict]) -> tuple[list[dict], int]:
    """Build Slack Block Kit blocks for active campaign sounds.

    Returns (blocks, sound_count).
    """
    now = datetime.now(EST).strftime("%B %-d, %Y %-I:%M %p EST")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Active Campaign Sounds"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Updated {now}"}
            ],
        },
    ]

    sound_count = 0
    campaigns_with_sounds = 0

    for c in sorted(campaigns, key=lambda x: x.get("artist", "")):
        artist = c.get("artist") or "Unknown Artist"
        song = c.get("song") or "Untitled"
        official = c.get("official_sound") or ""
        additional = c.get("additional_sounds") or []

        urls = []
        if official:
            urls.append(official)
        for extra in additional:
            url = extra if isinstance(extra, str) else (extra.get("url") or extra.get("link") or "")
            if url:
                urls.append(url)

        if not urls:
            continue

        sound_count += len(urls)
        campaigns_with_sounds += 1

        lines = [f"*{artist} — {song}*"]
        for url in urls:
            lines.append(url)

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn",
             "text": f"{sound_count} sound(s) across {campaigns_with_sounds} campaign(s)"}
        ],
    })

    return blocks, sound_count


def post_sounds_to_slack(channel: str | None = None) -> dict:
    """Build the sounds list and post it to the Slack channel.

    Returns a summary dict with ok/error status.
    """
    channel = channel or os.environ.get("SLACK_SOUNDS_CHANNEL", "")
    if not channel:
        return {"ok": False, "error": "SLACK_SOUNDS_CHANNEL not configured"}

    client = _get_slack_client()
    if not client:
        return {"ok": False, "error": "Slack bot not initialized"}

    campaigns = _db.list_campaigns(status="active")
    if not campaigns:
        return {"ok": True, "posted": False, "message": "No active campaigns"}

    blocks, sound_count = build_sounds_blocks(campaigns)

    if sound_count == 0:
        return {"ok": True, "posted": False, "message": "No sound URLs found across active campaigns"}

    try:
        client.chat_postMessage(
            channel=channel,
            text=f"Active Campaign Sounds — {sound_count} sound(s)",
            blocks=blocks,
        )
        log.info("Posted %d sounds to Slack channel %s", sound_count, channel)
        return {"ok": True, "posted": True, "sound_count": sound_count}
    except Exception as e:
        log.error("Failed to post sounds to Slack: %s", e)
        return {"ok": False, "error": str(e)}
