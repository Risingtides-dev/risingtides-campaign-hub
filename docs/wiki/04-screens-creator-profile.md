# 4e. The Creator Profile Page

**URL:** `/creators/<username>` (e.g. `/creators/dancegirl_tiktok`)

**Who uses it:** Anyone looking up a specific creator's history — what campaigns they've been on, what they were paid, and what posts they've delivered.

---

## How to get here

From the [Creator Database](./04-screens-creator-database.md), click any creator's row or username. You can also reach this page from any [Campaign Detail page](./04-screens-campaign-detail.md) by clicking a creator's username in the Creators Table.

---

## Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Creator Database > @username                                     │
├──────────────────────────────────────────────────────────────────┤
│  @username                            paypal@email   [↗ TikTok]  │
├──────────────────────────────────────────────────────────────────┤
│ [Campaigns] [Total Spend] [Total Payout] [Posts] [Views] [CPM]   │
├──────────────────────────────────────────────────────────────────┤
│  Campaign History                                                │
│  ┌────────────┬───────┬──────┬────────┬────────┬──────────────┐ │
│  │ Campaign   │Posts  │ Rate │ Paid?  │Status  │Notes          │ │
│  ├────────────┼───────┼──────┼────────┼────────┼──────────────┤ │
│  │Artist-Song │  3/3  │ $300 │ ✓      │Active  │              │ │
│  └────────────┴───────┴──────┴────────┴────────┴──────────────┘ │
├──────────────────────────────────────────────────────────────────┤
│  Live Posts                                                      │
│  ┌────────────┬─────────────────┬───────┬──────┬────────────┐   │
│  │ Campaign   │ Post Link       │ Views │Likes │ Date       │   │
│  ├────────────┼─────────────────┼───────┼──────┼────────────┤   │
│  │Artist-Song │ tiktok.com/...  │45,000 │3,200 │ 2026-04-15 │   │
│  └────────────┴─────────────────┴───────┴──────┴────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## The header

At the top of the page:
- **Username** (large)
- The creator's PayPal email if it's on file
- A **View on TikTok** button that opens their TikTok profile in a new tab

> **Known issue:** the "View on TikTok" link currently shows for every creator, even ones who only post on Instagram. Making it platform-aware (TikTok link for TikTok creators, Instagram for Instagram, both if both) is on the to-do list — see [What's In Progress](./08-whats-in-progress.md).

---

## The stat cards

A row of six small cards summarizing the creator's history across every campaign:

| Card | What it shows |
|---|---|
| **Campaigns** | How many different campaigns they've been booked on |
| **Total Spend** | Sum of all rates committed to them |
| **Total Payout** | Sum of all rates actually paid (with a "% paid" sub-label) |
| **Posts** | Total posts delivered over total posts owed |
| **Total Views** | Combined views across all their matched posts |
| **Avg CPM** | Their average cost per 1,000 views |

---

## Campaign History table

A row for every campaign this creator has been part of. Columns:

| Column | What it shows |
|---|---|
| **Campaign** | Campaign name. Click to open the Campaign Detail page. |
| **Posts** | Posts done over posts owed (e.g. "3 / 3"). |
| **Rate** | What they were paid for that campaign. |
| **Paid?** | Green ✓ if paid, red/empty if not. |
| **Status** | Active or inactive on that campaign. |
| **Notes** | Any campaign-specific notes attached to this creator. |

All columns can be sorted.

---

## Live Posts table

Only appears if the scraper has matched videos for this creator. A row for each individual post, across every campaign:

| Column | What it shows |
|---|---|
| **Campaign** | Which campaign this post was matched to (clickable) |
| **Post** | Direct link to the actual TikTok or Instagram video |
| **Views** | View count |
| **Likes** | Like count |
| **Date** | When the post was uploaded |

All columns can be sorted.

---

## What's not on this page

- **Editing the creator's username or PayPal email globally** — those edits happen per campaign on the Campaign Detail page (the system will then auto-fill PayPal across future campaigns once it learns the new value).
- **Direct payment processing** — Campaign Hub records *whether* a creator was paid, but actual PayPal transfers happen outside the app.

---

*Next: [Slack Inbox](./04-screens-slack-inbox.md)*
