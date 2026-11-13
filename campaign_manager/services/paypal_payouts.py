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
from dataclasses import dataclass

import requests

BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}
TIMEOUT = 30


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
        payload.update(recipient_type="USER_HANDLE", recipient_wallet="Venmo")
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
            )
        except requests.RequestException as exc:
            raise PayPalError(f"Couldn't reach PayPal ({type(exc).__name__}).") from None
        if resp.status_code != 200:
            raise PayPalError(f"PayPal rejected the credentials (HTTP {resp.status_code}).")
        self._token = resp.json().get("access_token", "")
        return self._token

    def _call(self, method: str, path: str, **kwargs) -> dict:
        headers = {"Authorization": f"Bearer {self._auth()}", "Content-Type": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        try:
            resp = self.http.request(method, f"{self.config.base_url}{path}",
                                     headers=headers, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise PayPalError(f"Couldn't reach PayPal ({type(exc).__name__}).") from None
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if resp.status_code >= 400:
            detail = body.get("message") or body.get("name") or f"HTTP {resp.status_code}"
            raise PayPalError(f"PayPal error: {detail}")
        return body

    def create_payout(self, sender_batch_id: str, items: list) -> dict:
        """POST /v1/payments/payouts. `sender_batch_id` makes retries safe:
        PayPal refuses a second batch with the same id."""
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

    def get_batch(self, paypal_batch_id: str, page_size: int = 500) -> dict:
        """All pages of the batch's items, merged into one response."""
        first = self._call("GET", f"/v1/payments/payouts/{paypal_batch_id}",
                           params={"page_size": page_size, "page": 1, "total_required": "true"})
        items = list(first.get("items") or [])
        pages = int(first.get("total_pages") or 1)
        for page in range(2, min(pages, 50) + 1):
            more = self._call("GET", f"/v1/payments/payouts/{paypal_batch_id}",
                              params={"page_size": page_size, "page": page})
            items.extend(more.get("items") or [])
        return {**first, "items": items}
