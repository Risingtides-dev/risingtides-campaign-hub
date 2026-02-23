"""Cobrand integration -- fetch live campaign stats from share pages.

Cobrand share pages are Next.js server-rendered pages that embed campaign data
in a __NEXT_DATA__ script tag. We parse this to extract performance metrics
without needing an official API.

We ONLY consume performance data (submission counts, comments, engagement).
Financial data (budget, spend, committed) is deliberately excluded because
Campaign Hub is the source of truth for financial tracking.
"""
import json
import re
from typing import Dict, Optional

import requests


def fetch_cobrand_stats(share_url: str) -> Optional[Dict]:
    """Fetch the Cobrand share page and extract performance data from __NEXT_DATA__.

    Args:
        share_url: Full Cobrand share URL with token, e.g.
            https://music.cobrand.com/promote/<id>/share/?token=<token>

    Returns:
        Dict with performance fields, or None if fetch/parse fails.
        Financial fields (budget, spend, spend_committed) are deliberately excluded.
    """
    if not share_url:
        return None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(share_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None

        return parse_next_data(resp.text)

    except Exception:
        return None


def parse_next_data(html: str) -> Optional[Dict]:
    """Parse __NEXT_DATA__ script tag from Cobrand page HTML.

    Returns structured performance data or None if parsing fails.
    """
    pattern = r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>'
    matches = re.findall(pattern, html, re.DOTALL)
    if not matches:
        return None

    try:
        data = json.loads(matches[0])
    except (json.JSONDecodeError, ValueError):
        return None

    # Navigate to the promotion object
    # Structure: { props: { pageProps: { promotion: {...}, token: "..." } } }
    page_props = data.get("props", {}).get("pageProps", {})
    promotion = page_props.get("promotion")
    if not promotion:
        return None

    return extract_performance_data(promotion)


def extract_performance_data(promotion: Dict) -> Dict:
    """Extract only performance/metadata fields from a Cobrand promotion object.

    Deliberately excludes:
    - budget, total_campaign_budget, spend, spend_committed (financial)
    - owner_auth0_user (auth)
    - organization internal IDs and whitelabel config
    """
    activations = []
    for act in promotion.get("activations", []):
        sounds = []
        segment = act.get("segment", {})
        for sound in segment.get("social_sounds", []):
            sounds.append({
                "id_platform": sound.get("id_platform", ""),
                "platform": sound.get("platform", ""),
                "title": sound.get("title", ""),
            })

        artist = act.get("artist") or {}
        activations.append({
            "id": act.get("id", ""),
            "name": act.get("name", ""),
            "artist_name": artist.get("name", ""),
            "artist_image_url": artist.get("image_url", ""),
            "social_sounds": sounds,
            "created_at": act.get("created_at", ""),
            "draft_submission_due_at": act.get("draft_submission_due_at"),
            "final_submission_due_at": act.get("final_submission_due_at"),
            "tags": act.get("tags", []),
        })

    return {
        "promotion_id": promotion.get("id", ""),
        "name": promotion.get("name", ""),
        "status": promotion.get("status", ""),
        "live_submission_count": promotion.get("live_submission_count", 0),
        "draft_submission_count": promotion.get("draft_submission_count", 0),
        "comment_count": promotion.get("comment_count", 0),
        "activation_count": promotion.get("activation_count", 0),
        "created_at": promotion.get("created_at", ""),
        "activations": activations,
    }
