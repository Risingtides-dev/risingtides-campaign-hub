"""Typed HTTP client for the four co:brand write endpoints.

All endpoints are POST against ``api.cobrand.com``. The client centralizes:

- bearer auth via :class:`Auth0TokenManager` (one ``401`` -> refresh -> retry),
- exponential backoff on ``429`` and ``5xx`` (a transient ``503`` was observed
  on the validate endpoint),
- typed (de)serialization into the dataclasses in :mod:`.types`.

The ``requests.Session`` is injectable so tests can drive it without network
access (no extra test dependency required).
"""
from __future__ import annotations

import time
from typing import Callable, List, Optional

import requests

from .auth import Auth0TokenManager
from .config import SideloadConfig
from .types import BulkCreateGroup, GetPromotionResponse


class CobrandAPIError(Exception):
    """Non-retryable (or retries-exhausted) error from a co:brand endpoint."""

    def __init__(self, status: int, body: str, path: str):
        self.status = status
        self.body = body
        self.path = path
        super().__init__(f"co:brand {path} returned {status}: {body[:300]}")


class CobrandSideloadClient:
    def __init__(
        self,
        config: SideloadConfig,
        token_manager: Optional[Auth0TokenManager] = None,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.session = session or requests.Session()
        self.tokens = token_manager or Auth0TokenManager(config, session=self.session)
        self._sleep = sleep

    # ---- endpoints -------------------------------------------------------

    def get_promotion(self, promotion_id: str) -> GetPromotionResponse:
        """POST /brand/v2/get_promotion — resolve a promotion to its activations."""
        data = self._post("/brand/v2/get_promotion", {"promotion_id": promotion_id})
        return GetPromotionResponse.from_api(data)

    def validate_live_post_url(self, url: str) -> dict:
        """POST /brand/v2/validate_live_post_url.

        NOTE: response shape is unconfirmed (see docs §2.2). Returns the raw
        JSON so callers can adapt once confirmed.
        """
        return self._post("/brand/v2/validate_live_post_url", {"url": url})

    def bulk_upload(self, activation_id: str, urls: List[str]) -> str:
        """POST /brand/v2/bulk_upload_live_posts_for_collaboration.

        Async — returns the ``group_id`` handle, not the created records.
        """
        data = self._post(
            "/brand/v2/bulk_upload_live_posts_for_collaboration",
            {"activation_id": activation_id, "urls": list(urls)},
        )
        return data.get("group_id", "") or ""

    def list_bulk_create_groups(
        self, activation_id: str, limit: int = 99, offset: int = 0
    ) -> List[BulkCreateGroup]:
        """POST /brand/v2/list_activation_collaboration_bulk_create_groups."""
        data = self._post(
            "/brand/v2/list_activation_collaboration_bulk_create_groups",
            {"activation_id": activation_id, "limit": limit, "offset": offset},
        )
        return [BulkCreateGroup.from_api(it) for it in (data.get("items") or [])]

    # ---- transport -------------------------------------------------------

    def _post(self, path: str, payload: dict, _auth_retried: bool = False) -> dict:
        url = f"{self.config.api_base}{path}"
        attempt = 0
        while True:
            token = self.tokens.get_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            try:
                resp = self.session.post(url, json=payload, headers=headers, timeout=30)
            except requests.RequestException as exc:
                # Treat transport errors like a retryable 5xx.
                if attempt < self.config.request_max_retries:
                    self._sleep(self._backoff_delay(attempt))
                    attempt += 1
                    continue
                raise CobrandAPIError(0, f"transport error: {exc}", path) from exc

            status = resp.status_code

            # Expired/invalid token: refresh once, then retry from scratch.
            if status == 401 and not _auth_retried:
                self.tokens.invalidate()
                return self._post(path, payload, _auth_retried=True)

            # Rate limited or server error: backoff + retry.
            if status == 429 or 500 <= status < 600:
                if attempt < self.config.request_max_retries:
                    self._sleep(self._backoff_delay(attempt))
                    attempt += 1
                    continue
                raise CobrandAPIError(status, resp.text, path)

            if not (200 <= status < 300):
                raise CobrandAPIError(status, resp.text, path)

            try:
                return resp.json()
            except ValueError:
                return {}

    def _backoff_delay(self, attempt: int) -> float:
        # Exponential backoff: base * 2**attempt.
        return self.config.request_backoff_base * (2 ** attempt)
