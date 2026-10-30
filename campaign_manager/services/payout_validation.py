"""Payout destination validation, normalization and masking.

Pure functions, no DB. Shared by the creator-facing endpoint (strict: the
creator typed it) and the backfill (conservative: only values that parse
cleanly are ever carried over from campaign rows).
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple, Optional

METHODS = ("paypal", "cashapp", "venmo", "other")

_EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@]+\.[^\s@]{2,}$")
_CASHTAG = re.compile(r"^(?=.*[a-z])[a-z0-9]{1,20}$")
_VENMO = re.compile(r"^[a-z0-9_-]{5,30}$")
_OTHER_MIN, _OTHER_MAX = 3, 200
_EMAIL_MAX = 254


class PayoutValidationError(ValueError):
    """Raised with a message that is safe to show the creator."""


class Destination(NamedTuple):
    method: str
    destination: str


def _strip_controls(value: str) -> str:
    return "".join(ch for ch in value if unicodedata.category(ch)[0] != "C")


def _clean(value) -> str:
    return _strip_controls(str(value or "")).strip()


def normalize_destination(method, destination) -> Destination:
    """Validate a creator-entered destination and return its canonical form.

    Canonical forms: PayPal = lowercase email, Cash App = ``$tag``,
    Venmo = ``@handle``, other = trimmed free text.
    """
    m = _clean(method).lower()
    if m not in METHODS:
        raise PayoutValidationError("Pick a payment method.")

    raw = _clean(destination)
    if not raw:
        raise PayoutValidationError("Enter where you'd like to be paid.")

    if m == "paypal":
        email = raw.lower()
        if len(email) > _EMAIL_MAX or not _EMAIL.match(email):
            raise PayoutValidationError("That doesn't look like a PayPal email address.")
        return Destination(m, email)

    if m == "cashapp":
        tag = raw.lstrip("$").lower()
        if not _CASHTAG.match(tag):
            raise PayoutValidationError(
                "Cash App tags are 1–20 letters or numbers, like $yourname."
            )
        return Destination(m, f"${tag}")

    if m == "venmo":
        handle = raw.lstrip("@").lower()
        if not _VENMO.match(handle):
            raise PayoutValidationError(
                "Venmo usernames are 5–30 letters, numbers, - or _, like @your-name."
            )
        return Destination(m, f"@{handle}")

    text = re.sub(r"\s+", " ", raw)
    if not (_OTHER_MIN <= len(text) <= _OTHER_MAX):
        raise PayoutValidationError(
            f"Keep it between {_OTHER_MIN} and {_OTHER_MAX} characters."
        )
    return Destination(m, text)


def classify_legacy_value(raw) -> Optional[Destination]:
    """Parse a value from the legacy ``creators.paypal_email`` column.

    Only two shapes are trusted: a valid email (→ PayPal) and a clean
    ``$cashtag`` (→ Cash App). Everything else — ``-@cashapp``, ``crypto``,
    bare handles — returns None. The backfill never guesses.
    """
    value = _clean(raw)
    if not value:
        return None
    if "@" in value and not value.startswith(("@", "-")):
        try:
            return normalize_destination("paypal", value)
        except PayoutValidationError:
            return None
    if value.startswith("$"):
        try:
            return normalize_destination("cashapp", value)
        except PayoutValidationError:
            return None
    return None


def mask_destination(destination: str) -> str:
    """Show enough for a creator to recognise their own details, no more."""
    value = str(destination or "")
    if not value:
        return ""
    if "@" in value and not value.startswith("@"):
        local, _, domain = value.partition("@")
        return f"{local[:2]}•••@{domain}"
    # $tag / @handle / free text: the symbol plus two characters.
    return f"{value[:3]}•••"
