"""Notion CRM sync -- poll for new 'Client' entries and create campaigns.

The Notion CRM database (Rising Tides Ent workspace) tracks client relationships
and campaign bookings. When a deal's Pipeline Status changes to "Client", we sync
that entry to Campaign Hub as a new campaign.

CRM Database ID: 1961465b-b829-80c9-a1b5-c4cb3284149a
Integration: "Rising Tides AI" bot (internal integration)
"""
import logging
import os
from typing import Dict, List, Optional, Set

import requests

from campaign_manager.utils.helpers import slugify, extract_sound_id


logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
# 2025-09-03 is the first version that supports multi-source databases.
# Both workspace databases (CRM + Master Pages) gained a second data source
# on 2026-07-28, after which older versions get HTTP 400 on every query.
NOTION_VERSION = "2025-09-03"

# database_id -> data_source_id, resolved once per process.
_data_source_cache: Dict[str, str] = {}


def _get_api_key() -> str:
    """Get the Notion API key from environment."""
    return os.environ.get("NOTION_API_KEY", "")


def _get_database_id() -> str:
    """Get the CRM database ID from environment."""
    return os.environ.get(
        "NOTION_CRM_DATABASE_ID", "1961465b-b829-80c9-a1b5-c4cb3284149a"
    )


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def resolve_data_source_id(database_id: str, env_override: str = "") -> str:
    """Resolve a database ID to the data source ID its queries should target.

    Since Notion-Version 2025-09-03, queries go to /data_sources/<id>/query
    rather than /databases/<id>/query, because a database is now a container
    that can hold several data sources. Both Rising Tides databases hold their
    original source first plus an empty accidental "New data source", so the
    first-listed source is the right one; set the env_override variable to pin
    a specific source if that ever changes.

    Returns "" on failure (callers treat that as an empty/failed fetch).
    """
    if env_override:
        pinned = os.environ.get(env_override, "").strip()
        if pinned:
            return pinned

    cached = _data_source_cache.get(database_id)
    if cached:
        return cached

    url = f"{NOTION_API_BASE}/databases/{database_id}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
    except Exception as e:
        logger.warning("Notion data-source lookup failed for %s: %s", database_id, e)
        return ""
    if resp.status_code != 200:
        logger.warning(
            "Notion data-source lookup for %s returned HTTP %s: %s",
            database_id, resp.status_code, resp.text[:300],
        )
        return ""

    sources = resp.json().get("data_sources") or []
    if not sources:
        logger.warning("Notion database %s reports no data sources", database_id)
        return ""
    if len(sources) > 1:
        logger.info(
            "Notion database %s has %d data sources; using first-listed %r (%s)",
            database_id, len(sources), sources[0].get("name", ""), sources[0].get("id", ""),
        )

    ds_id = sources[0].get("id", "")
    if ds_id:
        _data_source_cache[database_id] = ds_id
    return ds_id


# -- Notion property extractors --

def _get_title(prop: Dict) -> str:
    """Extract plain text from a Notion title property."""
    parts = prop.get("title", [])
    return "".join(t.get("plain_text", "") for t in parts)


def _get_rich_text(prop: Dict) -> str:
    """Extract plain text from a Notion rich_text property."""
    parts = prop.get("rich_text", [])
    return "".join(t.get("plain_text", "") for t in parts)


def _get_select(prop: Dict) -> str:
    """Extract value from a Notion select property."""
    s = prop.get("select")
    return s.get("name", "") if s else ""


def _get_multi_select(prop: Dict) -> List[str]:
    """Extract values from a Notion multi_select property."""
    return [o.get("name", "") for o in prop.get("multi_select", [])]


def _get_status(prop: Dict) -> str:
    """Extract value from a Notion status property."""
    s = prop.get("status")
    return s.get("name", "") if s else ""


def _get_url(prop: Dict) -> str:
    """Extract value from a Notion url property."""
    return prop.get("url", "") or ""


def _get_date(prop: Dict) -> str:
    """Extract start date from a Notion date property."""
    d = prop.get("date")
    return d.get("start", "") if d else ""


def _get_number(prop: Dict) -> Optional[float]:
    """Extract value from a Notion number property."""
    return prop.get("number")


def _get_email(prop: Dict) -> str:
    """Extract value from a Notion email property."""
    return prop.get("email", "") or ""


def _parse_platform_split(tiktok_pct: List[str], insta_pct: List[str]) -> Dict:
    """Parse TikTok/Instagram percentage multi-selects into a platform split dict.

    Notion stores these as multi_select with values like "70%", "100%".
    We take the first value from each.
    """
    split = {}
    if tiktok_pct:
        try:
            split["tiktok"] = int(tiktok_pct[0].replace("%", ""))
        except (ValueError, IndexError):
            pass
    if insta_pct:
        try:
            split["instagram"] = int(insta_pct[0].replace("%", ""))
        except (ValueError, IndexError):
            pass
    return split


def fetch_page_content_types(notion_page_id: str) -> Optional[List[str]]:
    """Fetch one CRM page's Content Niche Targets by page id.

    Used to refresh EXISTING campaigns: the client-import funnel filters on
    Pipeline Status = 'Client', but a campaign's niche targets must keep
    syncing after the row leaves that status (782 of 783 CRM rows are
    'Lead', and campaigns keep their niche targets there). Returns None on
    any fetch failure — a page we cannot read is skipped, never emptied.
    """
    api_key = _get_api_key()
    if not api_key or not notion_page_id:
        return None
    url = f"{NOTION_API_BASE}/pages/{notion_page_id}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
    except Exception as e:
        logger.warning("CRM page fetch failed for %s: %s", notion_page_id, e)
        return None
    if resp.status_code != 200:
        logger.warning("CRM page fetch %s -> %s", notion_page_id, resp.status_code)
        return None
    props = resp.json().get("properties", {}) or {}
    return _get_multi_select(props.get("Content Niche Targets", {}))


def query_new_clients(synced_page_ids: Set[str]) -> List[Dict]:
    """Query Notion CRM for entries with Pipeline Status = 'Client' not yet synced.

    Args:
        synced_page_ids: Set of Notion page IDs already imported to Campaign Hub.

    Returns:
        List of campaign dicts ready to be saved via db.save_campaign().
    """
    api_key = _get_api_key()
    if not api_key:
        return []

    database_id = _get_database_id()
    ds_id = resolve_data_source_id(database_id, env_override="NOTION_CRM_DATA_SOURCE_ID")
    if not ds_id:
        logger.warning("CRM sync skipped: could not resolve a data source for %s", database_id)
        return []
    url = f"{NOTION_API_BASE}/data_sources/{ds_id}/query"

    payload = {
        "filter": {
            "property": "Pipeline Status",
            "status": {"equals": "Client"},
        },
        "page_size": 50,
    }

    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=15)
        if resp.status_code != 200:
            logger.warning(
                "CRM sync query returned HTTP %s: %s", resp.status_code, resp.text[:300]
            )
            return []
    except Exception as e:
        logger.warning("CRM sync query failed: %s", e)
        return []

    results = []
    for page in resp.json().get("results", []):
        page_id = page["id"]
        if page_id in synced_page_ids:
            continue

        props = page.get("properties", {})

        # Extract all mapped fields from the CRM schema
        artist = _get_title(props.get("Artist Name", {}))
        song = _get_rich_text(props.get("Song Name", {}))
        tiktok_sound = _get_url(props.get("TikTok Sound Link", {})).strip()
        insta_sound = _get_url(props.get("Insta Sound Link", {})).strip()
        cobrand = _get_url(props.get("Co Brand Link", {})).strip()
        start_date = _get_date(props.get("Desired Start Date", {}))
        budget = _get_number(props.get("Media Spend", {}))
        campaign_stage = _get_status(props.get("Campaign Stage", {}))
        round_val = _get_select(props.get("Round", {}))
        label = _get_rich_text(props.get("Label/Distro Partner", {}))
        lead = _get_multi_select(props.get("Project Lead", {}))
        email = _get_email(props.get("Key Contact Email", {}))
        # The CRM property is "Content Niche Targets" (multi_select). We were
        # reading "Types of Content Creators", which does not exist on the
        # database — so this came back empty for every campaign ever synced
        # (0 of 326 populated) while 286 of 300 CRM rows actually carry tags.
        # A missing property is silently empty here, so nothing ever surfaced.
        # Legacy name kept as a fallback in case an older DB copy still uses it.
        content_types = (_get_multi_select(props.get("Content Niche Targets", {}))
                         or _get_multi_select(props.get("Types of Content Creators", {})))
        tiktok_pct = _get_multi_select(props.get("TikTok", {}))
        insta_pct = _get_multi_select(props.get("Instagram", {}))

        platform_split = _parse_platform_split(tiktok_pct, insta_pct)

        # Extract sound ID from TikTok sound link if available
        sound_id = ""
        if tiktok_sound:
            sound_id = extract_sound_id(tiktok_sound)

        # Build campaign title
        if artist and song:
            title = f"{artist} - {song}"
        elif artist:
            title = artist
        elif song:
            title = song
        else:
            title = f"Untitled ({page_id[:8]})"

        slug = slugify(title)

        results.append({
            "notion_page_id": page_id,
            "title": title,
            "slug": slug,
            "artist": artist,
            "song": song,
            "official_sound": tiktok_sound,
            "sound_id": sound_id,
            "insta_sound": insta_sound,
            "cobrand_share_url": cobrand,
            "start_date": start_date,
            "budget": float(budget) if budget else 0.0,
            "campaign_stage": campaign_stage,
            "round": round_val,
            "label": label,
            "project_lead": lead,
            "client_email": email,
            "content_types": content_types,
            "platform_split": platform_split,
            "source": "notion",
        })

    return results
