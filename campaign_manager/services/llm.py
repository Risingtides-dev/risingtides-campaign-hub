"""LLM-based parsing for Slack booking messages using Claude API."""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

import anthropic

log = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None


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
- If a message contains a username + post count + dollar amount, it IS a booking
- When in doubt, treat it as a booking — false positives are OK, they get reviewed by a human

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
      "total_rate": number,
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
            model="claude-haiku-4-20250414",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        text = response.content[0].text.strip()

        if text.lower() == "null" or not text:
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
        log.error("LLM returned invalid JSON: %s", e)
        return None
    except anthropic.APIError as e:
        log.error("Claude API error: %s", e)
        return None
    except Exception as e:
        log.error("Unexpected error parsing booking message: %s", e)
        return None
