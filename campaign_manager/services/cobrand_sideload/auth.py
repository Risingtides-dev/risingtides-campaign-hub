"""Auth0 token manager for the co:brand write API.

co:brand authenticates via an Auth0 tenant. We support two grants and pick
based on which secrets are configured (see ``SideloadConfig.grant_type``):

- ``client_credentials`` (M2M): ``AUTH0_CLIENT_ID`` + ``AUTH0_CLIENT_SECRET``
  + ``AUTH0_AUDIENCE``.
- ``refresh_token``: ``AUTH0_REFRESH_TOKEN`` (+ client id/secret when present).

The token is cached in memory until shortly before expiry. ``invalidate()``
forces a refetch; the API client calls it on a ``401`` and retries once.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import requests

from .config import SideloadConfig

# Refresh this many seconds before the token actually expires.
_EXPIRY_SKEW_SECONDS = 60


class CobrandAuthError(Exception):
    """Raised when an access token cannot be obtained."""


class Auth0TokenManager:
    def __init__(
        self,
        config: SideloadConfig,
        session: Optional[requests.Session] = None,
        clock: Callable[[], float] = time.time,
    ):
        self._config = config
        self._session = session or requests.Session()
        self._clock = clock
        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def get_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            now = self._clock()
            if (
                not force_refresh
                and self._token
                and now < (self._expires_at - _EXPIRY_SKEW_SECONDS)
            ):
                return self._token
            return self._fetch_locked()

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    def _fetch_locked(self) -> str:
        cfg = self._config
        grant = cfg.grant_type
        if not grant:
            raise CobrandAuthError(
                "No Auth0 credentials configured: set AUTH0_CLIENT_ID/SECRET "
                "(client_credentials) or AUTH0_REFRESH_TOKEN (refresh_token)."
            )
        if not cfg.auth0_domain:
            raise CobrandAuthError("AUTH0_DOMAIN is not configured.")

        if grant == "client_credentials":
            body = {
                "grant_type": "client_credentials",
                "client_id": cfg.auth0_client_id,
                "client_secret": cfg.auth0_client_secret,
                "audience": cfg.auth0_audience,
            }
        else:  # refresh_token
            body = {
                "grant_type": "refresh_token",
                "refresh_token": cfg.auth0_refresh_token,
            }
            if cfg.auth0_client_id:
                body["client_id"] = cfg.auth0_client_id
            if cfg.auth0_client_secret:
                body["client_secret"] = cfg.auth0_client_secret

        url = f"https://{cfg.auth0_domain}/oauth/token"
        try:
            resp = self._session.post(url, json=body, timeout=15)
        except requests.RequestException as exc:
            raise CobrandAuthError(f"Auth0 token request failed: {exc}") from exc

        if resp.status_code != 200:
            raise CobrandAuthError(
                f"Auth0 token request returned {resp.status_code}: {resp.text[:300]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise CobrandAuthError("Auth0 token response was not JSON.") from exc

        token = data.get("access_token")
        if not token:
            raise CobrandAuthError("Auth0 token response had no access_token.")

        expires_in = data.get("expires_in", 3600)
        try:
            expires_in = float(expires_in)
        except (TypeError, ValueError):
            expires_in = 3600.0

        self._token = token
        self._expires_at = self._clock() + expires_in
        return token
