"""Campaign API endpoints.

Migrated from web_dashboard.py -- all routes converted to JSON API responses.
"""
from __future__ import annotations

import csv
import json
import os
import re

import requests as _requests
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

from flask import Blueprint, current_app, jsonify, request

from campaign_manager import db as _db
from campaign_manager.utils.helpers import (
    slugify,
    campaign_title,
    extract_sound_id,
    extract_sound_id_from_html,
    resolve_tiktok_short_url,
    parse_sort_datetime,
    load_json,
    save_json,
)
from campaign_manager.utils.budget import calc_budget, calc_stats

campaigns_bp = Blueprint("campaigns", __name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent          # campaign_manager/
PROJECT_ROOT = BASE_DIR.parent                             # project root

IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT") is not None
DATA_ROOT = Path("/app/data_volume") if IS_RAILWAY else BASE_DIR

CAMPAIGNS_DIR = DATA_ROOT / "campaigns"
ACTIVE_DIR = CAMPAIGNS_DIR / "active"
COMPLETED_DIR = CAMPAIGNS_DIR / "completed"

PAYPAL_MEMORY_PATH = CAMPAIGNS_DIR / "paypal_memory.json"

CREATOR_FIELDS = [
    "username", "posts_owed", "posts_done", "posts_matched",
    "total_rate", "per_post_rate", "paypal_email", "paid",
    "payment_date", "platform", "added_date", "status", "notes",
]

# ---------------------------------------------------------------------------
# File-mode helpers (used when database is not active)
# ---------------------------------------------------------------------------

def ensure_dirs() -> None:
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)


def load_creators(campaign_dir: Path) -> List[Dict]:
    csv_path = campaign_dir / "creators.csv"
    if not csv_path.exists():
        return []
    rows: List[Dict] = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["posts_owed"] = int(row.get("posts_owed") or 0)
            row["posts_done"] = int(row.get("posts_done") or 0)
            row["posts_matched"] = int(row.get("posts_matched") or 0)
            row["total_rate"] = float(row.get("total_rate") or 0)
            row["per_post_rate"] = float(row.get("per_post_rate") or 0)
            rows.append(row)
    return rows


def save_creators(campaign_dir: Path, creators: List[Dict]) -> None:
    csv_path = campaign_dir / "creators.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CREATOR_FIELDS)
        writer.writeheader()
        for c in creators:
            writer.writerow({k: c.get(k, "") for k in CREATOR_FIELDS})


def load_matched_videos(campaign_dir: Path) -> List[Dict]:
    """Load stored matched videos for a campaign."""
    path = campaign_dir / "matched_videos.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []


def save_matched_videos(campaign_dir: Path, videos: List[Dict]) -> None:
    """Save matched videos, deduplicating by URL."""
    seen: set = set()
    deduped: List[Dict] = []
    for v in videos:
        url = v.get("url", "")
        if url and url not in seen:
            seen.add(url)
            deduped.append(v)
    # Sort by date descending
    deduped.sort(key=lambda v: v.get("upload_date", ""), reverse=True)
    with open(campaign_dir / "matched_videos.json", "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# PayPal memory helpers
# ---------------------------------------------------------------------------

def load_paypal_memory() -> Dict[str, str]:
    if _db.is_active():
        return _db.get_all_paypal()
    if not PAYPAL_MEMORY_PATH.exists():
        return {}
    with open(PAYPAL_MEMORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_paypal_memory(memory: Dict[str, str]) -> None:
    if _db.is_active():
        for uname, email in memory.items():
            _db.save_paypal(uname, email)
        return
    CAMPAIGNS_DIR.mkdir(parents=True, exist_ok=True)
    with open(PAYPAL_MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)


def remember_paypal(username: str, email: str) -> None:
    if not username or not email:
        return
    if _db.is_active():
        _db.save_paypal(username, email)
        return
    memory = load_paypal_memory()
    memory[username.lower()] = email
    save_paypal_memory(memory)


def recall_paypal(username: str) -> str:
    if _db.is_active():
        return _db.get_paypal(username)
    memory = load_paypal_memory()
    return memory.get(username.lower(), "")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _save_meta(slug: str, meta: Dict, campaign_dir=None):
    """Save campaign metadata to DB or file, depending on mode."""
    if _db.is_active():
        _db.save_campaign(slug, meta)
    else:
        save_json(campaign_dir / "campaign.json", meta)


def get_campaigns() -> List[Dict]:
    """Return all active campaigns with budget/stats attached."""
    if _db.is_active():
        metas = _db.list_campaigns(status="active")
        items = []
        for meta in metas:
            slug = meta["slug"]
            creators = _db.get_creators(slug)
            budget = calc_budget(meta, creators)
            stats = calc_stats(meta, creators)
            items.append({
                "slug": slug,
                "meta": meta,
                "title": campaign_title(meta),
                "creators": creators,
                "budget": budget,
                "stats": stats,
                "created_dt": parse_sort_datetime(meta),
            })
        return items

    ensure_dirs()
    items = []
    for d in ACTIVE_DIR.iterdir() if ACTIVE_DIR.exists() else []:
        if not d.is_dir():
            continue
        meta = load_json(d / "campaign.json")
        if not meta:
            continue
        creators = load_creators(d)
        budget = calc_budget(meta, creators)
        stats = calc_stats(meta, creators)

        items.append({
            "slug": d.name,
            "meta": meta,
            "title": campaign_title(meta),
            "creators": creators,
            "budget": budget,
            "stats": stats,
            "created_dt": parse_sort_datetime(meta),
        })
    return items


def _campaign_summary(c: Dict) -> Dict:
    """Build a JSON-safe campaign summary."""
    return {
        "slug": c["slug"],
        "title": c["title"],
        "artist": c["meta"].get("artist", ""),
        "song": c["meta"].get("song", ""),
        "start_date": c["meta"].get("start_date", ""),
        "status": c["meta"].get("status", "active"),
        "budget": c["budget"],
        "stats": c["stats"],
        "completion_status": c["meta"].get("completion_status", "none"),
        "creator_count": len([
            cr for cr in c["creators"]
            if cr.get("status", "active") != "removed"
        ]),
    }


# ===================================================================
# Routes
# ===================================================================

# -------------------------------------------------------------------
# 1. GET /api/campaigns  -- list all campaigns
# -------------------------------------------------------------------
@campaigns_bp.get("/api/campaigns")
def list_campaigns():
    """List all campaigns with budget and stats."""
    search = (request.args.get("search") or "").strip().lower()
    campaigns = get_campaigns()

    if search:
        tokens = [t for t in re.split(r"\s+", search) if t]

        def _match(c):
            blob = " ".join([
                c["title"],
                c["meta"].get("artist", ""),
                c["meta"].get("song", ""),
                str(c["meta"].get("official_sound", "")),
                str(c["meta"].get("sound_id", "")),
                c["slug"],
            ]).lower()
            return all(tok in blob for tok in tokens)

        campaigns = [c for c in campaigns if _match(c)]

    campaigns.sort(key=lambda c: c["meta"].get("start_date", ""), reverse=True)
    return jsonify([_campaign_summary(c) for c in campaigns])


# -------------------------------------------------------------------
# 2. POST /api/campaign/create  -- create a new campaign
# -------------------------------------------------------------------
@campaigns_bp.post("/api/campaign/create")
def create_campaign():
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    official_sound = (data.get("official_sound") or "").strip()
    start_date = (data.get("start_date") or "").strip() or str(date.today())
    budget_raw = (data.get("budget") or "0")

    if not title:
        return jsonify({"error": "Title is required."}), 400

    try:
        budget = float(budget_raw)
    except (ValueError, TypeError):
        return jsonify({"error": "Budget must be a number."}), 400

    artist, song = "", ""
    if " - " in title:
        artist, song = [x.strip() for x in title.split(" - ", 1)]

    slug = slugify(title)

    meta = {
        "title": title, "name": title, "slug": slug,
        "artist": artist, "song": song,
        "official_sound": official_sound,
        "sound_id": extract_sound_id(official_sound) if official_sound else "",
        "start_date": start_date, "budget": budget,
        "status": "active", "platform": "tiktok",
        "created_at": datetime.now().isoformat(),
        "stats": {"total_views": 0, "total_likes": 0},
    }

    if _db.is_active():
        if _db.campaign_exists(slug):
            return jsonify({"error": f"Campaign '{slug}' already exists."}), 409
        _db.save_campaign(slug, meta)
        _db.save_creators(slug, [])
    else:
        campaign_dir = ACTIVE_DIR / slug
        if campaign_dir.exists():
            return jsonify({"error": f"Campaign '{slug}' already exists."}), 409
        campaign_dir.mkdir(parents=True, exist_ok=True)
        (campaign_dir / "links").mkdir(exist_ok=True)
        save_json(campaign_dir / "campaign.json", meta)
        save_creators(campaign_dir, [])

    return jsonify({"ok": True, "slug": slug, "message": f"Created campaign: {title}"}), 201


# -------------------------------------------------------------------
# 3. POST /api/campaign/<slug>/edit  -- update campaign metadata
# -------------------------------------------------------------------
@campaigns_bp.post("/api/campaign/<slug>/edit")
def edit_campaign(slug: str):
    if _db.is_active():
        meta = _db.get_campaign(slug)
        campaign_dir = None
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": "Campaign not found."}), 404
        meta = load_json(campaign_dir / "campaign.json")

    if not meta:
        return jsonify({"error": "Campaign not found."}), 404

    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    sound_id_raw = (data.get("sound_id") or "").strip()
    start_date = (data.get("start_date") or "").strip()
    budget_raw = (data.get("budget") or "").strip() if isinstance(data.get("budget"), str) else data.get("budget")

    if title:
        meta["title"] = title
        meta["name"] = title
        if " - " in title:
            artist, song = [x.strip() for x in title.split(" - ", 1)]
            meta["artist"] = artist
            meta["song"] = song

    if sound_id_raw:
        meta["official_sound"] = sound_id_raw
        meta["sound_id"] = extract_sound_id(sound_id_raw)

    # Save additional sounds
    additional = data.get("additional_sounds", [])
    if isinstance(additional, list):
        meta["additional_sounds"] = [s.strip() for s in additional if s and s.strip()]

    if start_date:
        meta["start_date"] = start_date

    if budget_raw is not None and budget_raw != "":
        try:
            meta["budget"] = float(budget_raw)
        except (ValueError, TypeError):
            pass

    completion_status = data.get("completion_status")
    if completion_status in ("none", "booked", "completed"):
        meta["completion_status"] = completion_status

    cobrand_link = (data.get("cobrand_link") or "").strip()
    meta["cobrand_link"] = cobrand_link

    if _db.is_active():
        _db.save_campaign(slug, meta)
    else:
        save_json(campaign_dir / "campaign.json", meta)

    return jsonify({"ok": True, "slug": slug, "message": "Campaign updated."})


# -------------------------------------------------------------------
# 4. GET /api/campaign/<slug>  -- full campaign detail
# -------------------------------------------------------------------
@campaigns_bp.get("/api/campaign/<slug>")
def campaign_detail(slug: str):
    """Full campaign detail with creators and matched videos."""
    if _db.is_active():
        meta = _db.get_campaign(slug)
        if not meta:
            return jsonify({"error": "Campaign not found"}), 404
        creators = _db.get_creators(slug)
        matched_videos = _db.get_matched_videos(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": "Campaign not found"}), 404
        meta = load_json(campaign_dir / "campaign.json")
        creators = load_creators(campaign_dir)
        matched_videos = load_matched_videos(campaign_dir)

    active = [c for c in creators if c.get("status", "active") != "removed"]
    active.sort(key=lambda c: c.get("username", ""))
    budget = calc_budget(meta, creators)
    stats = calc_stats(meta, creators)

    return jsonify({
        "slug": slug,
        "title": campaign_title(meta),
        "meta": meta,
        "artist": meta.get("artist", ""),
        "song": meta.get("song", ""),
        "sound_id": meta.get("sound_id", ""),
        "official_sound": meta.get("official_sound", ""),
        "additional_sounds": meta.get("additional_sounds", []),
        "cobrand_link": meta.get("cobrand_link", ""),
        "cobrand_share_url": meta.get("cobrand_share_url", ""),
        "cobrand_upload_url": meta.get("cobrand_upload_url", ""),
        "start_date": meta.get("start_date", ""),
        "budget": budget,
        "stats": stats,
        "platform": meta.get("platform", "tiktok"),
        "status": meta.get("status", "active"),
        "source": meta.get("source", "manual"),
        "label": meta.get("label", ""),
        "round": meta.get("round", ""),
        "campaign_stage": meta.get("campaign_stage", ""),
        "project_lead": meta.get("project_lead", []),
        "client_email": meta.get("client_email", ""),
        "platform_split": meta.get("platform_split", {}),
        "content_types": meta.get("content_types", []),
        "creators": [
            {
                "username": c.get("username", ""),
                "posts_owed": int(c.get("posts_owed", 0)),
                "posts_done": int(c.get("posts_done", 0)),
                "posts_matched": int(c.get("posts_matched", 0)),
                "total_rate": float(c.get("total_rate", 0)),
                "per_post_rate": float(c.get("per_post_rate", 0)),
                "paid": c.get("paid", "no"),
                "payment_date": c.get("payment_date", ""),
                "paypal_email": c.get("paypal_email", ""),
                "platform": c.get("platform", "tiktok"),
                "added_date": c.get("added_date", ""),
                "status": c.get("status", "active"),
                "notes": c.get("notes", ""),
            }
            for c in active
        ],
        "matched_videos": matched_videos,
        "cobrand_share_url": meta.get("cobrand_share_url", ""),
        "cobrand_upload_url": meta.get("cobrand_upload_url", ""),
        "tracker_campaign_id": meta.get("tracker_campaign_id", ""),
        "tracker_url": meta.get("tracker_url", ""),
        "platform": meta.get("platform", "tiktok"),
        "status": meta.get("status", "active"),
        "source": meta.get("source", "manual"),
        "label": meta.get("label", ""),
        "round": meta.get("round", ""),
        "campaign_stage": meta.get("campaign_stage", ""),
        "project_lead": meta.get("project_lead", []),
        "client_email": meta.get("client_email", ""),
        "platform_split": meta.get("platform_split", {}),
        "content_types": meta.get("content_types", []),
    })


# -------------------------------------------------------------------
# 5. POST /api/campaign/<slug>/refresh  -- scrape & match
# -------------------------------------------------------------------
@campaigns_bp.post("/api/campaign/<slug>/refresh")
def refresh_stats(slug: str):
    """Scrape creator accounts and match videos to the campaign sound."""
    import traceback as _tb
    try:
        return _refresh_stats_inner(slug)
    except Exception as e:
        return jsonify({"error": str(e), "traceback": _tb.format_exc()}), 500


def _refresh_stats_inner(slug: str):
    if _db.is_active():
        meta = _db.get_campaign(slug)
        if not meta:
            return jsonify({"error": "Campaign not found."}), 404
        creators = _db.get_creators(slug)
        campaign_dir = None  # not used in DB mode
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": "Campaign not found."}), 404
        meta = load_json(campaign_dir / "campaign.json")
        creators = load_creators(campaign_dir)

    active_creators = [c for c in creators if c.get("status", "active") != "removed"]

    if not active_creators:
        return jsonify({"error": "No creators to scrape."}), 400

    sound_id_raw = meta.get("sound_id") or meta.get("official_sound", "")
    song = meta.get("song", "")
    artist = meta.get("artist", "")
    start_date_str = meta.get("start_date", "")

    # Parse start date
    scrape_start = None
    if start_date_str:
        try:
            scrape_start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    # Detect if sound_id is actually the video ID from official_sound URL
    official_sound_url = meta.get("official_sound", "")
    if (sound_id_raw and re.match(r"^\d{10,}$", sound_id_raw)
            and official_sound_url and sound_id_raw in official_sound_url):
        html_id, html_title = extract_sound_id_from_html(official_sound_url)
        if html_id and html_id != sound_id_raw:
            sound_id_raw = html_id
            meta["sound_id"] = html_id
            _save_meta(slug, meta, campaign_dir)
        # Auto-populate artist/song from HTML title if empty
        if not artist or not song:
            if html_title and not song:
                song = html_title
                meta["song"] = song
                _save_meta(slug, meta, campaign_dir)

    # Resolve the sound ID -- if it's a URL, extract the real numeric ID
    sound_id = sound_id_raw
    ref_song_title = None
    if sound_id_raw and not re.match(r"^\d{10,}$", sound_id_raw):
        resolved_id = extract_sound_id(sound_id_raw)
        if resolved_id and resolved_id != sound_id_raw:
            sound_id = resolved_id
            meta["sound_id"] = resolved_id
            _save_meta(slug, meta, campaign_dir)

    # If sound_id is still a URL (couldn't resolve), try HTML extraction
    if sound_id and "tiktok.com/" in sound_id:
        resolved_url = sound_id
        if "/t/" in resolved_url:
            resolved_url = resolve_tiktok_short_url(resolved_url)
        if "/video/" in resolved_url or "/photo/" in resolved_url:
            html_id, html_title = extract_sound_id_from_html(resolved_url)
            if html_id:
                sound_id = html_id
                ref_song_title = html_title
                meta["sound_id"] = html_id
                _save_meta(slug, meta, campaign_dir)

    # Resolve additional sounds
    additional_sounds = meta.get("additional_sounds", [])
    resolved_additional = []
    for extra_raw in additional_sounds:
        extra_id = extra_raw
        if extra_raw and not re.match(r"^\d{10,}$", extra_raw):
            resolved = extract_sound_id(extra_raw)
            if resolved:
                extra_id = resolved
        # HTML fallback
        if extra_id and "tiktok.com/" in extra_id:
            url = extra_id
            if "/t/" in url:
                url = resolve_tiktok_short_url(url)
            if "/video/" in url or "/photo/" in url:
                html_id, html_title = extract_sound_id_from_html(url)
                if html_id:
                    extra_id = html_id
                    if html_title:
                        ref_song_title = ref_song_title or html_title
        resolved_additional.append(extra_id)

    # Build sound matching sets
    sound_ids: set = set()
    sound_keys: set = set()
    if sound_id and re.match(r"^\d{10,}$", sound_id):
        sound_ids.add(sound_id)
    for extra_id in resolved_additional:
        if extra_id and re.match(r"^\d{10,}$", extra_id):
            sound_ids.add(extra_id)

    # Add exact song+artist key
    if song and artist:
        sound_keys.add(f"{song.lower().strip()} - {artist.lower().strip()}")

    # Add fuzzy song keys
    def _core_song_name(s: str) -> str:
        s = re.sub(r"\s*\(feat\..*?\)", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*\(ft\..*?\)", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*feat\..*$", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s+promo\s*$", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s+remix\s*$", "", s, flags=re.IGNORECASE)
        return s.strip().lower()

    if song:
        core_song = _core_song_name(song)
        if artist:
            sound_keys.add(f"{core_song} - {artist.lower().strip()}")
    if ref_song_title and artist:
        core_ref = _core_song_name(ref_song_title)
        sound_keys.add(f"{core_ref} - {artist.lower().strip()}")

    if not sound_ids and not sound_keys:
        return jsonify({"error": "No sound ID or song/artist to match against."}), 400

    try:
        from src.scrapers.master_tracker import (
            scrape_tiktok_account,
            extract_sound_ids_parallel,
            match_video_to_sounds,
        )
    except ImportError as e:
        return jsonify({"error": f"Could not import scraper: {e}"}), 500

    # Scrape all creator accounts in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_videos: List[Dict] = []
    accounts_scraped = 0
    errors: List[str] = []

    tiktok_creators = [c for c in active_creators if c.get("platform", "tiktok") == "tiktok"]

    def _scrape_one(username):
        """Scrape a single creator with retry."""
        for attempt in range(2):
            try:
                videos = scrape_tiktok_account(
                    f"@{username}",
                    start_date=scrape_start,
                    limit=500,
                    use_cache=True,
                )
                return username, videos, None
            except Exception as e:
                if attempt == 0:
                    continue  # retry once
                return username, [], str(e)
        return username, [], "max retries"

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_scrape_one, c.get("username", "")): c
            for c in tiktok_creators
        }
        for future in as_completed(futures):
            username, videos, error = future.result()
            if error:
                errors.append(f"@{username}: {error}")
            else:
                all_videos.extend(videos)
                accounts_scraped += 1

    # Extract sound IDs for videos that don't have them
    tiktok_needing = [v for v in all_videos if not v.get("extracted_sound_id")]
    if tiktok_needing:
        try:
            enhanced = extract_sound_ids_parallel(tiktok_needing, max_workers=10)
            enhanced_dict = {v["url"]: v for v in enhanced}
            all_videos = [enhanced_dict.get(v.get("url"), v) for v in all_videos]
        except Exception:
            pass

    # Match videos using shared matching logic
    from campaign_manager.services.matching import (
        core_song_name as _csn, match_videos, merge_matched_videos,
        update_creator_post_counts,
    )

    core_song_words: set = set()
    if song:
        core_song_words = {w for w in _csn(song).split() if len(w) > 2}
    if ref_song_title:
        core_song_words |= {w for w in _csn(ref_song_title).split() if len(w) > 2}

    matched = match_videos(all_videos, sound_ids, sound_keys, core_song_words, artist, match_fn=match_video_to_sounds)

    # Merge — updates view/like counts for existing matches + adds new ones
    if _db.is_active():
        existing = _db.get_matched_videos(slug)
    else:
        existing = load_matched_videos(campaign_dir)

    all_matched, new_count = merge_matched_videos(existing, matched)

    # Serialize matched videos (datetime -> string)
    for v in all_matched:
        if isinstance(v.get("timestamp"), datetime):
            v["timestamp"] = v["timestamp"].isoformat()

    if _db.is_active():
        _db.replace_matched_videos(slug, all_matched)
    else:
        save_matched_videos(campaign_dir, all_matched)

    # Update stats (now with fresh view counts!)
    total_views = sum(int(v.get("views", 0)) for v in all_matched)
    total_likes = sum(int(v.get("likes", 0)) for v in all_matched)
    stats = meta.get("stats", {})
    stats["total_views"] = total_views
    stats["total_likes"] = total_likes
    stats["last_scrape"] = datetime.now().isoformat()
    meta["stats"] = stats
    _save_meta(slug, meta, campaign_dir)

    # Update creator post counts using shared logic
    if _db.is_active():
        all_creators = _db.get_creators(slug)
    else:
        all_creators = load_creators(campaign_dir)
    all_creators = update_creator_post_counts(all_creators, all_matched)
    if _db.is_active():
        _db.save_creators(slug, all_creators)
    else:
        save_creators(campaign_dir, all_creators)

    # Build feedback
    feedback = (
        f"Scrape complete: {accounts_scraped} accounts scraped, "
        f"{len(all_videos)} videos checked, "
        f"{new_count} new matches found, "
        f"{len(all_matched)} total matched videos. "
        f"Views: {total_views:,} | Likes: {total_likes:,}"
    )
    if errors:
        feedback += f" | {len(errors)} error(s): {'; '.join(errors[:3])}"

    # Save scrape log
    scrape_log = {
        "last_scrape": datetime.now().isoformat(),
        "accounts_scraped": accounts_scraped,
        "videos_checked": len(all_videos),
        "new_matches": new_count,
        "total_matches": len(all_matched),
    }
    if _db.is_active():
        _db.save_scrape_log(slug, scrape_log)
    else:
        save_json(campaign_dir / "scrape_log.json", scrape_log)

    return jsonify({
        "ok": True,
        "slug": slug,
        "message": feedback,
        "accounts_scraped": accounts_scraped,
        "videos_checked": len(all_videos),
        "new_matches": new_count,
        "total_matches": len(all_matched),
        "total_views": total_views,
        "total_likes": total_likes,
        "errors": errors,
    })


# -------------------------------------------------------------------
# 6. GET /api/campaign/<slug>/links  -- matched video links
# -------------------------------------------------------------------
@campaigns_bp.get("/api/campaign/<slug>/links")
def campaign_links(slug: str):
    """Return all matched video links for a campaign."""
    if _db.is_active():
        meta = _db.get_campaign(slug)
        if not meta:
            return jsonify({"error": "Campaign not found."}), 404
        matched = _db.get_matched_videos(slug)
        scrape_log = _db.get_scrape_log(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": "Campaign not found."}), 404
        meta = load_json(campaign_dir / "campaign.json")
        matched = load_matched_videos(campaign_dir)
        scrape_log = load_json(campaign_dir / "scrape_log.json")

    return jsonify({
        "slug": slug,
        "title": campaign_title(meta),
        "videos": matched,
        "scrape_log": scrape_log,
    })


# -------------------------------------------------------------------
# 7. POST /api/campaign/<slug>/creator/add  -- add a creator
# -------------------------------------------------------------------
@campaigns_bp.post("/api/campaign/<slug>/creator/add")
def add_creator(slug: str):
    if _db.is_active():
        if not _db.campaign_exists(slug):
            return jsonify({"error": "Campaign not found."}), 404
        campaign_dir = None
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": "Campaign not found."}), 404

    data = request.get_json(silent=True) or {}

    username = (data.get("username") or "").strip().lstrip("@").rstrip("/")
    posts_owed_raw = data.get("posts_owed", 0)
    total_rate_raw = data.get("total_rate", 0)
    paypal = (data.get("paypal_email") or "").strip()
    platform = (data.get("platform") or "tiktok").strip() or "tiktok"
    niches = data.get("niches", [])

    # Auto-fill PayPal from memory if not provided
    if not paypal and username:
        paypal = recall_paypal(username)

    if not username:
        return jsonify({"error": "Username is required."}), 400

    try:
        posts_owed = int(posts_owed_raw)
        total_rate = float(total_rate_raw)
    except (ValueError, TypeError):
        return jsonify({"error": "Posts owed must be int and rate must be number."}), 400

    if _db.is_active():
        creators = _db.get_creators(slug)
    else:
        creators = load_creators(campaign_dir)

    if any(c.get("username") == username and c.get("status", "active") != "removed" for c in creators):
        return jsonify({"error": f"@{username} already exists."}), 409

    # Remove any previously-removed entries for this username to avoid
    # unique constraint violations on (campaign_id, username).
    creators = [c for c in creators if not (c.get("username") == username and c.get("status") == "removed")]

    per_post = round(total_rate / posts_owed, 2) if posts_owed > 0 else 0.0
    creators.append({
        "username": username, "posts_owed": posts_owed,
        "posts_done": 0, "posts_matched": 0,
        "total_rate": total_rate, "per_post_rate": per_post,
        "paypal_email": paypal, "paid": "no", "payment_date": "",
        "platform": platform, "added_date": str(date.today()),
        "status": "active", "notes": "", "niches": niches,
    })

    try:
        if _db.is_active():
            _db.save_creators(slug, creators)
        else:
            save_creators(campaign_dir, creators)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"DB error: {exc}"}), 500

    if paypal:
        remember_paypal(username, paypal)

    return jsonify({"ok": True, "username": username, "message": f"Added @{username}"}), 201


# -------------------------------------------------------------------
# 8. POST /api/campaign/<slug>/creator/<username>/edit
# -------------------------------------------------------------------
@campaigns_bp.post("/api/campaign/<slug>/creator/<username>/edit")
def edit_creator(slug: str, username: str):
    if _db.is_active():
        creators = _db.get_creators(slug)
        campaign_dir = None
    else:
        campaign_dir = ACTIVE_DIR / slug
        creators = load_creators(campaign_dir)

    data = request.get_json(silent=True) or {}

    new_username = (data.get("new_username") or "").strip().lstrip("@")
    posts_owed_raw = data.get("posts_owed")
    total_rate_raw = data.get("total_rate")
    paypal = (data.get("paypal_email") or "").strip()
    notes = (data.get("notes") or "").strip()
    niches = data.get("niches")

    if posts_owed_raw is None or total_rate_raw is None:
        return jsonify({"error": "posts_owed and total_rate are required."}), 400

    try:
        posts_owed = int(posts_owed_raw)
        total_rate = float(total_rate_raw)
        if posts_owed < 0 or total_rate < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid values."}), 400

    found = False
    for c in creators:
        if c.get("username") == username and c.get("status", "active") != "removed":
            if new_username and new_username != username:
                c["username"] = new_username
            c["posts_owed"] = posts_owed
            c["total_rate"] = total_rate
            c["per_post_rate"] = round(total_rate / posts_owed, 2) if posts_owed > 0 else 0.0
            c["paypal_email"] = paypal
            c["notes"] = notes
            if niches is not None:
                c["niches"] = niches
            found = True
            break

    if not found:
        return jsonify({"error": f"Creator @{username} not found."}), 404

    if _db.is_active():
        _db.save_creators(slug, creators)
    else:
        save_creators(campaign_dir, creators)

    display_name = new_username if new_username and new_username != username else username
    if paypal:
        remember_paypal(display_name, paypal)

    return jsonify({"ok": True, "username": display_name, "message": f"Updated @{display_name}"})


# -------------------------------------------------------------------
# 9. POST /api/campaign/<slug>/creator/<username>/toggle-paid
# -------------------------------------------------------------------
@campaigns_bp.post("/api/campaign/<slug>/creator/<username>/toggle-paid")
def toggle_paid(slug: str, username: str):
    if _db.is_active():
        creators = _db.get_creators(slug)
        campaign_dir = None
    else:
        campaign_dir = ACTIVE_DIR / slug
        creators = load_creators(campaign_dir)

    new_status = "no"
    found = False
    for c in creators:
        if c.get("username") == username:
            now_paid = str(c.get("paid", "no")).lower() != "yes"
            c["paid"] = "yes" if now_paid else "no"
            c["payment_date"] = str(date.today()) if now_paid else ""
            new_status = c["paid"]
            found = True
            break

    if not found:
        return jsonify({"error": f"Creator @{username} not found."}), 404

    if _db.is_active():
        _db.save_creators(slug, creators)
    else:
        save_creators(campaign_dir, creators)

    return jsonify({"ok": True, "paid": new_status, "username": username})


# -------------------------------------------------------------------
# 10. POST /api/campaign/<slug>/creator/<username>/remove
# -------------------------------------------------------------------
@campaigns_bp.post("/api/campaign/<slug>/creator/<username>/remove")
def remove_creator(slug: str, username: str):
    if _db.is_active():
        creators = _db.get_creators(slug)
        campaign_dir = None
    else:
        campaign_dir = ACTIVE_DIR / slug
        creators = load_creators(campaign_dir)

    found = False
    for c in creators:
        if c.get("username") == username:
            c["status"] = "removed"
            found = True
            break

    if not found:
        return jsonify({"error": f"Creator @{username} not found."}), 404

    if _db.is_active():
        _db.save_creators(slug, creators)
    else:
        save_creators(campaign_dir, creators)

    return jsonify({"ok": True, "username": username, "message": f"Removed @{username}"})


# -------------------------------------------------------------------
# 10b. POST /api/campaign/<slug>/creator/remove  -- body-based remove
#      (handles usernames with slashes or other URL-unsafe chars)
# -------------------------------------------------------------------
@campaigns_bp.post("/api/campaign/<slug>/creator/remove")
def remove_creator_by_body(slug: str):
    data = request.get_json(silent=True) or {}
    username = data.get("username", "")
    if not username:
        return jsonify({"error": "Username is required."}), 400

    if _db.is_active():
        creators = _db.get_creators(slug)
        campaign_dir = None
    else:
        campaign_dir = ACTIVE_DIR / slug
        creators = load_creators(campaign_dir)

    found = False
    for c in creators:
        if c.get("username") == username:
            c["status"] = "removed"
            found = True
            break

    if not found:
        return jsonify({"error": f"Creator @{username} not found."}), 404

    if _db.is_active():
        _db.save_creators(slug, creators)
    else:
        save_creators(campaign_dir, creators)

    return jsonify({"ok": True, "username": username, "message": f"Removed @{username}"})


# -------------------------------------------------------------------
# 11. GET /api/paypal/<username>  -- PayPal lookup
# -------------------------------------------------------------------
@campaigns_bp.get("/api/paypal/<username>")
def api_paypal(username: str):
    return jsonify({"paypal": recall_paypal(username)})


# -------------------------------------------------------------------
# 12. GET /api/campaign/<slug>/budget  -- quick budget lookup
# -------------------------------------------------------------------
@campaigns_bp.get("/api/campaign/<slug>/budget")
def api_campaign_budget(slug: str):
    """Quick budget lookup -- designed for Slack responses."""
    if _db.is_active():
        meta = _db.get_campaign(slug)
        if not meta:
            return jsonify({"error": "Campaign not found"}), 404
        creators = _db.get_creators(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": "Campaign not found"}), 404
        meta = load_json(campaign_dir / "campaign.json")
        creators = load_creators(campaign_dir)

    budget = calc_budget(meta, creators)

    return jsonify({
        "title": campaign_title(meta),
        "slug": slug,
        "budget_total": budget["total"],
        "budget_booked": budget["booked"],
        "budget_paid": budget["paid"],
        "budget_remaining": budget["left"],
        "budget_pct_used": budget["pct"],
        "message": (
            f"{campaign_title(meta)}: ${budget['total']:,.0f} budget, "
            f"${budget['booked']:,.0f} booked, ${budget['left']:,.0f} remaining "
            f"({budget['pct']}% used)"
        ),
    })


# -------------------------------------------------------------------
# 13. GET /api/search  -- fuzzy campaign search
# -------------------------------------------------------------------
@campaigns_bp.get("/api/search")
def api_search():
    """Fuzzy search campaigns by name/artist/song. Returns best matches."""
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify({"error": "Missing ?q= parameter"}), 400

    campaigns = get_campaigns()
    tokens = q.split()

    scored = []
    for c in campaigns:
        blob = " ".join([
            c["title"],
            c["meta"].get("artist", ""),
            c["meta"].get("song", ""),
            c["slug"],
        ]).lower()
        hits = sum(1 for t in tokens if t in blob)
        if hits > 0:
            scored.append((hits, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [_campaign_summary(s[1]) for s in scored[:5]]
    return jsonify({"query": q, "results": results})


# -------------------------------------------------------------------
# Cobrand Integration
# -------------------------------------------------------------------

@campaigns_bp.get("/api/campaign/<slug>/cobrand")
def get_cobrand_stats(slug: str):
    """Fetch live stats from Cobrand for this campaign."""
    from campaign_manager.services.cobrand import fetch_cobrand_stats

    if _db.is_active():
        meta = _db.get_campaign(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": "Campaign not found"}), 404
        meta = load_json(campaign_dir / "campaign.json")

    if not meta:
        return jsonify({"error": "Campaign not found"}), 404

    share_url = meta.get("cobrand_share_url", "")
    if not share_url:
        return jsonify({"error": "No Cobrand tracking link configured for this campaign"}), 404

    stats = fetch_cobrand_stats(share_url)
    if stats is None:
        return jsonify({"error": "Failed to fetch Cobrand stats"}), 502

    # Cache the stats in the database
    if _db.is_active():
        _db.update_cobrand_cache(slug, stats)

    return jsonify(stats)


@campaigns_bp.get("/api/campaign/<slug>/cobrand/raw")
def get_cobrand_raw(slug: str):
    """Debug: dump the full raw __NEXT_DATA__ promotion object from Cobrand."""
    if _db.is_active():
        meta = _db.get_campaign(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": "Campaign not found"}), 404
        meta = load_json(campaign_dir / "campaign.json")

    if not meta:
        return jsonify({"error": "Campaign not found"}), 404

    share_url = meta.get("cobrand_share_url", "")
    if not share_url:
        return jsonify({"error": "No Cobrand tracking link configured"}), 404

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        resp = _requests.get(share_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return jsonify({"error": f"Cobrand returned {resp.status_code}"}), 502

        pattern = r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>'
        matches = re.findall(pattern, resp.text, re.DOTALL)
        if not matches:
            return jsonify({"error": "No __NEXT_DATA__ found in page"}), 502

        data = json.loads(matches[0])
        page_props = data.get("props", {}).get("pageProps", {})
        promotion = page_props.get("promotion")
        if not promotion:
            return jsonify({"error": "No promotion object in __NEXT_DATA__", "keys": list(page_props.keys())}), 502

        # Return full promotion with all keys listed at the top for reference
        return jsonify({
            "top_level_keys": sorted(promotion.keys()),
            "promotion": promotion,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@campaigns_bp.put("/api/campaign/<slug>/cobrand")
def set_cobrand_links(slug: str):
    """Set or update Cobrand share URL and upload URL for a campaign."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    share_url = (data.get("share_url") or "").strip()
    upload_url = (data.get("upload_url") or "").strip()

    if not share_url and not upload_url:
        return jsonify({"error": "Provide share_url and/or upload_url"}), 400

    if _db.is_active():
        if not _db.campaign_exists(slug):
            return jsonify({"error": "Campaign not found"}), 404

        meta = _db.get_campaign(slug)
        if share_url:
            meta["cobrand_share_url"] = share_url
        if upload_url:
            meta["cobrand_upload_url"] = upload_url
        _db.save_campaign(slug, meta)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            return jsonify({"error": "Campaign not found"}), 404
        meta = load_json(campaign_dir / "campaign.json")
        if share_url:
            meta["cobrand_share_url"] = share_url
        if upload_url:
            meta["cobrand_upload_url"] = upload_url
        save_json(campaign_dir / "campaign.json", meta)

    return jsonify({"ok": True, "message": "Cobrand links updated"})


# -------------------------------------------------------------------
# Creator Database
# -------------------------------------------------------------------

def _get_all_campaigns_data():
    """Return all campaigns (active + completed) with creators and matched videos.

    Works in both DB and file-based mode.  Returns a list of dicts, each with
    keys: slug, meta, creators, matched_videos.
    """
    results = []

    if _db.is_active():
        # Query all campaigns regardless of status
        for status in ("active", "completed"):
            metas = _db.list_campaigns(status=status)
            for meta in metas:
                slug = meta["slug"]
                creators = _db.get_creators(slug)
                matched_videos = _db.get_matched_videos(slug)
                results.append({
                    "slug": slug,
                    "meta": meta,
                    "creators": creators,
                    "matched_videos": matched_videos,
                })
    else:
        ensure_dirs()
        for parent_dir in (ACTIVE_DIR, COMPLETED_DIR):
            if not parent_dir.exists():
                continue
            for d in parent_dir.iterdir():
                if not d.is_dir():
                    continue
                meta = load_json(d / "campaign.json")
                if not meta:
                    continue
                creators = load_creators(d)
                matched_videos = load_matched_videos(d)
                results.append({
                    "slug": d.name,
                    "meta": meta,
                    "creators": creators,
                    "matched_videos": matched_videos,
                })

    return results


@campaigns_bp.get("/api/creators")
def list_creators():
    """List all unique creators with aggregated stats across campaigns."""
    all_campaigns = _get_all_campaigns_data()

    # Aggregate by username (case-insensitive)
    creator_map: Dict[str, Dict] = {}

    for camp in all_campaigns:
        slug = camp["slug"]
        meta = camp["meta"]
        title = campaign_title(meta)
        creators = camp["creators"]
        matched_videos = camp["matched_videos"]

        # Build a views-by-account map for this campaign
        views_by_account: Dict[str, int] = {}
        for v in matched_videos:
            acct = (v.get("account", "") or "").lstrip("@").lower()
            if acct:
                views_by_account[acct] = views_by_account.get(acct, 0) + int(v.get("views", 0) or 0)

        for c in creators:
            if c.get("status", "active") == "removed":
                continue

            uname = (c.get("username", "") or "").strip()
            if not uname:
                continue
            key = uname.lower()

            if key not in creator_map:
                creator_map[key] = {
                    "username": uname,
                    "campaigns_count": 0,
                    "total_posts_owed": 0,
                    "total_posts_done": 0,
                    "total_spend": 0.0,
                    "total_payout": 0.0,
                    "total_views": 0,
                    "platform": c.get("platform", "tiktok"),
                    "paypal_email": c.get("paypal_email", ""),
                    "niches": [],
                    "_platforms": [],
                }

            entry = creator_map[key]
            entry["campaigns_count"] += 1
            entry["total_posts_owed"] += int(c.get("posts_owed", 0) or 0)
            entry["total_posts_done"] += int(c.get("posts_done", 0) or 0)
            entry["total_spend"] += float(c.get("total_rate", 0) or 0)
            if str(c.get("paid", "no")).lower() == "yes":
                entry["total_payout"] += float(c.get("total_rate", 0) or 0)
            entry["total_views"] += views_by_account.get(key, 0)
            entry["_platforms"].append(c.get("platform", "tiktok"))

            # Keep latest non-empty paypal
            pp = (c.get("paypal_email", "") or "").strip()
            if pp:
                entry["paypal_email"] = pp

            # Merge niches (union across campaigns)
            for n in (c.get("niches") or []):
                if n and n not in entry["niches"]:
                    entry["niches"].append(n)

    # Finalize: compute avg_cpm, pick most common platform, remove internals
    results = []
    for entry in creator_map.values():
        platforms = entry.pop("_platforms", [])
        if platforms:
            entry["platform"] = max(set(platforms), key=platforms.count)

        if entry["total_views"] > 0:
            entry["avg_cpm"] = round(
                (entry["total_spend"] / entry["total_views"]) * 1_000, 2
            )
        else:
            entry["avg_cpm"] = None

        entry["total_spend"] = round(entry["total_spend"], 2)
        entry["total_payout"] = round(entry["total_payout"], 2)
        results.append(entry)

    # Sort by total_spend descending
    results.sort(key=lambda x: x["total_spend"], reverse=True)
    return jsonify(results)


@campaigns_bp.get("/api/creators/<username>")
def creator_profile(username: str):
    """Full creator profile with cross-campaign data."""
    all_campaigns = _get_all_campaigns_data()
    uname_lower = username.lower()

    campaigns_list = []
    all_videos = []
    total_posts_owed = 0
    total_posts_done = 0
    total_spend = 0.0
    total_payout = 0.0
    total_views = 0
    total_likes = 0
    platforms = []
    paypal_email = ""

    for camp in all_campaigns:
        slug = camp["slug"]
        meta = camp["meta"]
        title = campaign_title(meta)
        creators = camp["creators"]
        matched_videos = camp["matched_videos"]

        # Find this creator in the campaign
        creator_entry = None
        for c in creators:
            if (c.get("username", "") or "").lower() == uname_lower and c.get("status", "active") != "removed":
                creator_entry = c
                break

        if not creator_entry:
            continue

        posts_owed = int(creator_entry.get("posts_owed", 0) or 0)
        posts_done = int(creator_entry.get("posts_done", 0) or 0)
        rate = float(creator_entry.get("total_rate", 0) or 0)
        paid = creator_entry.get("paid", "no")
        platform = creator_entry.get("platform", "tiktok")
        platforms.append(platform)

        total_posts_owed += posts_owed
        total_posts_done += posts_done
        total_spend += rate
        if str(paid).lower() == "yes":
            total_payout += rate

        pp = (creator_entry.get("paypal_email", "") or "").strip()
        if pp:
            paypal_email = pp

        # Gather matched videos for this creator in this campaign
        campaign_views = 0
        for v in matched_videos:
            acct = (v.get("account", "") or "").lstrip("@").lower()
            if acct == uname_lower:
                views = int(v.get("views", 0) or 0)
                likes = int(v.get("likes", 0) or 0)
                total_views += views
                total_likes += likes
                campaign_views += views
                all_videos.append({
                    "url": v.get("url", ""),
                    "campaign_slug": slug,
                    "campaign_title": title,
                    "views": views,
                    "likes": likes,
                    "upload_date": v.get("upload_date", ""),
                })

        campaigns_list.append({
            "slug": slug,
            "title": title,
            "artist": meta.get("artist", ""),
            "song": meta.get("song", ""),
            "posts_owed": posts_owed,
            "posts_done": posts_done,
            "total_rate": rate,
            "paid": paid,
            "payment_date": creator_entry.get("payment_date", ""),
            "status": creator_entry.get("status", "active"),
            "notes": creator_entry.get("notes", ""),
        })

    if not campaigns_list:
        return jsonify({"error": f"Creator @{username} not found in any campaign."}), 404

    platform = "tiktok"
    if platforms:
        platform = max(set(platforms), key=platforms.count)

    avg_cpm = None
    if total_views > 0:
        avg_cpm = round((total_spend / total_views) * 1_000, 2)

    return jsonify({
        "username": username,
        "platform": platform,
        "paypal_email": paypal_email,
        "stats": {
            "campaigns_count": len(campaigns_list),
            "total_posts_owed": total_posts_owed,
            "total_posts_done": total_posts_done,
            "total_spend": round(total_spend, 2),
            "total_payout": round(total_payout, 2),
            "total_views": total_views,
            "total_likes": total_likes,
            "avg_cpm": avg_cpm,
        },
        "campaigns": campaigns_list,
        "videos": all_videos,
    })


# ---------------------------------------------------------------------------
# TidesTracker integration
# ---------------------------------------------------------------------------

@campaigns_bp.route("/api/campaign/<slug>/create-tracker", methods=["POST"])
def create_tracker(slug: str):
    """Create a TidesTracker campaign for this campaign's Cobrand share link.

    Calls the TidesTracker API to create a tracking campaign, then stores
    the returned campaign ID back on the Campaign record.

    Requires:
      - Campaign must have a cobrand_share_url set
      - TIDESTRACKER_API_URL and TIDESTRACKER_SERVICE_KEY env vars configured
    """
    # Load campaign
    if _db.is_active():
        meta = _db.get_campaign(slug)
    else:
        cdir = ACTIVE_DIR / slug
        if not cdir.exists():
            cdir = COMPLETED_DIR / slug
        if not (cdir / "campaign.json").exists():
            return jsonify({"error": "Campaign not found"}), 404
        meta = load_json(cdir / "campaign.json")

    if not meta:
        return jsonify({"error": "Campaign not found"}), 404

    cobrand_share_url = meta.get("cobrand_share_url", "")
    if not cobrand_share_url:
        return jsonify({"error": "Campaign has no Cobrand share URL set. Add one first."}), 400

    # Check if tracker already exists
    tracker_id = meta.get("tracker_campaign_id", "")
    if tracker_id:
        return jsonify({
            "ok": True,
            "message": "Tracker already exists",
            "tracker_campaign_id": tracker_id,
            "tracker_url": meta.get("tracker_url", ""),
        })

    # Get TidesTracker config
    tracker_api = current_app.config.get("TIDESTRACKER_API_URL", "")
    tracker_key = current_app.config.get("TIDESTRACKER_SERVICE_KEY", "")
    tracker_base = current_app.config.get("TIDESTRACKER_BASE_URL", "")

    if not tracker_api or not tracker_key:
        return jsonify({"error": "TidesTracker not configured. Set TIDESTRACKER_API_URL and TIDESTRACKER_SERVICE_KEY."}), 500

    # Build tracker campaign name from campaign metadata
    title = meta.get("title", slug)
    artist = meta.get("artist", "")
    song = meta.get("song", "")
    tracker_name = title
    if artist and song:
        tracker_name = f"{artist} - {song}"
    elif artist:
        tracker_name = f"{artist} Campaign"

    # Call TidesTracker API to create the campaign
    import requests as http_requests
    try:
        resp = http_requests.post(
            f"{tracker_api}/campaigns",
            json={
                "name": tracker_name,
                "slug": slug,
                "cobrand_share_link": cobrand_share_url,
                "client_id": None,  # Unassigned — assign to client later via admin UI
            },
            headers={
                "Content-Type": "application/json",
                "x-service-key": tracker_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
    except http_requests.RequestException as e:
        return jsonify({"error": f"Failed to create tracker: {str(e)}"}), 502

    tracker_campaign_id = result.get("campaign", {}).get("id", "")
    tracker_url = f"{tracker_base}/{tracker_campaign_id}" if tracker_base else ""

    # Save tracker ID back to campaign
    if _db.is_active():
        _db.update_campaign_fields(slug, {
            "tracker_campaign_id": tracker_campaign_id,
            "tracker_url": tracker_url,
        })
    else:
        meta["tracker_campaign_id"] = tracker_campaign_id
        meta["tracker_url"] = tracker_url
        _save_meta(slug, meta, ACTIVE_DIR / slug)

    return jsonify({
        "ok": True,
        "message": "Tracker created successfully",
        "tracker_campaign_id": tracker_campaign_id,
        "tracker_url": tracker_url,
    })
