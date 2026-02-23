"""Slack Inbox API endpoints.

Migrated from web_dashboard.py -- all routes converted to JSON API responses.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

from flask import Blueprint, jsonify, request

from campaign_manager import db as _db
from campaign_manager.blueprints.campaigns import (
    get_campaigns,
    remember_paypal,
    recall_paypal,
    load_creators,
    save_creators,
    CREATOR_FIELDS,
    ACTIVE_DIR,
    CAMPAIGNS_DIR,
)

inbox_bp = Blueprint("inbox", __name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
INBOX_PATH = CAMPAIGNS_DIR / "inbox.json"

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_inbox() -> List[Dict]:
    if _db.is_active():
        return _db.get_inbox()
    if INBOX_PATH.exists():
        try:
            return json.loads(INBOX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_inbox(items: List[Dict]):
    if _db.is_active():
        # In DB mode, inbox items are saved individually -- this is a no-op
        # for backward compat (individual saves happen in the route handlers)
        return
    INBOX_PATH.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")


def _suggest_campaign(name: str, raw_message: str) -> tuple:
    """Fuzzy-match a campaign by name, artist, or keywords in the message.
    Returns (slug, display_name, True) if suggested, or ('', name, False).
    """
    campaigns = get_campaigns()
    if not campaigns:
        return "", name, False

    search_text = f"{name} {raw_message}".lower()
    if not search_text.strip():
        return "", name, False

    best_slug = ""
    best_name = name
    best_score = 0

    for c in campaigns:
        meta = c["meta"]
        slug = c["slug"]
        title = (meta.get("title") or meta.get("name") or "").lower()
        artist = (meta.get("artist") or "").lower()
        song = (meta.get("song") or "").lower()

        score = 0
        # Exact slug match
        if slug in search_text.replace(" ", "_"):
            score = 100
        # Artist name match (strong signal)
        if artist and len(artist) > 2 and artist in search_text:
            score = max(score, 60)
        # Song name match
        if song and len(song) > 2 and song in search_text:
            score = max(score, 50)
        # Title word overlap
        title_words = {w for w in title.split() if len(w) > 2}
        search_words = set(search_text.split())
        if title_words:
            overlap = len(title_words & search_words)
            word_score = int(40 * overlap / len(title_words))
            score = max(score, word_score)

        if score > best_score:
            best_score = score
            best_slug = slug
            best_name = meta.get("title") or meta.get("name") or slug

    if best_score >= 30:
        return best_slug, best_name, True
    return "", name, False


# ===================================================================
# Routes
# ===================================================================

# -------------------------------------------------------------------
# 1. POST /api/inbox  -- add an inbox item
# -------------------------------------------------------------------
@inbox_bp.post("/api/inbox")
def inbox_add():
    """Open CLAW posts a parsed booking recommendation here."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    # Auto-extract PayPal emails from raw_message and per-creator data
    creators_data = data.get("creators", [])
    raw_msg = data.get("raw_message", "")

    # Try to extract PayPal info from raw message text
    # Look for patterns like "username - email@example.com" or "username: email@example.com"
    if raw_msg:
        email_pattern = re.compile(r'@?([\w.]+)\s*[-:–]\s*([\w.+-]+@[\w.-]+\.\w+)')
        for match in email_pattern.finditer(raw_msg):
            uname = match.group(1).lower().strip()
            email = match.group(2).strip()
            # Save to paypal memory for future auto-fill
            remember_paypal(uname, email)
            # Also attach to matching creator in the list
            for cr in creators_data:
                cr_name = cr.get("username", "").strip().lstrip("@").lower()
                if cr_name == uname and not cr.get("paypal_email"):
                    cr["paypal_email"] = email

    # For any creator with a paypal_email, save to memory
    for cr in creators_data:
        uname = cr.get("username", "").strip().lstrip("@").lower()
        paypal = cr.get("paypal_email", "").strip()
        if uname and paypal:
            remember_paypal(uname, paypal)
        elif uname and not paypal:
            # Try to auto-fill from memory
            remembered = recall_paypal(uname)
            if remembered:
                cr["paypal_email"] = remembered

    # Auto-suggest campaign if slug not provided
    campaign_slug = data.get("campaign_slug", "")
    campaign_name = data.get("campaign_name", "")
    suggested = False
    if not campaign_slug:
        campaign_slug, campaign_name, suggested = _suggest_campaign(
            campaign_name, raw_msg
        )

    item = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S") + f"-{os.urandom(3).hex()}",
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "source": data.get("source", "slack"),
        "raw_message": raw_msg,
        "campaign_name": campaign_name,
        "campaign_slug": campaign_slug,
        "campaign_suggested": suggested,
        "creators": creators_data,
        "notes": data.get("notes", ""),
    }

    if _db.is_active():
        _db.save_inbox_item(item)
    else:
        inbox = load_inbox()
        inbox.insert(0, item)
        save_inbox(inbox)

    return jsonify({"ok": True, "id": item["id"], "message": "Added to inbox"})


# -------------------------------------------------------------------
# 2. GET /api/inbox  -- list inbox items
# -------------------------------------------------------------------
@inbox_bp.get("/api/inbox")
def inbox_list():
    """Get all pending inbox items."""
    status_filter = request.args.get("status", "pending")
    if _db.is_active():
        inbox = _db.get_inbox(status=status_filter)
    else:
        inbox = load_inbox()
        if status_filter != "all":
            inbox = [i for i in inbox if i.get("status") == status_filter]
    return jsonify(inbox)


# -------------------------------------------------------------------
# 3. POST /api/inbox/<item_id>/approve  -- approve inbox item
# -------------------------------------------------------------------
@inbox_bp.post("/api/inbox/<item_id>/approve")
def inbox_approve(item_id: str):
    """Approve an inbox item -- adds creators to the campaign."""
    if _db.is_active():
        item = _db.get_inbox_item(item_id)
    else:
        inbox = load_inbox()
        item = next((i for i in inbox if i.get("id") == item_id), None)
    if not item:
        return jsonify({"error": "Inbox item not found"}), 404

    # Allow overriding campaign_slug and creator details from the request body
    body = request.get_json(silent=True) or {}
    if body.get("campaign_slug"):
        item["campaign_slug"] = body["campaign_slug"]
    if body.get("creators"):
        item["creators"] = body["creators"]

    slug = item.get("campaign_slug", "")
    if not slug:
        return jsonify({"error": "No campaign_slug in inbox item"}), 400

    if _db.is_active():
        if not _db.campaign_exists(slug):
            return jsonify({"error": f"Campaign '{slug}' not found"}), 404
        creators = _db.get_creators(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": f"Campaign '{slug}' not found"}), 404
        creators = load_creators(campaign_dir)

    existing_usernames = {c.get("username", "").lower() for c in creators}
    added = []

    for cr in item.get("creators", []):
        username = cr.get("username", "").strip().lstrip("@").lower()
        if not username or username in existing_usernames:
            continue

        posts_owed = int(cr.get("posts_owed", 0))
        total_rate = float(cr.get("total_rate", 0))
        per_post = round(total_rate / posts_owed, 2) if posts_owed > 0 else 0

        new_creator = {f: "" for f in CREATOR_FIELDS}
        new_creator.update({
            "username": username,
            "posts_owed": str(posts_owed),
            "posts_done": "0",
            "posts_matched": "0",
            "total_rate": str(total_rate),
            "per_post_rate": str(per_post),
            "paypal_email": cr.get("paypal_email", "") or recall_paypal(username),
            "paid": cr.get("paid", "no"),
            "platform": "tiktok",
            "added_date": str(date.today()),
            "status": "active",
            "notes": cr.get("notes", ""),
        })
        creators.append(new_creator)
        existing_usernames.add(username)
        added.append(username)

    if _db.is_active():
        _db.save_creators(slug, creators)
        _db.update_inbox_item(item_id, {
            "status": "approved",
            "approved_at": datetime.now(),
            "creators_added": added,
            "campaign_slug": slug,
            "creators": item.get("creators", []),
        })
    else:
        save_creators(campaign_dir, creators)
        item["status"] = "approved"
        item["approved_at"] = datetime.now().isoformat()
        item["creators_added"] = added
        save_inbox(inbox)

    return jsonify({"ok": True, "added": added, "message": f"Added {len(added)} creators to {slug}"})


# -------------------------------------------------------------------
# 4. POST /api/inbox/<item_id>/dismiss  -- dismiss inbox item
# -------------------------------------------------------------------
@inbox_bp.post("/api/inbox/<item_id>/dismiss")
def inbox_dismiss(item_id: str):
    """Dismiss/reject an inbox item."""
    if _db.is_active():
        item = _db.get_inbox_item(item_id)
        if not item:
            return jsonify({"error": "Inbox item not found"}), 404
        _db.update_inbox_item(item_id, {
            "status": "dismissed",
            "dismissed_at": datetime.now(),
        })
    else:
        inbox = load_inbox()
        item = next((i for i in inbox if i.get("id") == item_id), None)
        if not item:
            return jsonify({"error": "Inbox item not found"}), 404
        item["status"] = "dismissed"
        item["dismissed_at"] = datetime.now().isoformat()
        save_inbox(inbox)
    return jsonify({"ok": True, "message": "Dismissed"})
