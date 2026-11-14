"""Minimal PayPal Payouts API client (PayPal + Venmo recipients).

Env:
  PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET   REST app credentials
  PAYPAL_ENV                                 'sandbox' (default) or 'live'

Defaults to SANDBOX so nothing real can move until someone deliberately
sets PAYPAL_ENV=live. Only ever called from an explicit, human-approved
batch (see services/payout_batches.py).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests

BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}
TIMEOUT = 30
_PROVIDER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def validate_provider_id(value) -> str:
    if not isinstance(value, str) or not _PROVIDER_ID.fullmatch(value):
        raise PayPalError("Enter a valid PayPal batch ID (letters, numbers, hyphen or underscore; at most 64 characters).")
    return value


class PayPalError(RuntimeError):
    """Message is safe to show Jake: never contains credentials."""


@dataclass(frozen=True)
class PayPalConfig:
    client_id: str
    client_secret: str
    env: str

    @classmethod
    def from_env(cls) -> "PayPalConfig":
        env = (os.environ.get("PAYPAL_ENV") or "sandbox").strip().lower()
        if env not in BASE_URLS:
            raise PayPalError("PAYPAL_ENV must be 'sandbox' or 'live'.")
        cid = (os.environ.get("PAYPAL_CLIENT_ID") or "").strip()
        secret = (os.environ.get("PAYPAL_CLIENT_SECRET") or "").strip()
        if not cid or not secret:
            raise PayPalError("PayPal isn't connected yet (PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET not set).")
        return cls(cid, secret, env)

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.env]


def _item_payload(item) -> dict:
    payload = {
        "amount": {"value": f"{item.amount:.2f}", "currency": item.currency or "USD"},
        "receiver": item.destination,
        "sender_item_id": f"item-{item.id}",
        "note": f"Rising Tides — {item.campaign_title}"[:4000],
    }
    if item.method == "venmo":
        payload.update(recipient_type="USER_HANDLE", recipient_wallet="VENMO")
    else:
        payload.update(recipient_type="EMAIL")
    return payload


class PayPalPayouts:
    def __init__(self, config: PayPalConfig, session: requests.Session | None = None):
        self.config = config
        self.http = session or requests.Session()
        self._token = ""

    @property
    def env(self) -> str:
        return self.config.env

    def _auth(self) -> str:
        if self._token:
            return self._token
        try:
            resp = self.http.post(
                f"{self.config.base_url}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self.config.client_id, self.config.client_secret),
                timeout=TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise PayPalError(f"Couldn't reach PayPal ({type(exc).__name__}).") from None
        if resp.status_code != 200:
            raise PayPalError(f"PayPal rejected the credentials (HTTP {resp.status_code}).")
        try:
            body = resp.json()
        except ValueError:
            raise PayPalError("PayPal returned an unreadable authentication response.") from None
        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token or len(token) > 16384 or any(ch.isspace() for ch in token):
            raise PayPalError("PayPal returned an invalid authentication response.")
        self._token = token
        return self._token

    def _call(self, method: str, path: str, **kwargs) -> dict:
        headers = {"Authorization": f"Bearer {self._auth()}", "Content-Type": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        try:
            resp = self.http.request(method, f"{self.config.base_url}{path}",
                                     headers=headers, timeout=TIMEOUT, allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            raise PayPalError(f"Couldn't reach PayPal ({type(exc).__name__}).") from None
        if not 200 <= resp.status_code < 300:
            raise PayPalError(f"PayPal request failed (HTTP {resp.status_code}).")
        try:
            body = resp.json()
        except ValueError:
            raise PayPalError("PayPal returned an unreadable response.") from None
        if not isinstance(body, dict):
            raise PayPalError("PayPal returned an invalid response.")
        return body

    def create_payout(self, sender_batch_id: str, items: list) -> dict:
        """Create once. The caller persists an attempt before this POST and
        reconciles an unknown result with GET; it never replays this call."""
        validate_provider_id(sender_batch_id)
        return self._call(
            "POST",
            "/v1/payments/payouts",
            headers={"PayPal-Request-Id": sender_batch_id},
            json={
                "sender_batch_header": {
                    "sender_batch_id": sender_batch_id,
                    "email_subject": "You've been paid by Rising Tides",
                    "email_message": "Thanks for posting! Here's your payment.",
                },
                "items": [_item_payload(i) for i in items],
            },
        )

    def prepare_payout(self) -> None:
        """Authenticate before the durable funds attempt; OAuth moves no money."""
        self._auth()

    def get_batch(self, paypal_batch_id: str, page_size: int = 500) -> dict:
        """All pages of the batch's items, merged into one response."""
        validate_provider_id(paypal_batch_id)
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 1000:
            raise PayPalError("Invalid PayPal batch page size.")
        first = self._call("GET", f"/v1/payments/payouts/{paypal_batch_id}",
                           params={"page_size": page_size, "page": 1, "total_required": "true"})
        if not isinstance(first.get("items"), list):
            raise PayPalError("PayPal returned incomplete batch items.")
        items = list(first["items"])
        if len(items) > 1000:
            raise PayPalError("PayPal returned too many batch items.")
        raw_pages = first.get("total_pages", 1)
        if isinstance(raw_pages, bool) or not str(raw_pages).isdigit():
            raise PayPalError("PayPal returned invalid batch pagination.")
        pages = int(raw_pages)
        if not 1 <= pages <= 50:
            raise PayPalError("PayPal batch pagination is incomplete or too large.")
        for page in range(2, pages + 1):
            more = self._call("GET", f"/v1/payments/payouts/{paypal_batch_id}",
                              params={"page_size": page_size, "page": page})
            if not isinstance(more.get("items"), list):
                raise PayPalError("PayPal returned incomplete batch items.")
            header = more.get("batch_header")
            if header is not None and header != first.get("batch_header"):
                raise PayPalError("PayPal returned conflicting batch pages.")
            items.extend(more["items"])
            if len(items) > 1000:
                raise PayPalError("PayPal returned too many batch items.")
        if "total_items" in first:
            total = first["total_items"]
            if isinstance(total, bool) or not isinstance(total, int) or total != len(items):
                raise PayPalError("PayPal returned incomplete or inconsistent batch item counts.")
        return {**first, "items": items}
