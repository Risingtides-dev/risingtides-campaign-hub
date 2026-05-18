#!/usr/bin/env python3
"""Create Notion databases required by the outreach agent.

Creates four databases under a parent page:
- Labels
- Artists
- Leads
- Outreach Log

Required env vars:
    NOTION_API_KEY
    NOTION_PARENT_PAGE_ID

Optional env vars:
    NOTION_VERSION (default: 2022-06-28)

Usage:
    NOTION_API_KEY=... NOTION_PARENT_PAGE_ID=... \
      python scripts/create_outreach_notion_schema.py
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict

import requests

NOTION_API_BASE = "https://api.notion.com/v1"
DEFAULT_NOTION_VERSION = "2022-06-28"


@dataclass
class CreatedDatabase:
    name: str
    id: str
    url: str


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Content-Type": "application/json",
        "Notion-Version": os.environ.get("NOTION_VERSION", DEFAULT_NOTION_VERSION),
    }


def _create_database(parent_page_id: str, title: str, properties: Dict[str, Any]) -> CreatedDatabase:
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
    }
    response = requests.post(
        f"{NOTION_API_BASE}/databases",
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    return CreatedDatabase(name=title, id=body["id"], url=body["url"])


def _labels_schema() -> Dict[str, Any]:
    return {
        "name": {"title": {}},
        "tier": {"select": {}},
        "genres": {"multi_select": {}},
        "contacts": {"rich_text": {}},
        "roster_size": {"number": {"format": "number"}},
        "relationship_status": {"select": {}},
    }


def _artists_schema(labels_db_id: str) -> Dict[str, Any]:
    return {
        "name": {"title": {}},
        "label": {
            "relation": {
                "database_id": labels_db_id,
                "single_property": {},
            }
        },
        "spotify_url": {"url": {}},
        "monthly_listeners": {"number": {"format": "number"}},
        "genres": {"multi_select": {}},
        "recent_releases": {"rich_text": {}},
        "social_links": {"url": {}},
    }


def _leads_schema(artists_db_id: str, labels_db_id: str) -> Dict[str, Any]:
    return {
        "artist": {
            "relation": {
                "database_id": artists_db_id,
                "single_property": {},
            }
        },
        "label": {
            "relation": {
                "database_id": labels_db_id,
                "single_property": {},
            }
        },
        "score": {"number": {"format": "number"}},
        "score_reasoning": {"rich_text": {}},
        "signals": {"multi_select": {}},
        "status": {"select": {}},
        "scored_at": {"date": {}},
    }


def _outreach_log_schema(leads_db_id: str) -> Dict[str, Any]:
    return {
        "lead": {
            "relation": {
                "database_id": leads_db_id,
                "single_property": {},
            }
        },
        "draft_subject": {"rich_text": {}},
        "draft_body": {"rich_text": {}},
        "contact": {"rich_text": {}},
        "status": {
            "select": {
                "options": [
                    {"name": "draft", "color": "gray"},
                    {"name": "sent", "color": "blue"},
                    {"name": "replied", "color": "yellow"},
                    {"name": "converted", "color": "green"},
                ]
            }
        },
        "created_at": {"date": {}},
    }


def main() -> int:
    if not os.environ.get("NOTION_API_KEY"):
        print("ERROR: NOTION_API_KEY is required", file=sys.stderr)
        return 1
    if not os.environ.get("NOTION_PARENT_PAGE_ID"):
        print("ERROR: NOTION_PARENT_PAGE_ID is required", file=sys.stderr)
        return 1

    parent_page_id = os.environ["NOTION_PARENT_PAGE_ID"]

    try:
        labels = _create_database(parent_page_id, "Labels", _labels_schema())
        artists = _create_database(parent_page_id, "Artists", _artists_schema(labels.id))
        leads = _create_database(parent_page_id, "Leads", _leads_schema(artists.id, labels.id))
        outreach_log = _create_database(parent_page_id, "Outreach Log", _outreach_log_schema(leads.id))
    except requests.HTTPError as exc:
        detail = ""
        if exc.response is not None:
            detail = exc.response.text
        print(f"ERROR: Failed to create Notion schema: {exc}\n{detail}", file=sys.stderr)
        return 2

    output = {
        "labels_database_id": labels.id,
        "artists_database_id": artists.id,
        "leads_database_id": leads.id,
        "outreach_log_database_id": outreach_log.id,
        "databases": [
            {"name": labels.name, "id": labels.id, "url": labels.url},
            {"name": artists.name, "id": artists.id, "url": artists.url},
            {"name": leads.name, "id": leads.id, "url": leads.url},
            {"name": outreach_log.name, "id": outreach_log.id, "url": outreach_log.url},
        ],
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
