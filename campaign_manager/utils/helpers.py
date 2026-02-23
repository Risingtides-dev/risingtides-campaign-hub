"""Shared helper functions extracted from web_dashboard."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict

import requests


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
