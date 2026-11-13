"""scripts/payout_history_audit.summarize — pure bucketing logic."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "payout_history_audit.py"
spec = importlib.util.spec_from_file_location("payout_history_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_summarize_buckets():
    rows = [
        (True, True, "2025-03-01", 100, True),
        (True, True, "", 50, True),
        (False, True, "2026-10-01", 0, True),
        (True, False, "", 80, True),
        (True, False, "", 20, False),
        (False, False, "", 70, False),
    ]
    s = audit.summarize(rows)
    assert s["paid"] == (3, 150.0)
    assert s["paid_missing_date"] == (1, 50.0)
    assert s["paid_missing_amount"] == (1, 0.0)
    assert s["paid_in_2025"] == (1, 100.0)
    assert s["finished_unpaid_delivered"] == (1, 80.0)
    assert s["finished_unpaid_undelivered"] == (1, 20.0)
    assert s["active_unpaid"] == (1, 70.0)
