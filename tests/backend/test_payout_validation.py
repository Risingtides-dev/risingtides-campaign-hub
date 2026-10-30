"""Payout destination validation, legacy parsing, masking, backfill planning."""
from __future__ import annotations

import pytest

from campaign_manager.services.payout_backfill import plan_backfill
from campaign_manager.services.payout_validation import (
    Destination,
    PayoutValidationError,
    classify_legacy_value,
    mask_destination,
    normalize_destination,
)


@pytest.mark.parametrize("method,raw,expected", [
    ("paypal", "  Jane.Doe@Gmail.com ", Destination("paypal", "jane.doe@gmail.com")),
    ("PayPal", "a@b.co", Destination("paypal", "a@b.co")),
    ("cashapp", "$JaneDoe", Destination("cashapp", "$janedoe")),
    ("cashapp", "jane99", Destination("cashapp", "$jane99")),
    ("venmo", "@Jane-Doe_1", Destination("venmo", "@jane-doe_1")),
    ("other", "  zelle   555 0100 ", Destination("other", "zelle 555 0100")),
])
def test_normalize_accepts_valid(method, raw, expected):
    assert normalize_destination(method, raw) == expected


@pytest.mark.parametrize("method,raw", [
    ("bitcoin", "x@y.com"),
    ("", "x@y.com"),
    ("paypal", ""),
    ("paypal", "not-an-email"),
    ("paypal", "a@b"),
    ("paypal", "a b@c.com"),
    ("cashapp", "$"),
    ("cashapp", "$12345"),             # needs a letter
    ("cashapp", "$" + "a" * 21),
    ("cashapp", "$jane doe"),
    ("venmo", "@abc"),                 # too short
    ("venmo", "@jane doe!"),
    ("other", "ab"),
    ("other", "x" * 201),
])
def test_normalize_rejects_invalid(method, raw):
    with pytest.raises(PayoutValidationError):
        normalize_destination(method, raw)


def test_control_characters_are_stripped():
    assert normalize_destination("paypal", "a@b.com\x00​") == Destination("paypal", "a@b.com")


@pytest.mark.parametrize("raw,expected", [
    ("densona49@gmail.com", Destination("paypal", "densona49@gmail.com")),
    ("$JaneDoe", Destination("cashapp", "$janedoe")),
    ("-@cashapp", None),
    ("@cashapp-", None),
    ("cashapp", None),
    ("crypto", None),
    ("-@crypto", None),
    ("", None),
    (None, None),
])
def test_classify_legacy_value_never_guesses(raw, expected):
    assert classify_legacy_value(raw) == expected


def test_mask_shows_only_a_hint():
    assert mask_destination("jane.doe@gmail.com") == "ja•••@gmail.com"
    assert mask_destination("$janedoe") == "$ja•••"
    assert mask_destination("@jane-doe") == "@ja•••"
    assert mask_destination("") == ""


def test_plan_backfill_fills_only_single_clean_values():
    rows = [
        ("@Solo", "solo@gmail.com"),
        ("solo", "SOLO@gmail.com "),            # same value, different case/space
        ("conflict", "a@gmail.com"),
        ("conflict", "b@gmail.com"),
        ("caseconflict", "Venaldjb@gmail.com"),
        ("caseconflict", "venaldbecker@gmail.com"),
        ("junk", "-@cashapp"),
        ("empty", ""),
        ("empty", None),
        ("cash", "$CashKid"),
        ("hasone", "hasone@gmail.com"),
        ("noprofile", "np@gmail.com"),
    ]
    profiles = {
        "solo": "", "conflict": "", "caseconflict": "", "junk": "", "empty": "",
        "cash": "", "hasone": "existing@gmail.com",
    }
    plan = plan_backfill(rows, profiles)

    assert plan.to_fill == {
        "solo": Destination("paypal", "solo@gmail.com"),
        "cash": Destination("cashapp", "$cashkid"),
    }
    assert set(plan.conflicted) == {"conflict", "caseconflict"}
    assert plan.unparseable == {"junk": "-@cashapp"}
    assert plan.no_destination == ("empty",)
    assert plan.already_set == ("hasone",)
    assert plan.no_profile == ("noprofile",)
    assert plan.summary()["to_fill"] == 2
