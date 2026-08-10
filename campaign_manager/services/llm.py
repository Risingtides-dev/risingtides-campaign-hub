"""LLM-based parsing for Slack booking messages using Claude API."""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

import anthropic

log = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None
_last_raw_response: str = ""


def get_last_raw_response() -> str:
    """Return the last raw LLM response for debugging."""
    return _last_raw_response


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


SYSTEM_PROMPT = """\
You are a booking message parser for a music marketing agency. Your job is to \
extract structured booking data from informal Slack messages.

Messages come from a dedicated booking channel. Almost every message is a booking. \
The format is informal and varies, but common patterns include:

Pattern 1 — One creator, multiple campaigns (most common):
```
username
3 for campaign name
$50
3 for another campaign
$50
```

Pattern 2 — With PayPal info:
```
@username
5 Post for Campaign Name
$100
paypal@email.com
```

Pattern 3 — With notes:
```
username
5 for campaign name
$200 total
Not confirmed
```

Pattern 4 — Compact:
```
username 5/$100 campaign name
```

Pattern 5 — Multiple creators in one message:
```
@user1 3 for campaign $75
@user2 5 for campaign $100
```

Extract:
- **creators**: each creator with username, posts_owed (number of posts), \
total_rate (dollar amount for that creator). A single creator can be booked \
across multiple campaigns — create SEPARATE entries for each campaign line.
- **campaign_name**: the campaign, artist, or song name referenced. \
If multiple campaigns, use the first one mentioned as campaign_name.
- **notes**: anything extra (payment status, confirmation status, special instructions)

Rules:
- Strip @ symbols from usernames
- Usernames are typically the first line or start of the message
- Rates are TOTAL for that booking, not per-post
- Lines with "for [name]" indicate campaign bookings
- If PayPal email or paypal.me link is present, include it
- Slack formats links as <url|display> or <mailto:email|email> — extract the actual value
- If a message contains a username + post count, it IS a booking (dollar amount is optional)
- Rate/dollar amount may not always be present — use 0 if not mentioned
- When in doubt, treat it as a booking — false positives are OK, they get reviewed by a human
- NEVER return null for a message that has a username and post counts

Respond with ONLY valid JSON (no markdown fences, no explanation). \
Return null ONLY if the message clearly has no booking information at all \
(e.g., just "ok" or "thanks" or a question)."""

USER_TEMPLATE = """\
Parse this Slack message into a booking:

Message: {message}

Active campaigns for reference:
{campaigns}

Respond with JSON matching this schema:
{{
  "campaign_name": "string or empty",
  "creators": [
    {{
      "username": "string (no @ prefix)",
      "posts_owed": number,
      "total_rate": number or 0 if not mentioned,
      "paypal_email": "string or empty"
    }}
  ],
  "notes": "string or empty"
}}

Or respond with null if this is not a booking message."""


def parse_booking_message(
    raw_message: str,
    available_campaigns: List[Dict],
) -> Optional[Dict]:
    """Parse a raw Slack message into structured booking data.

    Returns a dict matching the /api/inbox POST body schema, or None if
    the message isn't a booking.
    """
    if not raw_message or not raw_message.strip():
        return None

    # Build campaign reference list for the prompt
    campaign_lines = []
    for c in available_campaigns:
        meta = c.get("meta", c)
        name = meta.get("title") or meta.get("name") or c.get("slug", "")
        artist = meta.get("artist", "")
        slug = c.get("slug", "")
        parts = [f"- {name}"]
        if artist:
            parts[0] += f" (artist: {artist})"
        if slug:
            parts[0] += f" [slug: {slug}]"
        campaign_lines.append(parts[0])

    campaigns_text = "\n".join(campaign_lines) if campaign_lines else "(none active)"

    user_msg = USER_TEMPLATE.format(
        message=raw_message,
        campaigns=campaigns_text,
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        global _last_raw_response
        text = response.content[0].text.strip()
        _last_raw_response = text
        log.info("LLM raw response: %.500s", text)

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.startswith("json"):
                text = text[4:].strip()

        if text.lower() == "null" or not text:
            log.info("LLM explicitly returned null")
            return None

        parsed = json.loads(text)
        if parsed is None:
            return None

        # Validate minimum structure
        creators = parsed.get("creators")
        if not creators or not isinstance(creators, list):
            log.warning("LLM returned no creators: %s", text)
            return None

        # Normalize creator fields
        for cr in creators:
            cr["username"] = str(cr.get("username", "")).strip().lstrip("@").lower()
            cr["posts_owed"] = int(cr.get("posts_owed", 0) or 0)
            cr["total_rate"] = float(cr.get("total_rate", 0) or 0)
            cr["paypal_email"] = str(cr.get("paypal_email", "") or "").strip()

        # Filter out creators with no username
        parsed["creators"] = [cr for cr in creators if cr["username"]]

        if not parsed["creators"]:
            return None

        return {
            "campaign_name": str(parsed.get("campaign_name", "") or ""),
            "creators": parsed["creators"],
            "notes": str(parsed.get("notes", "") or ""),
        }

    except json.JSONDecodeError as e:
        log.error("LLM returned invalid JSON: %s — raw: %s", e, text)
        return None
    except anthropic.APIError as e:
        log.error("Claude API error: %s", e)
        return None
    except Exception as e:
        log.error("Unexpected error parsing booking message: %s", e, exc_info=True)
        return None


# ===================================================================
# ManyChat inbound DM classification
# ===================================================================
#
# Every inbound DM through the ManyChat webhook gets a Claude Haiku pass
# that tags it with a closed-set intent label and extracts any rate /
# email / paypal / song mentions. The intent drives the inbox view, and
# the extracted fields can auto-populate NetworkCreator rows when a new
# subscriber DMs us for the first time.
#
# Closed intent set (do not add freeform tags):
#   interested       — creator says yes / wants more info / is in
#   not_interested   — explicit no / not available / rate too low
#   rate_question    — asking about rate before committing
#   schedule_question — asking about deadline / timing
#   payment_question  — asking about payment method / timing
#   needs_info       — unclear / asking for more context
#   spam             — not a real creator / bot / off-topic
#   other            — doesn't fit anything above

INTENT_LABELS = {
    "interested",
    "not_interested",
    "rate_question",
    "schedule_question",
    "payment_question",
    "needs_info",
    "spam",
    "other",
}

CLASSIFY_SYSTEM_PROMPT = """\
You are a DM triage assistant for Rising Tides, a social media marketing \
agency that books TikTok and Instagram influencers for music marketing \
campaigns. You classify inbound DMs from creators into a fixed set of \
intents and extract any structured data.

Intents (you MUST pick exactly one):
- interested: creator says yes, is in, wants to proceed, asks where to send content
- not_interested: explicit no, not available, rate too low, off-brand
- rate_question: asking how much they will be paid before committing
- schedule_question: asking about deadline, timing, when to post
- payment_question: asking about payment method (paypal/venmo/zelle) or timing
- needs_info: unclear / asking for more context about the campaign
- spam: not a real creator, bot, off-topic, scam attempt
- other: real message but does not fit any label above

Also extract any of these fields if mentioned (use empty string if absent):
- rate: dollar amount the creator mentions (e.g. "$150", "100", "one hundred")
- email: a regular email address
- paypal: a paypal email or paypal.me link
- song: a song title or artist name they reference
- deadline: any date/time they mention

Respond with ONLY valid JSON (no markdown, no prose). Never leave intent empty.\
"""

CLASSIFY_USER_TEMPLATE = """\
Classify this inbound DM from a creator:

Message: {message}

Respond with JSON matching this schema:
{{
  "intent": "one of: interested | not_interested | rate_question | schedule_question | payment_question | needs_info | spam | other",
  "confidence": number between 0 and 1,
  "extracted": {{
    "rate": "string or empty",
    "email": "string or empty",
    "paypal": "string or empty",
    "song": "string or empty",
    "deadline": "string or empty"
  }}
}}"""


def classify_manychat_message(text: str) -> Optional[Dict]:
    """Classify a single inbound DM with Claude Haiku.

    Returns a dict:
        {
            "intent": "<one of INTENT_LABELS>",
            "confidence": 0.0 - 1.0,
            "extracted": {rate, email, paypal, song, deadline},
        }

    Returns None on any failure -- caller should leave the message
    unclassified and retry later via /api/inbox/reclassify.
    """
    if not text or not text.strip():
        return None

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=CLASSIFY_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": CLASSIFY_USER_TEMPLATE.format(message=text.strip()),
            }],
        )
        raw = response.content[0].text.strip()
        log.info("Classify raw: %.200s", raw)

        # Strip markdown fences if Claude added any.
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        parsed = json.loads(raw)
        intent = str(parsed.get("intent", "")).strip().lower()
        if intent not in INTENT_LABELS:
            log.warning("Classify returned invalid intent: %r", intent)
            intent = "other"

        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        confidence = max(0.0, min(1.0, confidence))

        extracted = parsed.get("extracted") or {}
        if not isinstance(extracted, dict):
            extracted = {}
        # Normalize extracted fields to strings.
        for key in ("rate", "email", "paypal", "song", "deadline"):
            extracted[key] = str(extracted.get(key, "") or "").strip()

        return {
            "intent": intent,
            "confidence": confidence,
            "extracted": extracted,
        }

    except json.JSONDecodeError as e:
        log.error("Classify: invalid JSON: %s — raw: %s", e, raw if 'raw' in dir() else "")
        return None
    except anthropic.APIError as e:
        log.error("Classify: Claude API error: %s", e)
        return None
    except Exception as e:
        log.error("Classify: unexpected error: %s", e, exc_info=True)
        return None
