"""Environment-driven configuration + feature flag for Cobrand Sideload.

Nothing here is hardcoded — every secret comes from the environment. The
master switch is ``COBRAND_SIDELOAD_ENABLED`` (default OFF).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


@dataclass
class SideloadConfig:
    """All knobs for the sideload module.

    Defaults are chosen so an instance constructed with no args is *safe*:
    disabled, validation off, conservative retry/poll budgets.
    """

    enabled: bool = False
    api_base: str = "https://api.cobrand.com"

    # Auth0
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_client_id: str = ""
    auth0_client_secret: str = ""
    auth0_refresh_token: str = ""

    # Optional pre-upload validation (shape unconfirmed — off by default).
    validate_urls: bool = False

    # Poll loop for the async bulk-create group.
    poll_max_attempts: int = 30
    poll_interval_seconds: float = 2.0
    poll_backoff: float = 1.0  # delay multiplier per attempt; 1.0 = constant

    # Per-request retry/backoff for 429 + 5xx.
    request_max_retries: int = 4
    request_backoff_base: float = 1.0

    @classmethod
    def from_env(cls) -> "SideloadConfig":
        return cls(
            enabled=_env_bool("COBRAND_SIDELOAD_ENABLED", False),
            api_base=os.environ.get("COBRAND_API_BASE", "https://api.cobrand.com").rstrip("/"),
            auth0_domain=os.environ.get("AUTH0_DOMAIN", "").strip(),
            auth0_audience=os.environ.get("AUTH0_AUDIENCE", "").strip(),
            auth0_client_id=os.environ.get("AUTH0_CLIENT_ID", "").strip(),
            auth0_client_secret=os.environ.get("AUTH0_CLIENT_SECRET", "").strip(),
            auth0_refresh_token=os.environ.get("AUTH0_REFRESH_TOKEN", "").strip(),
            validate_urls=_env_bool("COBRAND_SIDELOAD_VALIDATE", False),
            poll_max_attempts=_env_int("COBRAND_SIDELOAD_POLL_MAX_ATTEMPTS", 30),
            poll_interval_seconds=_env_float("COBRAND_SIDELOAD_POLL_INTERVAL_SECONDS", 2.0),
            poll_backoff=_env_float("COBRAND_SIDELOAD_POLL_BACKOFF", 1.0),
            request_max_retries=_env_int("COBRAND_SIDELOAD_REQUEST_MAX_RETRIES", 4),
            request_backoff_base=_env_float("COBRAND_SIDELOAD_REQUEST_BACKOFF_BASE", 1.0),
        )

    @property
    def grant_type(self) -> str:
        """Which Auth0 grant we can perform given the configured secrets."""
        if self.auth0_client_id and self.auth0_client_secret:
            return "client_credentials"
        if self.auth0_refresh_token:
            return "refresh_token"
        return ""
