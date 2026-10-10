"""Notion CRM sync -- poll for new 'Client' entries and create campaigns.

The Notion CRM database (Rising Tides Ent workspace) tracks client relationships
and campaign bookings. When a deal's Pipeline Status changes to "Client", we sync
that entry to Campaign Hub as a new campaign.

CRM Database ID: 1961465b-b829-80c9-a1b5-c4cb3284149a
Integration: "Rising Tides AI" bot (internal integration)
"""
import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import os
import threading
import time
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


# The CRM text property that holds a campaign's text-on-screen lines. Staff
# type into it and the intake forms write to it; the wording is kept verbatim.
CAPTIONS_PROPERTY = "Internal Captions"

# A page read returns at most 25 rich-text items inline. A longer value is
# read through the paginated property endpoint instead of being cut short.
_INLINE_RICH_TEXT_LIMIT = 25
_MAX_RICH_TEXT_PAGES = 40


def _parse_content_types(props: Dict) -> Optional[List[str]]:
    """Content Niche Targets from a page's properties, or None if unreadable."""
    target = props.get("Content Niche Targets")
    if not isinstance(target, dict) or not isinstance(target.get("multi_select"), list):
        return None
    options = target["multi_select"]
    if any(not isinstance(option, dict) or not isinstance(option.get("name"), str)
           or not option["name"].strip() for option in options):
        return None
    return [option["name"] for option in options]


def _fetch_full_rich_text(notion_page_id: str, property_id: str, *,
                          deadline=None, strict=False, before_request=None) -> Optional[str]:
    """Read a whole rich-text property, page by page. None on any failure."""
    url = f"{NOTION_API_BASE}/pages/{notion_page_id}/properties/{property_id}"
    parts: List[str] = []
    cursor = None
    for _ in range(_MAX_RICH_TEXT_PAGES):
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        remaining = deadline - time.monotonic() if deadline is not None else 15
        if remaining <= 0:
            if strict:
                raise CrmSourceUnavailable("property_deadline")
            return None
        if before_request is not None and not before_request(deadline=deadline):
            if strict:
                raise CrmSourceUnavailable("property_deadline")
            return None
        remaining = deadline - time.monotonic() if deadline is not None else 15
        if remaining <= 0:
            if strict:
                raise CrmSourceUnavailable("property_deadline")
            return None
        try:
            resp = requests.get(url, headers=_headers(), params=params,
                                timeout=min(15, remaining))
        except Exception:
            if strict:
                raise CrmSourceUnavailable("property_transport")
            logger.warning("CRM property fetch failed for %s", notion_page_id)
            return None
        if resp.status_code != 200:
            if strict:
                _crm_read_response(resp)
            logger.warning("CRM property fetch %s -> %s", notion_page_id, resp.status_code)
            return None
        try:
            body = resp.json()
            results = body.get("results")
            if not isinstance(results, list):
                return None
            for item in results:
                rich = item.get("rich_text") if isinstance(item, dict) else None
                if not isinstance(rich, dict) or not isinstance(rich.get("plain_text"), str):
                    return None
                parts.append(rich["plain_text"])
            if not body.get("has_more"):
                return "".join(parts)
            cursor = body.get("next_cursor")
        except (ValueError, AttributeError):
            return None
        if not cursor:
            return None
    if strict:
        raise CrmSourceUnavailable("caption_too_long", 300)
    logger.warning("CRM property for %s is longer than this sync reads", notion_page_id)
    return None


def _parse_internal_captions(notion_page_id: str, props: Dict, *,
                             deadline=None, strict=False, before_request=None) -> Optional[str]:
    """Internal Captions text from a page's properties, or None if unreadable.

    An empty property is an explicit "no captions" and returns "". A missing
    or malformed property returns None so stored captions are preserved.
    """
    target = props.get(CAPTIONS_PROPERTY)
    if not isinstance(target, dict) or not isinstance(target.get("rich_text"), list):
        return None
    parts = target["rich_text"]
    if any(not isinstance(part, dict) or not isinstance(part.get("plain_text"), str)
           for part in parts):
        return None
    if len(parts) >= _INLINE_RICH_TEXT_LIMIT:
        property_id = target.get("id")
        if not isinstance(property_id, str) or not property_id:
            return None
        return _fetch_full_rich_text(notion_page_id, property_id,
                                     deadline=deadline, strict=strict,
                                     before_request=before_request)
    return "".join(part["plain_text"] for part in parts)


# Notion takes rich text in pieces of at most 2,000 characters, and at most
# 100 pieces per property.
_RICH_TEXT_PIECE = 2000
MAX_INTERNAL_CAPTIONS = 100_000


def _rich_text_pieces(text: str) -> List[Dict]:
    """Text as Notion takes it. Python slices by code point, so no emoji is cut."""
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + _RICH_TEXT_PIECE, len(text))
        pieces.append({"type": "text", "text": {"content": text[start:end]}})
        start = end
    return pieces


def write_page_internal_captions(notion_page_id: str, text: str) -> Optional[str]:
    """Write a campaign's Internal Captions back to its CRM page.

    Returns None when the write went through, or the reason it did not, in
    plain words for the caller's response. The CRM is the source of truth
    for captions, so a caller that gets a reason must not store the value
    locally either.
    """
    api_key = _get_api_key()
    if not api_key:
        return "CRM writes are not configured (NOTION_API_KEY)"
    if not notion_page_id:
        return "campaign has no CRM page"
    url = f"{NOTION_API_BASE}/pages/{notion_page_id}"
    payload = {"properties": {CAPTIONS_PROPERTY: {"rich_text": _rich_text_pieces(text)}}}
    try:
        resp = requests.patch(url, headers=_headers(), json=payload, timeout=15)
    except Exception as e:
        logger.warning("CRM caption write failed for %s: %s", notion_page_id, e)
        return "CRM could not be reached"
    if resp.status_code != 200:
        logger.warning("CRM caption write %s -> %s: %s", notion_page_id, resp.status_code, resp.text[:300])
        detail = ""
        try:
            detail = (resp.json() or {}).get("message", "") or ""
        except ValueError:
            pass
        return f"CRM answered {resp.status_code}" + (f": {detail[:200]}" if detail else "")
    return None


def fetch_page_campaign_fields(notion_page_id: str) -> Optional[Dict]:
    """Fetch the CRM fields an existing campaign keeps tracking, by page id.

    Used to refresh EXISTING campaigns: the client-import funnel filters on
    Pipeline Status = 'Client', but a campaign's niche targets and captions
    must keep syncing after the row leaves that status (782 of 783 CRM rows
    are 'Lead', and campaigns keep their niche targets there). Returns None
    on any fetch failure — a page we cannot read is skipped, never emptied.
    Each field is None when its own property is missing or unreadable, so one
    bad property never blanks the other.
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
    try:
        props = resp.json().get("properties", {}) or {}
        if not isinstance(props, dict):
            return None
        return {
            "content_types": _parse_content_types(props),
            "internal_captions": _parse_internal_captions(notion_page_id, props),
        }
    except (ValueError, AttributeError):
        return None


def fetch_page_content_types(notion_page_id: str) -> Optional[List[str]]:
    """Fetch one CRM page's Content Niche Targets by page id."""
    fields = fetch_page_campaign_fields(notion_page_id)
    return fields["content_types"] if fields else None


_client_discovery_cursor = None
_crm_row_warning_at = {}


def log_crm_row_skip(page_id: str, reason: str) -> None:
    """Rate-limit per-row diagnostics without logging CRM property values."""
    key = (str(page_id), reason)
    now = time.monotonic()
    last = _crm_row_warning_at.get(key)
    if last is not None and now - last < 3600:
        return
    if len(_crm_row_warning_at) >= 256:
        oldest = min(_crm_row_warning_at, key=_crm_row_warning_at.get)
        del _crm_row_warning_at[oldest]
    _crm_row_warning_at[key] = now
    page_ref = hashlib.sha256(str(page_id).encode()).hexdigest()[:12]
    logger.warning("CRM discovery skipped page %s: %s", page_ref, reason)



def parse_client_pages(pages: List[Dict], synced_page_ids: Set[str], *,
                       strict_captions=False, deadline=None, before_request=None) -> List[Dict]:
    """Parse CRM page objects into create-only campaign candidates."""
    results = []
    for page in pages:
        page_id = page.get("id", "") if isinstance(page, dict) else ""
        try:
            if not page_id:
                raise ValueError("missing page id")
            if page_id in synced_page_ids:
                continue

            props = page.get("properties", {})

            # Extract all mapped fields from the CRM schema
            artist = _get_title(props.get("Artist Name", {}))
            song = _get_rich_text(props.get("Song Name", {}))
            if len(artist) > 255 or len(song) > 255:
                log_crm_row_skip(page_id, "artist or song exceeds 255 chars")
                continue
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
            content_types = _parse_content_types(props)
            tiktok_pct = _get_multi_select(props.get("TikTok", {}))
            insta_pct = _get_multi_select(props.get("Instagram", {}))
            internal_captions = _parse_internal_captions(
                page_id, props, deadline=deadline, strict=strict_captions,
                before_request=before_request,
            )
            captions_prop = props.get(CAPTIONS_PROPERTY)
            if (strict_captions and isinstance(captions_prop, dict) and
                isinstance(captions_prop.get("rich_text"), list) and
                len(captions_prop["rich_text"]) >= _INLINE_RICH_TEXT_LIMIT and
                internal_captions is None):
                raise CrmSourceUnavailable("caption_property_unreadable")

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
                "internal_captions": internal_captions,
                "platform_split": platform_split,
                "source": "notion",
            })
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            log_crm_row_skip(page_id, type(error).__name__)

    return results


def query_new_clients(synced_page_ids: Set[str], *, resume: bool = False) -> List[Dict]:
    """Query Notion CRM for entries with Pipeline Status = 'Client' not yet synced.

    Args:
        synced_page_ids: Set of Notion page IDs already imported to Campaign Hub.
        resume: Continue the bounded one-page discovery scan across scheduler ticks.

    Returns:
        List of campaign dicts ready to be saved via db.save_campaign().
    """
    global _client_discovery_cursor
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

    if resume and _client_discovery_cursor:
        payload["start_cursor"] = _client_discovery_cursor

    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=15)
        if resp.status_code != 200:
            if resume and resp.status_code == 400:
                _client_discovery_cursor = None
            logger.warning(
                "CRM sync query returned HTTP %s: %s", resp.status_code, resp.text[:300]
            )
            return []
    except Exception as e:
        logger.warning("CRM sync query failed: %s", e)
        return []

    response = resp.json()
    results = parse_client_pages(response.get("results", []), synced_page_ids)

    if resume:
        _client_discovery_cursor = response.get("next_cursor") if response.get("has_more") else None

    return results


_niche_refresh_after = ""


def refresh_campaign_niche_targets():
    """Refresh up to 50 existing active campaigns from their exact CRM links.

    Keeps each campaign's niche targets and captions in step with its CRM
    row. No campaign creation, inferred categories, or notifications. The
    cursor walks slugs so a larger roster advances across ticks, including
    failures.
    """
    global _niche_refresh_after
    from campaign_manager import db

    if not db.is_active():
        return {"checked": 0, "updated": 0, "unavailable": 0}
    links = sorted(db.get_campaign_notion_links(active_only=True), key=lambda row: row["slug"])
    ahead = [row for row in links if row["slug"] > _niche_refresh_after]
    behind = [row for row in links if row["slug"] <= _niche_refresh_after]
    selected = (ahead + behind)[:50]
    counts = {"checked": 0, "updated": 0, "unavailable": 0}
    for link in selected:
        counts["checked"] += 1
        try:
            fields = fetch_page_campaign_fields(link["notion_page_id"]) or {}
            fresh = fields.get("content_types")
            captions = fields.get("internal_captions")
            changes = {}
            if fresh is None:
                counts["unavailable"] += 1
            elif sorted(fresh) != sorted(link["content_types"]):
                changes["content_types"] = fresh
            if captions is not None and captions != link.get("internal_captions"):
                changes["internal_captions"] = captions
            if changes:
                db.update_campaign_fields(link["slug"], changes)
                counts["updated"] += 1
        except Exception:
            counts["unavailable"] += 1
            logger.exception("CRM niche refresh failed for %s", link["slug"])
        _niche_refresh_after = link["slug"]
    logger.info("CRM niche refresh: %s", counts)
    return counts


_niche_refresh_lock = threading.Lock()
_niche_refresh_running = False
_niche_refresh_requested_at = None


def request_campaign_niche_refresh():
    """Refresh in the background at most every 15 minutes on campaign reads.

    This keeps the CRM projection current when the scraping scheduler is off.
    Requests return the existing snapshot immediately while one refresh runs.
    """
    global _niche_refresh_running, _niche_refresh_requested_at
    from campaign_manager import db

    if not _get_api_key() or not db.is_active():
        return False
    with _niche_refresh_lock:
        now = time.monotonic()
        if _niche_refresh_running or (_niche_refresh_requested_at is not None
                                     and now - _niche_refresh_requested_at < 900):
            return False
        _niche_refresh_running = True
        _niche_refresh_requested_at = now
    def refresh():
        global _niche_refresh_running
        try:
            refresh_campaign_niche_targets()
        except Exception:
            logger.exception("CRM niche refresh failed")
        finally:
            with _niche_refresh_lock:
                _niche_refresh_running = False
    try:
        threading.Thread(target=refresh, name="crm-niche-refresh", daemon=True).start()
    except Exception:
        with _niche_refresh_lock:
            _niche_refresh_running = False
            _niche_refresh_requested_at = None
        logger.exception("Could not start CRM niche refresh")
        return False
    return True

class CrmSourceUnavailable(RuntimeError):
    """A CRM read cannot be treated as an empty source result."""

    def __init__(self, reason: str, retry_after: int = 2):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = max(1, int(retry_after))


def _crm_read_response(response, *, query_cursor=None):
    if response.status_code in (429, 529):
        raw_retry = response.headers.get("Retry-After", "2")
        try:
            retry_after = int(raw_retry)
        except (TypeError, ValueError):
            try:
                when = parsedate_to_datetime(raw_retry)
                retry_after = int((when - datetime.now(timezone.utc)).total_seconds()) + 1
            except (TypeError, ValueError, OverflowError):
                retry_after = 2
        raise CrmSourceUnavailable("rate_limited", retry_after)
    if response.status_code == 400 and query_cursor:
        try:
            error = response.json()
        except ValueError:
            error = None
        if (isinstance(error, dict) and error.get("code") == "validation_error" and
            "cursor" in str(error.get("message", "")).lower()):
            raise CrmSourceUnavailable("expired_query_cursor")
    if response.status_code != 200:
        raise CrmSourceUnavailable("http_status")
    try:
        body = response.json()
    except ValueError as error:
        raise CrmSourceUnavailable("invalid_json") from error
    if not isinstance(body, dict):
        raise CrmSourceUnavailable("invalid_body")
    return body


def query_crm_edit_window(*, lower, upper, cursor=None):
    """One sorted page of CRM edits, inclusive of both timestamp boundaries.

    Caller persists its cursor and enqueued page IDs in one DB transaction.
    Failure raises; it must never advance a durable cursor or watermark.
    """
    if not _get_api_key():
        raise CrmSourceUnavailable("missing_api_key", 60)
    source_id = resolve_data_source_id(
        _get_database_id(), env_override="NOTION_CRM_DATA_SOURCE_ID"
    )
    if not source_id:
        raise CrmSourceUnavailable("missing_data_source", 60)
    predicates = [{"timestamp": "last_edited_time", "last_edited_time":
                   {"on_or_before": upper.isoformat()}}]
    if lower is not None:
        predicates.append({"timestamp": "last_edited_time", "last_edited_time":
                           {"on_or_after": lower.isoformat()}})
    payload = {"filter": {"and": predicates}, "sorts": [
        {"timestamp": "last_edited_time", "direction": "ascending"}], "page_size": 100}
    if cursor:
        payload["start_cursor"] = cursor
    try:
        response = requests.post(
            f"{NOTION_API_BASE}/data_sources/{source_id}/query",
            headers=_headers(), json=payload, timeout=15,
        )
    except Exception as error:
        raise CrmSourceUnavailable("transport") from error
    body = _crm_read_response(response, query_cursor=cursor)
    request_status = body.get("request_status")
    if isinstance(request_status, dict) and request_status.get("type") == "incomplete":
        raise CrmSourceUnavailable("query_result_limit", 60)
    pages = body.get("results")
    if not isinstance(pages, list):
        raise CrmSourceUnavailable("missing_results")
    has_more = body.get("has_more")
    next_cursor = body.get("next_cursor")
    if not isinstance(has_more, bool) or (has_more and not isinstance(next_cursor, str)):
        raise CrmSourceUnavailable("invalid_cursor")
    if has_more and (not next_cursor or next_cursor == cursor):
        raise CrmSourceUnavailable("stalled_cursor")
    candidates = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("id"), str) or not page["id"]:
            raise CrmSourceUnavailable("invalid_page")
        edited = page.get("last_edited_time")
        if not isinstance(edited, str):
            raise CrmSourceUnavailable("invalid_edit_time")
        candidates.append((page["id"], edited))
    return candidates, next_cursor if has_more else None


def fetch_crm_page_for_queue(page_id):
    """Read exact current source page; failed reads are retryable, not empty."""
    if not _get_api_key():
        raise CrmSourceUnavailable("missing_api_key", 60)
    try:
        response = requests.get(f"{NOTION_API_BASE}/pages/{page_id}",
                                headers=_headers(), timeout=15)
    except Exception as error:
        raise CrmSourceUnavailable("transport") from error
    body = _crm_read_response(response)
    if body.get("id") != page_id or not isinstance(body.get("properties"), dict):
        raise CrmSourceUnavailable("invalid_page")
    return body
