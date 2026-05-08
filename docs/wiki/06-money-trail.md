# 6. The Money Trail

There are three systems involved in Rising Tides' business, and each one owns a different piece of the financial picture. The most important thing to understand is what lives where — because putting money information in the wrong place creates confusion and errors.

---

## The golden rule

> **Money owed to creators and campaign budgets live in Campaign Hub.**
> **What labels pay Rising Tides lives in Notion.**
> **Performance numbers (views, comments) live in Cobrand.**

Never mix these up.

---

## Creator rates

**Where it lives:** Campaign Hub, on each campaign's creator table.

Each creator booked on a campaign has a "Rate" — the total dollar amount Rising Tides agreed to pay them for their posts on that campaign. This is set when you add the creator to the campaign and can be edited later.

Example: "@username owes 5 posts at a total rate of $350" — that $350 is stored in Campaign Hub.

## Campaign budgets

**Where it lives:** Campaign Hub, on each campaign.

When a campaign is created, a total budget is entered. That's the total amount Rising Tides has allocated to pay creators for this campaign.

The budget section on the campaign list shows:
- **Total** — the full budget amount
- **Booked** — how much of that budget is committed to creators (sum of all creator rates)
- **Paid** — how much has actually been paid out so far (sum of rates for creators marked "Paid")
- **Left** — how much of the budget is uncommitted (Total minus Booked)
- **Spend %** — what percentage of the budget is already committed

The progress bar on the campaigns list fills up as Booked approaches Total.

## Payments to creators

**Where it lives:** Campaign Hub, on each campaign's creator table.

The "Paid" checkbox on each creator row tracks whether that creator has been paid. When you check it, the "Paid" amount in the campaign budget updates accordingly.

Creator PayPal emails are stored in Campaign Hub so the team knows where to send payments. (Campaign Hub doesn't send payments automatically — that's done manually through PayPal.)

## What the label pays Rising Tides

**Where it lives:** Notion.

The label's invoice, the contract, how much they're paying Rising Tides for the campaign, the payment schedule — none of that is in Campaign Hub. That's all managed in Notion as part of the client relationship.

Campaign Hub only tracks what Rising Tides pays out. It doesn't know (or need to know) what the label is paying Rising Tides.

## Performance numbers

**Where it lives:** Cobrand (read-only in Campaign Hub).

Views, likes, comments, submission counts — these are performance metrics, not money. They live in Cobrand. Campaign Hub displays them for convenience (by pulling them from Cobrand in real time), but it doesn't store or own them. If Cobrand's numbers look wrong, the source of truth is Cobrand's own dashboard, not Campaign Hub.

CPM (cost per thousand views) is calculated by Campaign Hub using the budget data it owns and the view data it reads from Cobrand. It's a derived number, not stored directly.

---

## Summary table

| Information | Lives in | Who owns it |
|------------|----------|------------|
| Creator rates | Campaign Hub | Rising Tides (this app) |
| Campaign budgets | Campaign Hub | Rising Tides (this app) |
| Who's been paid | Campaign Hub | Rising Tides (this app) |
| Creator PayPal emails | Campaign Hub | Rising Tides (this app) |
| Label billing / invoices | Notion | Rising Tides (CRM) |
| Views, likes, comments | Cobrand | Cobrand (third party) |
| Submission counts | Cobrand | Cobrand (third party) |
| CPM (calculated) | Campaign Hub | Derived from budget + Cobrand views |

---

*Next: [The Scrapers](07-scrapers.md)*
