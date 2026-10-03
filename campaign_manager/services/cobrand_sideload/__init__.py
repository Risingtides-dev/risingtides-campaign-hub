"""Cobrand Sideload — push matched TikTok links into co:brand's write API.

This is the *write path* into co:brand. It is deliberately separate from
``campaign_manager/services/cobrand.py`` (the read path, which only scrapes
performance fields out of public share-page ``__NEXT_DATA__`` and never
authenticates).

These are undocumented, private co:brand endpoints. The whole module is gated
behind the ``COBRAND_SIDELOAD_ENABLED`` feature flag (default OFF) and must not
be enabled in production until co:brand account/ToS authorization for
programmatic access is confirmed. See ``docs/cobrand-sideload.md``.
"""
from .config import SideloadConfig
from .client import CobrandSideloadClient, CobrandAPIError
from .auth import Auth0TokenManager, CobrandAuthError
from .sync import (
    sync_campaign,
    SyncReport,
    UrlOutcome,
    SideloadDisabledError,
    ActivationResolutionError,
)

__all__ = [
    "SideloadConfig",
    "CobrandSideloadClient",
    "CobrandAPIError",
    "Auth0TokenManager",
    "CobrandAuthError",
    "sync_campaign",
    "SyncReport",
    "UrlOutcome",
    "SideloadDisabledError",
    "ActivationResolutionError",
]
