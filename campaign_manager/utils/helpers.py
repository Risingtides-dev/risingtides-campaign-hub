"""Shared helper functions extracted from web_dashboard."""

import json
import hashlib
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable
from urllib.parse import urlsplit, urlunsplit

import requests

log = logging.getLogger(__name__)


def _ambiguous_post_ref(video: Dict) -> str:
    """Stable diagnostic identity without leaking query tokens or raw URLs."""
    raw = str(video.get("url") or "").strip()
    if raw:
        try:
            parts = urlsplit(raw)
            canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))
        except ValueError:
            canonical = raw.split("?", 1)[0].split("#", 1)[0]
        return "url_sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    row_id = video.get("id")
    return f"row_id:{row_id}" if row_id is not None else "unidentified"


def slugify(text: str) -> str:
    """Canonical slug from free-text (Notion `Group` / `Poster` values).

    Lowercase, replace whitespace + punctuation with `_`, collapse runs of `_`,
    strip leading/trailing `_`. Source of truth for slug generation now that
    Notion drives both label and booker axes (see RTA-5 / RTA-8).
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "_", text)
    text = re.sub(r"[\s\-_]+", "_", text)
    return text.strip("_")

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


def video_posted_before_start(video: Dict, start_date: str) -> bool:
    """Return True if `video` was definitively posted before `start_date`.

    Used to scope a campaign's matched videos to its own date window so
    that a round-2 campaign doesn't pull in posts already uploaded under
    round 1 (CAMP-42). Cobrand only dedupes within a single round, so
    leaking pre-start-date posts into a later round creates duplicates
    in the client report.

    `start_date` is the campaign's ``start_date`` ("YYYY-MM-DD"). The
    video's post date is read from ``timestamp`` (ISO format) when
    present, falling back to ``upload_date`` ("YYYYMMDD"). When neither
    field is parseable — or `start_date` is empty — returns False so
    the caller keeps the row. Fail-open is deliberate: hiding a real
    match because metadata is missing is worse than the duplicate-in-
    Cobrand symptom this filter exists to prevent.
    """
    if not start_date:
        return False

    timestamp = (video.get("timestamp") or "").strip()
    if timestamp and len(timestamp) >= 10 and timestamp[4] == "-" and timestamp[7] == "-":
        return timestamp[:10] < start_date

    upload_date = (video.get("upload_date") or "").strip()
    if len(upload_date) == 8 and upload_date.isdigit():
        normalized = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        return normalized < start_date

    return False


def round_start_date(value: object) -> date | None:
    """Parse a campaign round's calendar start; reject malformed dates."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()) else None
    except ValueError:
        return None


def video_post_date(video: Dict) -> date | None:
    """Read a post's calendar date from scraper metadata, if trustworthy."""
    ts = video.get("timestamp")
    if isinstance(ts, datetime):
        return ts.date()
    if isinstance(ts, str) and ts.strip():
        try:
            return datetime.fromisoformat(ts.strip().replace("Z", "+00:00")).date()
        except ValueError:
            pass
    upload = video.get("upload_date")
    if isinstance(upload, str) and re.fullmatch(r"\d{8}", upload.strip()):
        try:
            return datetime.strptime(upload.strip(), "%Y%m%d").date()
        except ValueError:
            pass
    if isinstance(upload, str) and upload.strip():
        try:
            return datetime.fromisoformat(upload.strip().replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return None


def build_round_end_by_slug(campaigns: Iterable[Dict]) -> dict[str, dict[str, date | None]]:
    """Upper-exclusive next-round start for each exact campaign sound ID.

    Include completed rounds: completion stops writes, not the previous
    round's date window. Same-day rounds use created_at then slug to select
    one deterministic owner for that date.
    """
    rows = list(campaigns)
    keyed = []
    for meta in rows:
        slug = str(meta.get("slug") or "")
        start = round_start_date(meta.get("start_date"))
        if not slug or start is None:
            continue
        additional = meta.get("additional_sounds")
        raw_ids = [meta.get("sound_id")] + (list(additional) if isinstance(additional, (list, tuple)) else [])
        sound_ids = {str(raw).strip() for raw in raw_ids if raw is not None and len(str(raw).strip()) >= 5 and str(raw).strip() != "-"}
        if sound_ids:
            keyed.append((slug, start, str(meta.get("created_at") or ""), sound_ids))

    end_by_slug: dict[str, dict[str, date | None]] = {}
    for slug, start, created, sound_ids in keyed:
        current_key = (start, created, slug)
        per_sound = {}
        for sound_id in sound_ids:
            later_starts = [other_start for other_slug, other_start, other_created, other_ids in keyed
                            if sound_id in other_ids and (other_start, other_created, other_slug) > current_key]
            per_sound[sound_id] = min(later_starts) if later_starts else None
        end_by_slug[slug] = per_sound
    return end_by_slug


def round_end_for_video(video: Dict, end_date: date | dict[str, date | None] | None) -> date | None:
    """Resolve a sound-specific boundary; unknown identities use the earliest end.

    This prevents uncertain historical matches from crossing into another
    round's Cobrand queue or report. A known secondary sound with no successor
    retains its own open window even if the primary sound has advanced.
    """
    if not isinstance(end_date, dict):
        return end_date
    for field in ("extracted_sound_id", "music_id"):
        sound_id = str(video.get(field) or "").strip()
        if sound_id in end_date:
            return end_date[sound_id]
    bounded = [end for end in end_date.values() if end is not None]
    return min(bounded) if bounded else None


def round_qualified_videos(
    videos: Iterable[Dict], start_date: object, *, end_date: date | dict[str, date | None] | None = None,
    exclude_dismissed: bool = False,
) -> list[Dict]:
    """Scope stored matches to a campaign round without deleting history.

    A missing campaign start retains legacy behavior. A malformed nonempty
    start or missing/malformed post date cannot prove round membership.
    """
    return [video for video in videos if video_in_round(
        video, start_date, end_date=end_date, exclude_dismissed=exclude_dismissed,
    )]


def video_in_round(
    video: Dict, start_date: object, *, end_date: date | dict[str, date | None] | None = None,
    exclude_dismissed: bool = False,
) -> bool:
    """Whether one matched row can be shown or counted in a round."""
    if exclude_dismissed and video.get("dismissed_at"):
        return False
    raw = str(start_date or "").strip()
    if not raw:
        return True
    start = round_start_date(raw)
    posted = video_post_date(video)
    end = round_end_for_video(video, end_date)
    if (isinstance(end_date, dict) and end is not None and posted is not None
            and posted >= end and not any(
                str(video.get(field) or "").strip() in end_date
                for field in ("extracted_sound_id", "music_id")
            )):
        log.warning(
            "Matched post %s has no owned sound identity after a partial round boundary; excluded for reconciliation",
            _ambiguous_post_ref(video),
        )
    return bool(start is not None and posted is not None and posted >= start
                and (end is None or posted < end))
