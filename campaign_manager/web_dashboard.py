from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

import requests
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Add project root to path so we can import master_tracker
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Check if running on Railway (use volume paths)
IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT") is not None
DATA_ROOT = Path("/app/data_volume") if IS_RAILWAY else BASE_DIR

CAMPAIGNS_DIR = DATA_ROOT / "campaigns"
ACTIVE_DIR = CAMPAIGNS_DIR / "active"
COMPLETED_DIR = CAMPAIGNS_DIR / "completed"
SCRAPER_PATH = PROJECT_ROOT / "src" / "scrapers" / "scrape_external_accounts_cached.py"
INTERNAL_CREATORS_PATH = DATA_ROOT / "internal_creators.json"
INTERNAL_RESULTS_PATH = DATA_ROOT / "internal_last_scrape.json"

# Update cache path for both web_dashboard and master_tracker
CACHE_DIR = DATA_ROOT / "cache" if IS_RAILWAY else PROJECT_ROOT / "cache"
INTERNAL_CACHE_DIR = DATA_ROOT / "internal_cache"

# Set environment variable so master_tracker uses the correct cache directory
os.environ["CACHE_DIR"] = str(CACHE_DIR)

# ── Database setup ────────────────────────────────────────────────────
# If DATABASE_URL is set, use Postgres; otherwise fall back to file I/O.
from campaign_manager import db as _db

USE_DB = _db.init()  # returns True if DATABASE_URL was found and connected

app = Flask(__name__)
from campaign_manager.config import Config as _Config
app.secret_key = _Config.SECRET_KEY

CREATOR_FIELDS = [
    "username", "posts_owed", "posts_done", "posts_matched",
    "total_rate", "per_post_rate", "paypal_email", "paid",
    "payment_date", "platform", "added_date", "status", "notes",
]


PAYPAL_MEMORY_PATH = CAMPAIGNS_DIR / "paypal_memory.json"


def ensure_dirs() -> None:
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)


def load_paypal_memory() -> Dict[str, str]:
    if USE_DB:
        return _db.get_all_paypal()
    if not PAYPAL_MEMORY_PATH.exists():
        return {}
    with open(PAYPAL_MEMORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_paypal_memory(memory: Dict[str, str]) -> None:
    if USE_DB:
        for uname, email in memory.items():
            _db.save_paypal(uname, email)
        return
    CAMPAIGNS_DIR.mkdir(parents=True, exist_ok=True)
    with open(PAYPAL_MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)


def remember_paypal(username: str, email: str) -> None:
    if not username or not email:
        return
    if USE_DB:
        _db.save_paypal(username, email)
        return
    memory = load_paypal_memory()
    memory[username.lower()] = email
    save_paypal_memory(memory)


def recall_paypal(username: str) -> str:
    if USE_DB:
        return _db.get_paypal(username)
    memory = load_paypal_memory()
    return memory.get(username.lower(), "")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s-]+", "_", text)
    return text


def load_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}


def save_json(path: Path, data: Dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def load_creators(campaign_dir: Path) -> List[Dict]:
    csv_path = campaign_dir / "creators.csv"
    if not csv_path.exists():
        return []
    rows = []
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


def calc_budget(meta: Dict, creators: List[Dict]) -> Dict:
    total = float(meta.get("budget", 0))
    active = [c for c in creators if c.get("status", "active") != "removed"]
    booked = sum(float(c.get("total_rate", 0)) for c in active)
    paid = sum(float(c.get("total_rate", 0)) for c in active if str(c.get("paid", "")).lower() == "yes")
    left = total - booked
    pct = round(booked / total * 100) if total > 0 else 0
    return {"total": total, "booked": booked, "paid": paid, "left": left, "pct": pct}


def calc_stats(meta: Dict, creators: List[Dict]) -> Dict:
    """Calculate campaign stats from creators and stored stats."""
    active = [c for c in creators if c.get("status", "active") != "removed"]
    live_posts = sum(int(c.get("posts_done", 0)) for c in active)

    stored = meta.get("stats", {})
    total_views = int(stored.get("total_views", 0))

    budget_info = calc_budget(meta, creators)
    cpm = None
    if total_views > 0 and budget_info["booked"] > 0:
        cpm = (budget_info["booked"] / total_views) * 1_000

    return {
        "live_posts": live_posts,
        "total_views": total_views,
        "cpm": cpm,
    }


def campaign_title(meta: Dict) -> str:
    return meta.get("title") or meta.get("name") or "Untitled Campaign"


def parse_sort_datetime(meta: Dict) -> datetime:
    created_at = str(meta.get("created_at") or "").strip()
    if created_at:
        try:
            return datetime.fromisoformat(created_at)
        except Exception:
            pass
    start_date = str(meta.get("start_date") or "").strip()
    if start_date:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(start_date, fmt)
            except Exception:
                continue
    return datetime.min


def resolve_tiktok_short_url(short_url: str) -> str:
    """Resolve a TikTok short URL (e.g. /t/ZP8xdMGcf/) to its final URL."""
    try:
        resp = requests.head(short_url, allow_redirects=True, timeout=10,
                             headers={"User-Agent": "Mozilla/5.0"})
        return resp.url
    except Exception:
        try:
            resp = requests.get(short_url, allow_redirects=True, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"}, stream=True)
            return resp.url
        except Exception:
            return short_url


def extract_sound_id_from_html(video_url: str):
    """Extract sound ID and song title from a TikTok video page's HTML.

    More reliable than yt-dlp for getting the actual sound ID.
    Returns (sound_id, song_title) or (None, None).
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(video_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None, None

        pattern = r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>'
        matches = re.findall(pattern, resp.text, re.DOTALL)
        if not matches:
            return None, None

        data = json.loads(matches[0])
        music = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]["music"]
        sound_id = music.get("id")
        song_title = music.get("title", "")

        if sound_id and str(sound_id).isdigit():
            return str(sound_id), song_title
        return None, song_title
    except Exception:
        return None, None


def extract_sound_id(input_str: str) -> str:
    """Extract TikTok sound ID from various input formats.

    Accepts:
      - Raw sound ID: "7602731070429858591"
      - Sound URL: "https://www.tiktok.com/music/FEVER-DREAM-7602731070429858591"
      - Short URL: "https://www.tiktok.com/t/ZP8xdMGcf/" (resolves redirect first)
      - Video URL: "https://www.tiktok.com/@user/video/7602731070429858591"
        (fetches HTML to extract sound ID)
    """
    input_str = input_str.strip()

    # Already a raw numeric ID
    if re.match(r"^\d{10,}$", input_str):
        return input_str

    # TikTok sound URL — ID is the last number in the path
    if "tiktok.com/music/" in input_str:
        match = re.search(r"-(\d{10,})(?:\?|$)", input_str)
        if match:
            return match.group(1)
        match = re.search(r"(\d{10,})", input_str)
        if match:
            return match.group(1)

    # TikTok short URL — resolve redirect first
    if "tiktok.com/t/" in input_str:
        resolved = resolve_tiktok_short_url(input_str)
        if resolved != input_str:
            # Recurse with the resolved URL
            return extract_sound_id(resolved)

    # TikTok video URL — extract sound ID from page HTML (more reliable than yt-dlp)
    if "tiktok.com/" in input_str and ("/video/" in input_str or "/photo/" in input_str):
        sound_id, _ = extract_sound_id_from_html(input_str)
        if sound_id:
            return sound_id

    # Last resort: find any long number in the string
    match = re.search(r"(\d{10,})", input_str)
    if match:
        return match.group(1)

    return input_str


def get_campaigns() -> List[Dict]:
    if USE_DB:
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


# --- Routes ---

@app.get("/")
def index():
    search = (request.args.get("search") or "").strip().lower()
    campaigns = get_campaigns()

    if search:
        tokens = [t for t in re.split(r"\s+", search) if t]

        def _match(c):
            blob = " ".join([
                c["title"], c["meta"].get("artist", ""), c["meta"].get("song", ""),
                str(c["meta"].get("official_sound", "")), str(c["meta"].get("sound_id", "")),
                c["slug"],
            ]).lower()
            return all(tok in blob for tok in tokens)

        campaigns = [c for c in campaigns if _match(c)]

    campaigns.sort(key=lambda c: c["meta"].get("start_date", ""), reverse=True)

    return render_template("index.html",
        campaigns=campaigns, search=search, active_nav="campaigns")


@app.post("/campaign/create")
def create_campaign():
    title = (request.form.get("title") or "").strip()
    official_sound = (request.form.get("official_sound") or "").strip()
    start_date = (request.form.get("start_date") or "").strip() or str(date.today())
    budget_raw = (request.form.get("budget") or "0").strip()

    if not title:
        flash("Title is required.", "error")
        return redirect(url_for("index"))

    try:
        budget = float(budget_raw)
    except ValueError:
        flash("Budget must be a number.", "error")
        return redirect(url_for("index"))

    artist, song = "", ""
    if " - " in title:
        artist, song = [x.strip() for x in title.split(" - ", 1)]

    slug = slugify(title)

    meta = {
        "title": title, "name": title, "slug": slug,
        "artist": artist, "song": song,
        "official_sound": official_sound, "sound_id": extract_sound_id(official_sound),
        "start_date": start_date, "budget": budget,
        "status": "active", "platform": "tiktok",
        "created_at": datetime.now().isoformat(),
        "stats": {"total_views": 0, "total_likes": 0},
    }

    if USE_DB:
        if _db.campaign_exists(slug):
            flash(f"Campaign '{slug}' already exists.", "error")
            return redirect(url_for("index"))
        _db.save_campaign(slug, meta)
        _db.save_creators(slug, [])
    else:
        campaign_dir = ACTIVE_DIR / slug
        if campaign_dir.exists():
            flash(f"Campaign '{slug}' already exists.", "error")
            return redirect(url_for("index"))
        campaign_dir.mkdir(parents=True, exist_ok=True)
        (campaign_dir / "links").mkdir(exist_ok=True)
        save_json(campaign_dir / "campaign.json", meta)
        save_creators(campaign_dir, [])

    flash(f"Created campaign: {title}", "ok")
    return redirect(url_for("campaign_detail", slug=slug))


@app.post("/campaign/<slug>/edit")
def edit_campaign(slug: str):
    if USE_DB:
        meta = _db.get_campaign(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            flash("Campaign not found.", "error")
            return redirect(url_for("index"))
        meta = load_json(campaign_dir / "campaign.json")

    if not meta:
        flash("Campaign not found.", "error")
        return redirect(url_for("index"))

    title = (request.form.get("title") or "").strip()
    sound_id_raw = (request.form.get("sound_id") or "").strip()
    start_date = (request.form.get("start_date") or "").strip()
    budget_raw = (request.form.get("budget") or "").strip()

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
    additional = request.form.getlist("additional_sound")
    meta["additional_sounds"] = [s.strip() for s in additional if s.strip()]

    if start_date:
        meta["start_date"] = start_date

    if budget_raw:
        try:
            meta["budget"] = float(budget_raw)
        except ValueError:
            pass

    cobrand_link = (request.form.get("cobrand_link") or "").strip()
    meta["cobrand_link"] = cobrand_link

    if USE_DB:
        _db.save_campaign(slug, meta)
    else:
        save_json(campaign_dir / "campaign.json", meta)
    flash("Campaign updated.", "ok")
    return redirect(url_for("campaign_detail", slug=slug))


@app.get("/campaign/<slug>")
def campaign_detail(slug: str):
    if USE_DB:
        meta = _db.get_campaign(slug)
        if not meta:
            flash("Campaign not found.", "error")
            return redirect(url_for("index"))
        creators = _db.get_creators(slug)
        matched_videos = _db.get_matched_videos(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            flash("Campaign not found.", "error")
            return redirect(url_for("index"))
        meta = load_json(campaign_dir / "campaign.json")
        creators = load_creators(campaign_dir)
        matched_videos = load_matched_videos(campaign_dir)

    active_creators = [c for c in creators if c.get("status", "active") != "removed"]
    active_creators.sort(key=lambda c: c.get("username", ""))
    budget = calc_budget(meta, creators)
    stats = calc_stats(meta, creators)
    budget_pct = budget["pct"]

    return render_template("campaign_detail.html",
        slug=slug, meta=meta, title=campaign_title(meta),
        active_creators=active_creators, budget=budget,
        budget_pct=budget_pct, stats=stats, active_nav="campaigns",
        matched_videos=matched_videos)


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
    seen = set()
    deduped = []
    for v in videos:
        url = v.get("url", "")
        if url and url not in seen:
            seen.add(url)
            deduped.append(v)
    # Sort by date descending
    deduped.sort(key=lambda v: v.get("upload_date", ""), reverse=True)
    with open(campaign_dir / "matched_videos.json", "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, default=str)


def _save_meta(slug: str, meta: Dict, campaign_dir=None):
    """Save campaign metadata to DB or file, depending on mode."""
    if USE_DB:
        _db.save_campaign(slug, meta)
    else:
        save_json(campaign_dir / "campaign.json", meta)


@app.post("/campaign/<slug>/refresh")
def refresh_stats(slug: str):
    """Scrape creator accounts and match videos to the campaign sound."""
    if USE_DB:
        meta = _db.get_campaign(slug)
        if not meta:
            flash("Campaign not found.", "error")
            return redirect(url_for("index"))
        creators = _db.get_creators(slug)
        campaign_dir = None  # not used in DB mode
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            flash("Campaign not found.", "error")
            return redirect(url_for("index"))
        meta = load_json(campaign_dir / "campaign.json")
        creators = load_creators(campaign_dir)

    active_creators = [c for c in creators if c.get("status", "active") != "removed"]

    if not active_creators:
        flash("No creators to scrape.", "error")
        return redirect(url_for("campaign_detail", slug=slug))

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
    # (happens when campaign was created with the video ID instead of the music ID)
    official_sound_url = meta.get("official_sound", "")
    if (sound_id_raw and re.match(r"^\d{10,}$", sound_id_raw)
            and official_sound_url and sound_id_raw in official_sound_url):
        # sound_id is the video ID — resolve the actual music sound ID from HTML
        html_id, html_title = extract_sound_id_from_html(official_sound_url)
        if html_id and html_id != sound_id_raw:
            sound_id_raw = html_id
            meta["sound_id"] = html_id
            _save_meta(slug, meta, campaign_dir)
        # Also auto-populate artist/song from the official video if empty
        if not artist or not song:
            try:
                import subprocess as _sp
                _cmd = ["yt-dlp", "--dump-json", "--no-download", official_sound_url]
                _r = _sp.run(_cmd, capture_output=True, text=True, timeout=30)
                if _r.returncode == 0:
                    _vdata = json.loads(_r.stdout.strip())
                    if not artist and (_vdata.get("artist") or (_vdata.get("artists") or [None])[0]):
                        artist = _vdata.get("artist") or _vdata["artists"][0]
                        meta["artist"] = artist
                    if not song and _vdata.get("track"):
                        song = _vdata["track"]
                        meta["song"] = song
                    if html_title and not song:
                        song = html_title
                        meta["song"] = song
                    _save_meta(slug, meta, campaign_dir)
            except Exception:
                pass
            # Use HTML title as fallback for song
            if not song and html_title:
                song = html_title
                meta["song"] = song
                _save_meta(slug, meta, campaign_dir)

    # Resolve the sound ID — if it's a URL, extract the real numeric ID
    sound_id = sound_id_raw
    ref_song_title = None
    if sound_id_raw and not re.match(r"^\d{10,}$", sound_id_raw):
        resolved_id = extract_sound_id(sound_id_raw)
        if resolved_id and resolved_id != sound_id_raw:
            sound_id = resolved_id
            # Persist the resolved numeric ID so we don't re-resolve next time
            meta["sound_id"] = resolved_id
            _save_meta(slug, meta, campaign_dir)

    # If sound_id is still a URL (couldn't resolve), try HTML extraction on the resolved video
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
    sound_ids = set()
    sound_keys = set()
    if sound_id and re.match(r"^\d{10,}$", sound_id):
        sound_ids.add(sound_id)
    for extra_id in resolved_additional:
        if extra_id and re.match(r"^\d{10,}$", extra_id):
            sound_ids.add(extra_id)

    # Add exact song+artist key
    if song and artist:
        sound_keys.add(f"{song.lower().strip()} - {artist.lower().strip()}")

    # Add fuzzy song keys — strip common suffixes like "Promo", "(feat. ...)", "Remix"
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
    # Also add the reference song title from the sound page if we got it
    if ref_song_title and artist:
        core_ref = _core_song_name(ref_song_title)
        sound_keys.add(f"{core_ref} - {artist.lower().strip()}")

    if not sound_ids and not sound_keys:
        flash("No sound ID or song/artist to match against.", "error")
        return redirect(url_for("campaign_detail", slug=slug))

    try:
        from src.scrapers.master_tracker import (
            scrape_tiktok_account,
            match_video_to_sounds,
        )
    except ImportError as e:
        flash(f"Could not import scraper: {e}", "error")
        return redirect(url_for("campaign_detail", slug=slug))

    # Scrape all creator accounts in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_videos = []
    accounts_scraped = 0
    errors = []

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

    # Match videos to campaign sound
    # Build a set of core song words for fuzzy fallback matching
    core_song_words = set()
    if song:
        core = _core_song_name(song)
        core_song_words = {w for w in core.split() if len(w) > 2}
    if ref_song_title:
        core = _core_song_name(ref_song_title)
        core_song_words |= {w for w in core.split() if len(w) > 2}

    matched = []
    for video in all_videos:
        # Primary: use master_tracker's multi-strategy matching
        if match_video_to_sounds(video, sound_ids, sound_keys):
            matched.append(video)
            continue

        # Fuzzy fallback: match if video song contains core words and artist matches
        v_song = _core_song_name(video.get("song", "") or "")
        v_artist = (video.get("artist", "") or "").lower().strip()
        if core_song_words and v_song:
            v_words = set(v_song.split())
            overlap = core_song_words & v_words
            artist_match = artist and artist.lower().strip() in v_artist
            # Match if at least one core word overlaps and artist matches
            if overlap and artist_match:
                matched.append(video)

    # Merge with existing matched videos (keep old ones, add new)
    if USE_DB:
        existing = _db.get_matched_videos(slug)
    else:
        existing = load_matched_videos(campaign_dir)
    existing_urls = {v.get("url") for v in existing}
    new_matches = [v for v in matched if v.get("url") not in existing_urls]
    all_matched = existing + new_matches

    # Serialize matched videos (datetime -> string)
    for v in all_matched:
        if isinstance(v.get("timestamp"), datetime):
            v["timestamp"] = v["timestamp"].isoformat()

    if USE_DB:
        _db.replace_matched_videos(slug, all_matched)
    else:
        save_matched_videos(campaign_dir, all_matched)

    # Update stats
    total_views = sum(int(v.get("views", 0)) for v in all_matched)
    total_likes = sum(int(v.get("likes", 0)) for v in all_matched)
    stats = meta.get("stats", {})
    stats["total_views"] = total_views
    stats["total_likes"] = total_likes
    stats["last_scrape"] = datetime.now().isoformat()
    meta["stats"] = stats
    _save_meta(slug, meta, campaign_dir)

    # Update posts_done per creator
    matched_by_account = {}
    for v in all_matched:
        acct = v.get("account", "").lstrip("@")
        if acct:
            matched_by_account[acct] = matched_by_account.get(acct, 0) + 1

    if USE_DB:
        all_creators = _db.get_creators(slug)
    else:
        all_creators = load_creators(campaign_dir)
    for cr in all_creators:
        username = cr.get("username", "")
        if username in matched_by_account:
            cr["posts_done"] = matched_by_account[username]
            cr["posts_matched"] = matched_by_account[username]
    if USE_DB:
        _db.save_creators(slug, all_creators)
    else:
        save_creators(campaign_dir, all_creators)

    # Build feedback message
    feedback = (
        f"Scrape complete: {accounts_scraped} accounts scraped, "
        f"{len(all_videos)} videos checked, "
        f"{len(new_matches)} new matches found, "
        f"{len(all_matched)} total matched videos. "
        f"Views: {total_views:,} | Likes: {total_likes:,}"
    )
    if errors:
        feedback += f" | {len(errors)} error(s): {'; '.join(errors[:3])}"

    flash(feedback, "ok")

    # Save scrape log
    scrape_log = {
        "last_scrape": datetime.now().isoformat(),
        "accounts_scraped": accounts_scraped,
        "videos_checked": len(all_videos),
        "new_matches": len(new_matches),
        "total_matches": len(all_matched),
    }
    if USE_DB:
        _db.save_scrape_log(slug, scrape_log)
    else:
        save_json(campaign_dir / "scrape_log.json", scrape_log)

    return redirect(url_for("campaign_detail", slug=slug))


@app.get("/campaign/<slug>/links")
def campaign_links(slug: str):
    """Show all matched video links for a campaign."""
    if USE_DB:
        meta = _db.get_campaign(slug)
        if not meta:
            flash("Campaign not found.", "error")
            return redirect(url_for("index"))
        matched = _db.get_matched_videos(slug)
        scrape_log = _db.get_scrape_log(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            flash("Campaign not found.", "error")
            return redirect(url_for("index"))
        meta = load_json(campaign_dir / "campaign.json")
        matched = load_matched_videos(campaign_dir)
        scrape_log = load_json(campaign_dir / "scrape_log.json")

    return render_template("campaign_links.html",
        slug=slug, meta=meta, title=campaign_title(meta),
        videos=matched, scrape_log=scrape_log, active_nav="campaigns")


@app.post("/campaign/<slug>/creator/add")
def add_creator(slug: str):
    if USE_DB:
        if not _db.campaign_exists(slug):
            flash("Campaign not found.", "error")
            return redirect(url_for("index"))
    else:
        campaign_dir = ACTIVE_DIR / slug
        if not campaign_dir.exists():
            flash("Campaign not found.", "error")
            return redirect(url_for("index"))

    username = (request.form.get("username") or "").strip().lstrip("@")
    posts_owed_raw = (request.form.get("posts_owed") or "0").strip()
    total_rate_raw = (request.form.get("total_rate") or "0").strip()
    paypal = (request.form.get("paypal_email") or "").strip()
    platform = (request.form.get("platform") or "tiktok").strip() or "tiktok"

    # Auto-fill PayPal from memory if not provided
    if not paypal and username:
        paypal = recall_paypal(username)

    if not username:
        flash("Username is required.", "error")
        return redirect(url_for("campaign_detail", slug=slug))

    try:
        posts_owed = int(posts_owed_raw)
        total_rate = float(total_rate_raw)
    except ValueError:
        flash("Posts owed must be int and rate must be number.", "error")
        return redirect(url_for("campaign_detail", slug=slug))

    if USE_DB:
        creators = _db.get_creators(slug)
    else:
        creators = load_creators(campaign_dir)
    if any(c.get("username") == username and c.get("status", "active") != "removed" for c in creators):
        flash(f"@{username} already exists.", "error")
        return redirect(url_for("campaign_detail", slug=slug))

    per_post = round(total_rate / posts_owed, 2) if posts_owed > 0 else 0.0
    creators.append({
        "username": username, "posts_owed": posts_owed,
        "posts_done": 0, "posts_matched": 0,
        "total_rate": total_rate, "per_post_rate": per_post,
        "paypal_email": paypal, "paid": "no", "payment_date": "",
        "platform": platform, "added_date": str(date.today()),
        "status": "active", "notes": "",
    })
    if USE_DB:
        _db.save_creators(slug, creators)
    else:
        save_creators(campaign_dir, creators)
    if paypal:
        remember_paypal(username, paypal)
    flash(f"Added @{username}", "ok")
    return redirect(url_for("campaign_detail", slug=slug))


@app.post("/campaign/<slug>/creator/<username>/edit")
def edit_creator(slug: str, username: str):
    if USE_DB:
        creators = _db.get_creators(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        creators = load_creators(campaign_dir)

    new_username = (request.form.get("new_username") or "").strip().lstrip("@")
    posts_owed_raw = (request.form.get("posts_owed") or "").strip()
    total_rate_raw = (request.form.get("total_rate") or "").strip()
    paypal = (request.form.get("paypal_email") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    try:
        posts_owed = int(posts_owed_raw)
        total_rate = float(total_rate_raw)
        if posts_owed < 0 or total_rate < 0:
            raise ValueError
    except Exception:
        flash("Invalid values.", "error")
        return redirect(url_for("campaign_detail", slug=slug))

    for c in creators:
        if c.get("username") == username and c.get("status", "active") != "removed":
            if new_username and new_username != username:
                c["username"] = new_username
            c["posts_owed"] = posts_owed
            c["total_rate"] = total_rate
            c["per_post_rate"] = round(total_rate / posts_owed, 2) if posts_owed > 0 else 0.0
            c["paypal_email"] = paypal
            c["notes"] = notes
            break

    if USE_DB:
        _db.save_creators(slug, creators)
    else:
        save_creators(campaign_dir, creators)
    display_name = new_username if new_username and new_username != username else username
    if paypal:
        remember_paypal(display_name, paypal)
    flash(f"Updated @{display_name}", "ok")
    return redirect(url_for("campaign_detail", slug=slug))


@app.post("/campaign/<slug>/creator/<username>/toggle-paid")
def toggle_paid(slug: str, username: str):
    if USE_DB:
        creators = _db.get_creators(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        creators = load_creators(campaign_dir)
    new_status = "no"
    for c in creators:
        if c.get("username") == username:
            now_paid = str(c.get("paid", "no")).lower() != "yes"
            c["paid"] = "yes" if now_paid else "no"
            c["payment_date"] = str(date.today()) if now_paid else ""
            new_status = c["paid"]
            break
    if USE_DB:
        _db.save_creators(slug, creators)
    else:
        save_creators(campaign_dir, creators)
    if request.headers.get("X-Requested-With") == "fetch":
        return {"paid": new_status}
    return redirect(url_for("campaign_detail", slug=slug))


@app.post("/campaign/<slug>/creator/<username>/remove")
def remove_creator(slug: str, username: str):
    if USE_DB:
        creators = _db.get_creators(slug)
    else:
        campaign_dir = ACTIVE_DIR / slug
        creators = load_creators(campaign_dir)
    for c in creators:
        if c.get("username") == username:
            c["status"] = "removed"
            break
    if USE_DB:
        _db.save_creators(slug, creators)
    else:
        save_creators(campaign_dir, creators)
    flash(f"Removed @{username}", "ok")
    return redirect(url_for("campaign_detail", slug=slug))


@app.get("/api/paypal/<username>")
def api_paypal(username: str):
    return {"paypal": recall_paypal(username)}


@app.get("/health")
def health():
    return {"ok": True}


# ── API endpoints (for Open CLAW / Slack integration) ──────────────────

INBOX_PATH = CAMPAIGNS_DIR / "inbox.json"


def load_inbox() -> List[Dict]:
    if USE_DB:
        return _db.get_inbox()
    if INBOX_PATH.exists():
        try:
            return json.loads(INBOX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_inbox(items: List[Dict]):
    if USE_DB:
        # In DB mode, inbox items are saved individually — this is a no-op
        # for backward compat (individual saves happen in the route handlers)
        return
    INBOX_PATH.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")


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
        "creator_count": len([cr for cr in c["creators"] if cr.get("status", "active") != "removed"]),
    }


@app.get("/api/campaigns")
def api_campaigns():
    """List all campaigns with budget and stats."""
    campaigns = get_campaigns()
    campaigns.sort(key=lambda c: c["meta"].get("start_date", ""), reverse=True)
    return jsonify([_campaign_summary(c) for c in campaigns])


@app.get("/api/campaign/<slug>")
def api_campaign_detail(slug: str):
    """Full campaign detail with creators."""
    if USE_DB:
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
    active = [c for c in creators if c.get("status", "active") != "removed"]
    budget = calc_budget(meta, creators)
    stats = calc_stats(meta, creators)

    return jsonify({
        "slug": slug,
        "title": campaign_title(meta),
        "artist": meta.get("artist", ""),
        "song": meta.get("song", ""),
        "sound_id": meta.get("sound_id", ""),
        "start_date": meta.get("start_date", ""),
        "budget": budget,
        "stats": stats,
        "creators": [
            {
                "username": c.get("username", ""),
                "posts_owed": int(c.get("posts_owed", 0)),
                "posts_done": int(c.get("posts_done", 0)),
                "total_rate": float(c.get("total_rate", 0)),
                "paid": c.get("paid", "no"),
                "paypal_email": c.get("paypal_email", ""),
                "notes": c.get("notes", ""),
            }
            for c in active
        ],
    })


@app.get("/api/campaign/<slug>/budget")
def api_campaign_budget(slug: str):
    """Quick budget lookup — designed for Slack responses."""
    if USE_DB:
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
        "message": f"{campaign_title(meta)}: ${budget['total']:,.0f} budget, ${budget['booked']:,.0f} booked, ${budget['left']:,.0f} remaining ({budget['pct']}% used)",
    })


@app.get("/api/search")
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
            c["title"], c["meta"].get("artist", ""), c["meta"].get("song", ""), c["slug"],
        ]).lower()
        hits = sum(1 for t in tokens if t in blob)
        if hits > 0:
            scored.append((hits, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [_campaign_summary(s[1]) for s in scored[:5]]
    return jsonify({"query": q, "results": results})


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


# ── Inbox (Slack intake) ───────────────────────────────────────────────

@app.post("/api/inbox")
def api_inbox_add():
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

    if USE_DB:
        _db.save_inbox_item(item)
    else:
        inbox = load_inbox()
        inbox.insert(0, item)
        save_inbox(inbox)

    return jsonify({"ok": True, "id": item["id"], "message": "Added to inbox"})


@app.get("/api/inbox")
def api_inbox_list():
    """Get all pending inbox items."""
    status_filter = request.args.get("status", "pending")
    if USE_DB:
        inbox = _db.get_inbox(status=status_filter)
    else:
        inbox = load_inbox()
        if status_filter != "all":
            inbox = [i for i in inbox if i.get("status") == status_filter]
    return jsonify(inbox)


@app.post("/api/inbox/<item_id>/approve")
def api_inbox_approve(item_id: str):
    """Approve an inbox item — adds creators to the campaign."""
    if USE_DB:
        item = _db.get_inbox_item(item_id)
    else:
        inbox = load_inbox()
        item = next((i for i in inbox if i.get("id") == item_id), None)
    if not item:
        return jsonify({"error": "Inbox item not found"}), 404

    # Allow overriding campaign_slug and creator details from the form
    body = request.get_json(silent=True) or {}
    if body.get("campaign_slug"):
        item["campaign_slug"] = body["campaign_slug"]
    if body.get("creators"):
        item["creators"] = body["creators"]

    slug = item.get("campaign_slug", "")
    if not slug:
        return jsonify({"error": "No campaign_slug in inbox item"}), 400

    if USE_DB:
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

    if USE_DB:
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


@app.post("/api/inbox/<item_id>/dismiss")
def api_inbox_dismiss(item_id: str):
    """Dismiss/reject an inbox item."""
    if USE_DB:
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


# ── Inbox UI page ──────────────────────────────────────────────────────

@app.get("/inbox")
def inbox_page():
    inbox = load_inbox()
    campaigns = get_campaigns()
    campaigns.sort(key=lambda c: c["meta"].get("start_date", ""), reverse=True)
    return render_template("inbox.html",
        inbox=inbox, campaigns=campaigns, active_nav="inbox")


# ── Internal TikTok ───────────────────────────────────────────────────

import threading

_internal_scrape_status = {"running": False, "progress": "", "done": False}


def load_internal_creators() -> List[str]:
    if USE_DB:
        return _db.get_internal_creators()
    if INTERNAL_CREATORS_PATH.exists():
        try:
            return json.loads(INTERNAL_CREATORS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_internal_creators(creators: List[str]) -> None:
    if USE_DB:
        _db.save_internal_creators(creators)
        return
    INTERNAL_CREATORS_PATH.write_text(
        json.dumps(sorted(set(creators)), indent=2), encoding="utf-8"
    )


def load_internal_results() -> Dict:
    if USE_DB:
        return _db.get_internal_results()
    if INTERNAL_RESULTS_PATH.exists():
        try:
            return json.loads(INTERNAL_RESULTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_internal_results(data: Dict) -> None:
    if USE_DB:
        _db.save_internal_results(data)
        return
    INTERNAL_RESULTS_PATH.write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )


# ── Per-account 30-day rolling cache ──

def _account_cache_path(username: str) -> Path:
    return INTERNAL_CACHE_DIR / f"{username.lower()}.json"


def load_account_cache(username: str) -> List[Dict]:
    if USE_DB:
        return _db.get_internal_cache(username)
    path = _account_cache_path(username)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_account_cache(username: str, videos: List[Dict]) -> None:
    if USE_DB:
        # In DB mode, use merge_into_cache instead
        return
    INTERNAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _account_cache_path(username)
    path.write_text(json.dumps(videos, indent=2, default=str), encoding="utf-8")


def merge_into_cache(username: str, new_videos: List[Dict]) -> List[Dict]:
    """Merge new videos into account cache, dedupe by URL, prune older than 30 days."""
    if USE_DB:
        return _db.merge_internal_cache(username, new_videos)

    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=30)

    existing = load_account_cache(username)
    seen_urls = {v.get("url") for v in existing if v.get("url")}
    for v in new_videos:
        url = v.get("url", "")
        if url and url not in seen_urls:
            existing.append(v)
            seen_urls.add(url)

    # Prune videos older than 30 days
    pruned = []
    for v in existing:
        video_dt = None
        ts = v.get("timestamp")
        if ts and isinstance(ts, str):
            try:
                video_dt = datetime.fromisoformat(ts)
            except Exception:
                pass
        if not video_dt:
            upload = v.get("upload_date", "")
            if upload and len(upload) == 8:
                try:
                    video_dt = datetime.strptime(upload, "%Y%m%d")
                except Exception:
                    pass
        # Keep if we can't determine date or if within 30 days
        if video_dt is None or video_dt >= cutoff:
            pruned.append(v)

    save_account_cache(username, pruned)
    return pruned


def is_original_sound(song: str, artist: str) -> bool:
    """Check if a sound is just 'original sound - @username'."""
    s = (song or "").strip().lower()
    a = (artist or "").strip().lower()
    if s.startswith("original sound"):
        return True
    if s == "unknown" or s == "":
        return True
    # "son original" (Spanish/French), "suara asli" (Indonesian)
    if s.startswith("son original") or s.startswith("suara asli"):
        return True
    return False


@app.get("/internal")
def internal_page():
    creators = load_internal_creators()
    results = load_internal_results()
    # Build per-creator stats from cache for the sidebar
    creator_stats = {}
    for c in creators:
        cached = load_account_cache(c)
        creator_stats[c] = {
            "total_videos": len(cached),
            "total_views": sum(v.get("views", 0) for v in cached),
        }
    return render_template("internal.html",
        creators=creators, results=results,
        creator_stats=creator_stats,
        scrape_status=_internal_scrape_status,
        active_nav="internal")


@app.post("/internal/creator/add")
def internal_add_creator():
    raw = (request.form.get("username") or "").strip()
    if not raw:
        flash("Username is required.", "error")
        return redirect(url_for("internal_page"))

    usernames = re.split(r"[\n,]+", raw)
    creators = load_internal_creators()
    existing = {c.lower() for c in creators}
    added = []
    for u in usernames:
        u = u.strip().lstrip("@").strip()
        if u and u.lower() not in existing:
            creators.append(u)
            existing.add(u.lower())
            added.append(u)

    if added:
        save_internal_creators(creators)
        flash(f"Added {len(added)} creator(s): {', '.join('@' + a for a in added)}", "ok")
    else:
        flash("No new creators to add (already exist or empty).", "error")

    return redirect(url_for("internal_page"))


@app.post("/internal/creator/<username>/remove")
def internal_remove_creator(username: str):
    creators = load_internal_creators()
    creators = [c for c in creators if c.lower() != username.lower()]
    save_internal_creators(creators)
    flash(f"Removed @{username}", "ok")
    return redirect(url_for("internal_page"))


def _run_internal_scrape(hours: int, creators: List[str]):
    """Background scrape worker — runs in a thread."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from collections import defaultdict
    from datetime import timedelta

    global _internal_scrape_status
    _internal_scrape_status = {"running": True, "progress": "Starting...", "done": False}

    utils_dir = str(PROJECT_ROOT / "src" / "utils")
    if utils_dir not in sys.path:
        sys.path.insert(0, utils_dir)

    try:
        from get_post_links_by_song import scrape_account_videos, normalize_song_key
    except ImportError as e:
        _internal_scrape_status = {"running": False, "progress": f"Import error: {e}", "done": True}
        return

    try:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(hours=hours)

        all_videos = []
        successful = 0
        failed = 0
        total = len(creators)

        def _scrape_one(account):
            try:
                videos = scrape_account_videos(account, start_datetime=start_dt, end_datetime=end_dt, limit=500)
                return account, videos or [], None
            except Exception as e:
                return account, [], str(e)

        completed_count = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_scrape_one, c): c for c in creators}
            for future in as_completed(futures):
                account, videos, error = future.result()
                completed_count += 1
                if error:
                    failed += 1
                else:
                    # Merge into per-account cache
                    serializable = []
                    for v in videos:
                        sv = {
                            "url": v.get("url", ""),
                            "song": v.get("song", ""),
                            "artist": v.get("artist", ""),
                            "account": v.get("account", ""),
                            "views": v.get("views", 0),
                            "likes": v.get("likes", 0),
                            "upload_date": v.get("upload_date", ""),
                            "timestamp": v.get("timestamp").isoformat() if isinstance(v.get("timestamp"), datetime) else str(v.get("timestamp", "")),
                        }
                        serializable.append(sv)
                    merge_into_cache(account.lstrip("@"), serializable)
                    all_videos.extend(serializable)
                    successful += 1

                _internal_scrape_status["progress"] = f"Scraped {completed_count}/{total} accounts ({successful} ok, {failed} failed)"

        # Filter out original sounds
        filtered = [v for v in all_videos if not is_original_sound(v.get("song", ""), v.get("artist", ""))]

        # Group by song
        songs_dict = defaultdict(lambda: {
            "song": "", "artist": "", "videos": [], "accounts": set(),
            "total_views": 0, "total_likes": 0,
        })

        for video in filtered:
            song_key = normalize_song_key(video.get("song", ""), video.get("artist", ""))
            entry = songs_dict[song_key]
            entry["song"] = video.get("song", "Unknown")
            entry["artist"] = video.get("artist", "Unknown")
            entry["videos"].append({
                "url": video.get("url", ""),
                "account": video.get("account", ""),
                "views": video.get("views", 0),
                "likes": video.get("likes", 0),
                "upload_date": video.get("upload_date", ""),
            })
            entry["accounts"].add(video.get("account", ""))
            entry["total_views"] += video.get("views", 0)
            entry["total_likes"] += video.get("likes", 0)

        songs_list = []
        for key, data in sorted(songs_dict.items(), key=lambda x: x[1]["total_views"], reverse=True):
            data["accounts"] = sorted(data["accounts"])
            data["videos"].sort(key=lambda v: v.get("views", 0), reverse=True)
            data["key"] = key
            songs_list.append(data)

        results = {
            "scraped_at": datetime.now().isoformat(),
            "hours": hours,
            "start_dt": start_dt.isoformat(),
            "end_dt": end_dt.isoformat(),
            "accounts_total": total,
            "accounts_successful": successful,
            "accounts_failed": failed,
            "total_videos": len(filtered),
            "total_videos_unfiltered": len(all_videos),
            "unique_songs": len(songs_list),
            "songs": songs_list,
        }
        save_internal_results(results)

        _internal_scrape_status = {
            "running": False,
            "done": True,
            "progress": (
                f"Done: {successful}/{total} accounts, "
                f"{len(filtered)} videos ({len(all_videos) - len(filtered)} original sounds filtered), "
                f"{len(songs_list)} unique songs"
            ),
        }
    except Exception as e:
        _internal_scrape_status = {
            "running": False,
            "done": True,
            "progress": f"Error: {e}",
        }


@app.post("/internal/scrape")
def internal_scrape():
    if _internal_scrape_status.get("running"):
        flash("A scrape is already running. Please wait.", "error")
        return redirect(url_for("internal_page"))

    hours = int(request.form.get("hours", 48))
    creators = load_internal_creators()

    if not creators:
        flash("No internal creators to scrape.", "error")
        return redirect(url_for("internal_page"))

    # Launch scrape in background thread
    t = threading.Thread(target=_run_internal_scrape, args=(hours, creators), daemon=True)
    t.start()

    flash(f"Scrape started for {len(creators)} accounts (last {hours}h). Page will auto-refresh when done.", "ok")
    return redirect(url_for("internal_page"))


@app.get("/internal/scrape/status")
def internal_scrape_status():
    """AJAX endpoint for polling scrape progress."""
    return jsonify(_internal_scrape_status)


# ── Internal creator detail page ──────────────────────────────────────

@app.get("/internal/creator/<username>")
def internal_creator_detail(username: str):
    creators = load_internal_creators()
    if username.lower() not in {c.lower() for c in creators}:
        flash(f"@{username} not found in internal creators.", "error")
        return redirect(url_for("internal_page"))

    # Load all cached videos for this account
    cached = load_account_cache(username)

    # Filter out original sounds
    filtered = [v for v in cached if not is_original_sound(v.get("song", ""), v.get("artist", ""))]

    # Group by song
    from collections import defaultdict
    songs_dict = defaultdict(lambda: {
        "song": "", "artist": "", "videos": [], "total_views": 0, "total_likes": 0,
    })

    for v in filtered:
        key = f"{(v.get('song') or 'Unknown').strip()} - {(v.get('artist') or 'Unknown').strip()}"
        entry = songs_dict[key]
        entry["song"] = v.get("song", "Unknown")
        entry["artist"] = v.get("artist", "Unknown")
        entry["videos"].append(v)
        entry["total_views"] += v.get("views", 0)
        entry["total_likes"] += v.get("likes", 0)

    songs_list = []
    for key, data in sorted(songs_dict.items(), key=lambda x: x[1]["total_views"], reverse=True):
        data["videos"].sort(key=lambda v: v.get("views", 0), reverse=True)
        data["key"] = key
        songs_list.append(data)

    total_views = sum(v.get("views", 0) for v in filtered)
    total_likes = sum(v.get("likes", 0) for v in filtered)

    return render_template("internal_creator.html",
        username=username,
        songs=songs_list,
        total_videos=len(filtered),
        total_videos_raw=len(cached),
        total_views=total_views,
        total_likes=total_likes,
        active_nav="internal")


# ── Data Migration API ────────────────────────────────────────────────

@app.route("/api/migrate/campaign", methods=["POST"])
def api_migrate_campaign():
    """Upload campaign data for migration"""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    slug = data.get("slug")
    if not slug:
        return jsonify({"error": "Missing slug"}), 400

    # Create campaign directory
    campaign_dir = ACTIVE_DIR / slug
    campaign_dir.mkdir(parents=True, exist_ok=True)

    # Save campaign.json
    if "campaign" in data:
        save_json(campaign_dir / "campaign.json", data["campaign"])

    # Save creators.csv
    if "creators" in data and data["creators"]:
        save_creators(campaign_dir, data["creators"])

    # Save matched_videos.json
    if "matched_videos" in data:
        videos = data["matched_videos"]
        if isinstance(videos, list):
            save_matched_videos(campaign_dir, videos)

    # Save scrape_log.json
    if "scrape_log" in data:
        save_json(campaign_dir / "scrape_log.json", data["scrape_log"])

    return jsonify({
        "status": "success",
        "slug": slug,
        "campaign_dir": str(campaign_dir)
    })


# Initialize directories when module is loaded (needed for gunicorn)
ensure_dirs()


if __name__ == "__main__":
    ensure_dirs()

    # Production settings for Railway
    port = int(os.environ.get("PORT", 5055))
    debug = not IS_RAILWAY  # Debug only in local development
    host = "0.0.0.0" if IS_RAILWAY else "127.0.0.1"

    # use_reloader=False prevents Flask from killing background scrape threads
    # when .py files change elsewhere in the project. Restart manually if needed.
    app.run(host=host, port=port, debug=debug, use_reloader=False)
