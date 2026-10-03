# 6. The Money Trail

One of the most important rules in Campaign Hub is knowing **what financial information lives where**. Mixing this up causes errors, duplicate tracking, and confusion. Here's the full answer.

---

## The Golden Rule

> **Money lives here. Performance lives in Cobrand. Client info lives in Notion.**

If you're wondering where to find a financial number or a piece of client info, that single line tells you which tool to open.

---

## Creator rates — Campaign Hub

Every creator booked on a campaign has a **rate** — the total dollar amount Rising Tides agreed to pay them. It's set when the creator is added to the campaign (either by approving a Slack Inbox card or by hand via the Add Creator form).

Campaign Hub also calculates a **per-post rate** automatically: total rate ÷ posts owed.

**Where to find it:** Campaign Detail page → Creators Table → Rate column.

---

## Campaign budgets — Campaign Hub

Each campaign has a total **budget** — the maximum amount Rising Tides can deploy into creator payments for that campaign. This is the internal market deployment amount, not the full client spend. For CPM reporting, Campaign Hub grosses this value up 2x because the deployment amount represents 50% of the client budget.

Campaign Hub tracks four budget numbers automatically:

| Number | What it means |
|---|---|
| **Budget** | Total amount allocated |
| **Booked** | Sum of all creator rates committed so far |
| **Paid** | Amount actually paid out so far |
| **Remaining** | Budget minus what's been paid |

**Where to find it:** Campaign Detail page → stat cards at the top. Also visible (in compressed form) on the Promotions list under the Budget column.

---

## Payments to creators — Campaign Hub

When a creator is actually paid (via PayPal), the team marks it by clicking the checkbox in the Paid column on the Creators Table. Campaign Hub records the payment status and remembers the PayPal email.

The **Paid** stat card at the top of the Campaign Detail page tracks the running total of what's actually been paid out (as opposed to what's been booked / committed but not yet paid).

PayPal emails are remembered across campaigns — if a creator has been paid before, the Add Creator form auto-fills their PayPal email next time they're booked.

**Where to find it:** Campaign Detail page → Creators Table → Paid column + Paid stat card.

---

## Client billing — Notion owns invoices; Campaign Hub derives CPM spend

What the *label* pays Rising Tides (the agency fee, contract terms, invoices) is tracked in Notion, not in Campaign Hub. Campaign Hub stores the budget Rising Tides has allocated to creator payments out of that fee.

For CPM only, Campaign Hub derives gross client spend from the market deployment amount:

```
gross client spend = creator/market deployment spend × 2
```

If you need to know what a label is paying for a campaign, look in Notion.

---

## Performance numbers (views, comments) — NOT here, that's pulled from Cobrand

Campaign Hub *displays* performance numbers (total views and submission counts), but **does not own them**. These numbers are fetched live from Cobrand and shown for convenience. CPM is derived in Campaign Hub from grossed-up client spend and the fetched views. If Cobrand goes offline, Campaign Hub shows the last known numbers but can't update them.

**Never enter performance data manually in Campaign Hub.** If a views number looks wrong, check Cobrand directly or hit the Refresh Stats button to re-pull.

---

## Summary table

| Type of information | Where it lives | Where it does NOT live |
|---|---|---|
| Creator rate / per-post rate | Campaign Hub | Cobrand, Notion |
| Campaign market-deployment budget | Campaign Hub | Cobrand |
| Who's been paid | Campaign Hub | Cobrand, Notion |
| PayPal emails | Campaign Hub | Anywhere else |
| What the label pays Rising Tides | Notion | Campaign Hub |
| Live view counts / engagement | Cobrand (mirrored in Campaign Hub) | Stored permanently in Campaign Hub |
| Client contact info, contracts | Notion | Campaign Hub |

---

## CPM — what it is and why it matters

CPM stands for **Cost Per Mille** ("mille" is Latin for thousand). In practice: how much did it cost for every 1,000 views?

**Formula:** Gross client spend ÷ (total views ÷ 1,000)

**Example:** If a campaign deployed $1,000 to creators, the gross client spend is $2,000. If it got 500,000 views:

```
CPM = $2,000 ÷ (500,000 ÷ 1,000)
    = $2,000 ÷ 500
    = $4.00 per thousand views
```

A **lower CPM** means we're getting more views per dollar — efficient spend. A **higher CPM** might mean creators didn't perform well, or the budget was overallocated relative to what the audience produced.

Campaign Hub calculates CPM automatically. You'll see it on:

- The Promotions list (per campaign)
- The Creator Database (per creator, averaged across all campaigns)
- The Creator Profile page (per campaign and overall)

---

*Next: [The Scrapers](./07-scrapers.md)*
