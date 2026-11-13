#!/usr/bin/env python3
"""payout_history_audit.py — how trustworthy is the Hub's payment history?

Creator dashboards build "Payment history" from every booking marked paid
(`creators.paid = 'yes'`). This read-only report shows how complete that
is, so we know what to clean up before creators rely on it.

Prints counts and dollar totals only — no handles or payment details.

Usage (from the Hub repo):
    railway run --service Postgres python3 scripts/payout_history_audit.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

from sqlalchemy import create_engine, text


def _engine():
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL") or ""
    if not url:
        sys.exit("No DATABASE_PUBLIC_URL / DATABASE_URL. Run via `railway run --service Postgres`.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, hide_parameters=True)


QUERY = text("""
    SELECT COALESCE(c.completion_status, 'none') = 'completed' AS finished,
           LOWER(COALESCE(cr.paid, 'no')) = 'yes'              AS paid,
           COALESCE(cr.payment_date, '')                         AS payment_date,
           COALESCE(cr.total_rate, 0)                            AS amount,
           COALESCE(cr.posts_owed, 0) <= COALESCE(cr.posts_done, 0)
               AND COALESCE(cr.posts_owed, 0) > 0               AS delivered
    FROM creators cr JOIN campaigns c ON c.id = cr.campaign_id
    WHERE COALESCE(cr.status, 'active') <> 'removed'
""")


def summarize(rows) -> dict:
    buckets: dict[str, list] = defaultdict(lambda: [0, 0.0])

    def add(key, amount):
        buckets[key][0] += 1
        buckets[key][1] += float(amount or 0)

    for finished, paid, payment_date, amount, delivered in rows:
        if paid:
            add("paid", amount)
            add("paid_with_date" if payment_date else "paid_missing_date", amount)
            if payment_date:
                add(f"paid_in_{payment_date[:4]}", amount)
            if not amount:
                add("paid_missing_amount", amount)
        elif finished:
            add("finished_unpaid_delivered" if delivered else "finished_unpaid_undelivered", amount)
        else:
            add("active_unpaid", amount)
    return {k: (v[0], round(v[1], 2)) for k, v in sorted(buckets.items())}


LABELS = {
    "paid": "Marked paid (shows in creator history)",
    "paid_with_date": "  …with a payment date",
    "paid_missing_date": "  …no payment date (shows 'Date not recorded')",
    "paid_missing_amount": "  …$0 / no rate on file",
    "active_unpaid": "Active campaigns, unpaid (the payment queue)",
    "finished_unpaid_delivered": "Finished, delivered, NOT marked paid (probably paid outside the Hub?)",
    "finished_unpaid_undelivered": "Finished, not delivered, not paid",
}


def main() -> int:
    with _engine().connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        summary = summarize(conn.execute(QUERY).all())
        conn.rollback()
    for key, (count, dollars) in summary.items():
        label = LABELS.get(key, f"  paid in {key[-4:]}" if key.startswith("paid_in_") else key)
        print(f"{label:<75} {count:>6} rows  ${dollars:>12,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
