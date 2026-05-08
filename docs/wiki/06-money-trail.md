# 6. The Money Trail

One of the most important rules in Campaign Hub is knowing **what financial information lives where**. Mixing this up causes errors, duplicate tracking, and confusion.

Here's the complete answer.

---

## The Golden Rule

> **Money lives here (Campaign Hub). Performance lives in Cobrand. Client info lives in Notion.**

If you're wondering where to find a number, this rule tells you which tool to open.

---

## Creator rates — lives in Campaign Hub

Every creator booked on a campaign has a **rate** — the total dollar amount Rising Tides agreed to pay them. This is entered when the creator is added to the campaign, either through the Slack Inbox (Approve flow) or manually via the Add Creator form.

Each creator also has a **per-post rate**, which Campaign Hub calculates automatically: total rate ÷ posts owed.

Where to find it: Campaign Detail page → Creators Table → "Rate" and "Per Post" columns.

---

## Campaign budgets — lives in Campaign Hub

Each campaign has a total **budget** — the maximum amount Rising Tides can spend on creator payments for that campaign. The budget is set when the campaign is created and can be edited later.

Campaign Hub tracks three budget numbers automatically:

| Number | What it means |
|---|---|
| **Budget** | The total amount allocated |
| **Spent** | The sum of all creator rates (committed money) |
| **Remaining** | Budget minus Spent |

Where to find it: Campaign Detail page → Stats Cards at the top. Also in the Campaigns List → Budget, Spent columns.

---

## Payments to creators — lives in Campaign Hub

When a creator is actually paid (via PayPal), the team marks them as paid by clicking the checkbox in the Creators Table. Campaign Hub records the payment status and the PayPal email used.

The **Paid** column on the Campaign Detail page shows who's been paid and who hasn't. The **Paid** stat card shows the running total of what's actually been paid out (as opposed to committed/booked).

Where to find it: Campaign Detail page → Creators Table → "Paid" column + "Paid" stat card.

---

## Client billing — NOT here, that's in Notion

What the label pays Rising Tides (the agency fee) is tracked in Notion, not in Campaign Hub. Campaign Hub doesn't know how much the label is paying — it only knows the budget that Rising Tides has allocated to creator payments.

If you need to know what a label is paying for a campaign, look in Notion.

---

## Performance numbers (views, comments) — NOT here, that's pulled from Cobrand

Campaign Hub displays performance numbers (total views, CPM, submission counts) but **does not own them**. These numbers are fetched live from Cobrand and shown for convenience. If Cobrand goes offline, Campaign Hub shows the last known numbers but can't update them.

Never enter performance data manually in Campaign Hub — if you see a views number that looks wrong, check Cobrand directly or trigger a stats refresh.

---

## Summary table

| Type of information | Where it lives | Where it does NOT live |
|---|---|---|
| Creator rate / per-post rate | Campaign Hub | Cobrand, Notion |
| Campaign budget | Campaign Hub | Cobrand, Notion |
| Who's been paid | Campaign Hub | Cobrand, Notion |
| PayPal emails | Campaign Hub | Anywhere else |
| What the label pays Rising Tides | Notion | Campaign Hub |
| Live view counts / engagement | Cobrand (shown in Campaign Hub) | Stored permanently in Campaign Hub |
| Client contact info | Notion | Campaign Hub |

---

## CPM — what it is and why it matters

CPM stands for "Cost Per Mille" — "mille" is Latin for thousand. In practice it means: how much did it cost for every 1,000 views?

**Formula:** Total paid ÷ (total views ÷ 1,000)

**Example:** If a campaign paid $1,000 to creators and got 500,000 views:
- CPM = $1,000 ÷ 500 = $2.00

A **lower CPM** means you're getting more views per dollar — the campaign is efficient. A high CPM might mean the creators didn't perform well, or the budget was overallocated.

Campaign Hub calculates CPM automatically. You'll see it in the Campaigns List (per campaign) and in the Creator Database (per creator, across all campaigns).
