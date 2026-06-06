"""Migration endpoints for importing data from local files via API.

These endpoints accept bulk data payloads and write them directly to the database.
Intended for one-time data migration, not ongoing use. Remove after migration is complete.
"""
from flask import Blueprint, jsonify, request

from campaign_manager import db as _db

migrate_bp = Blueprint("migrate", __name__, url_prefix="/api/migrate")


@migrate_bp.post("/campaign-full")
def migrate_campaign_full():
    """Import a complete campaign with creators, matched videos, and scrape log.

    Accepts:
    {
        "slug": "artist_song_promo",
        "campaign": { ...campaign.json contents... },
        "creators": [ ...creator dicts or CSV rows... ],
        "matched_videos": [ ...matched_videos.json contents... ],
        "scrape_log": { ...scrape_log.json contents... }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    slug = data.get("slug", "")
    if not slug:
        return jsonify({"error": "slug is required"}), 400

    # CAMP-96 hardening: this is a one-time import endpoint (docstring: "Remove
    # after migration is complete") that does an unauthenticated save_campaign
    # UPSERT — i.e. it silently OVERWRITES any existing campaign's full metadata
    # (budget, creators, matched_videos) by slug. Guard it: refuse to clobber an
    # existing campaign unless ?overwrite=1 is explicit (mirrors create_campaign,
    # which 409s on an existing slug). Re-imports pass the flag deliberately.
    overwrite = request.args.get("overwrite") in ("1", "true", "yes")
    if not overwrite and _db.is_active() and _db.campaign_exists(slug):
        return jsonify({
            "error": f"Campaign '{slug}' already exists. Pass ?overwrite=1 to replace it.",
            "slug": slug,
        }), 409

    campaign_meta = data.get("campaign", {})
    creators = data.get("creators", [])
    matched_videos = data.get("matched_videos", [])
    scrape_log = data.get("scrape_log", {})

    if not campaign_meta:
        return jsonify({"error": "campaign data is required"}), 400

    # Ensure slug is set in meta
    campaign_meta["slug"] = slug
    if not campaign_meta.get("title"):
        campaign_meta["title"] = campaign_meta.get("name", slug)
    if not campaign_meta.get("name"):
        campaign_meta["name"] = campaign_meta.get("title", slug)

    try:
        # Save campaign metadata
        _db.save_campaign(slug, campaign_meta)

        # Save creators
        if creators:
            # Normalize creator data (handle both dict and CSV-style formats)
            normalized = []
            for c in creators:
                normalized.append({
                    "username": str(c.get("username", "")).strip(),
                    "posts_owed": int(c.get("posts_owed", 0) or 0),
                    "posts_done": int(c.get("posts_done", 0) or 0),
                    "posts_matched": int(c.get("posts_matched", 0) or 0),
                    "total_rate": float(c.get("total_rate", 0) or 0),
                    "per_post_rate": float(c.get("per_post_rate", 0) or 0),
                    "paypal_email": str(c.get("paypal_email", "") or ""),
                    "paid": str(c.get("paid", "no") or "no"),
                    "payment_date": str(c.get("payment_date", "") or ""),
                    "platform": str(c.get("platform", "tiktok") or "tiktok"),
                    "added_date": str(c.get("added_date", "") or ""),
                    "status": str(c.get("status", "active") or "active"),
                    "notes": str(c.get("notes", "") or ""),
                })
            _db.save_creators(slug, normalized)

        # Save matched videos
        if matched_videos:
            _db.replace_matched_videos(slug, matched_videos)

        # Save scrape log
        if scrape_log:
            _db.save_scrape_log(slug, scrape_log)

        return jsonify({
            "ok": True,
            "slug": slug,
            "creators_count": len(creators),
            "videos_count": len(matched_videos),
            "message": f"Migrated campaign '{slug}' with {len(creators)} creators and {len(matched_videos)} videos",
        }), 201

    except Exception as e:
        return jsonify({"error": f"Migration failed: {str(e)}"}), 500


@migrate_bp.post("/paypal-bulk")
def migrate_paypal_bulk():
    """Import PayPal email memory in bulk.

    Accepts:
    {
        "paypal_memory": { "username": "email@example.com", ... }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    memory = data.get("paypal_memory", {})
    if not memory:
        return jsonify({"error": "paypal_memory dict is required"}), 400

    count = 0
    for username, email in memory.items():
        if username and email:
            _db.save_paypal(username.lower().strip(), email.strip())
            count += 1

    return jsonify({"ok": True, "count": count, "message": f"Imported {count} PayPal entries"})


@migrate_bp.post("/inbox-bulk")
def migrate_inbox_bulk():
    """Import inbox items in bulk.

    Accepts:
    {
        "items": [ ...inbox item dicts... ]
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    items = data.get("items", [])
    if not items:
        return jsonify({"error": "items list is required"}), 400

    count = 0
    for item in items:
        if item.get("id"):
            _db.save_inbox_item(item)
            count += 1

    return jsonify({"ok": True, "count": count, "message": f"Imported {count} inbox items"})


@migrate_bp.post("/internal")
def migrate_internal():
    """Import internal creator data.

    Accepts:
    {
        "creators": ["username1", "username2", ...],
        "results": { ...internal_last_scrape.json... },
        "caches": { "username": [ ...video dicts... ], ... }
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    creators = data.get("creators", [])
    results = data.get("results", {})
    caches = data.get("caches", {})

    if creators:
        _db.save_internal_creators(creators)

    if results:
        _db.save_internal_results(results)

    cache_count = 0
    for username, videos in caches.items():
        if username and videos:
            _db.merge_internal_cache(username, videos)
            cache_count += 1

    return jsonify({
        "ok": True,
        "creators_count": len(creators),
        "has_results": bool(results),
        "caches_count": cache_count,
        "message": f"Imported {len(creators)} internal creators, {cache_count} video caches",
    })
