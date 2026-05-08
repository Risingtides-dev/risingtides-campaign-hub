# 4d. The Creator Database

**URL:** `/creators`

**Who uses it:** Anyone who wants to look up a creator across all campaigns — their full history, total earnings, post counts, and average performance. Useful for finding creators to book on new campaigns.

---

## What it is

The Creator Database is a roster of every creator who has ever been booked on any campaign. Unlike the Creators Table on a single Campaign Detail page (which only shows that one campaign's creators), this page shows everyone across every campaign at once.

Think of it as the team's contact book for creators, with performance stats baked in.

---

## Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Creator Database                                                 │
├──────────────────────────────────────────────────────────────────┤
│ [🔍 Search…]  [music] [lifestyle] [comedy] [dance]               │
│                                                  234 creators    │
├────────────┬────────┬──────────┬───────┬────────────┬───────────┤
│ Creator    │ Niches │Campaigns │ Posts │Total Spend │Total Views│
├────────────┼────────┼──────────┼───────┼────────────┼───────────┤
│ @username  │ music  │    5     │ 12/12 │  $1,200    │  450,000  │
│            │ dance  │          │       │            │           │
└────────────┴────────┴──────────┴───────┴────────────┴───────────┘
```

---

## What every column means

| Column | What it shows |
|---|---|
| **Creator** | The creator's username with a TikTok icon. Click the username (or anywhere on the row) to open their full Creator Profile. |
| **Niches** | Colored chips showing what content categories the creator has been tagged with (e.g. music, lifestyle, comedy, dance). Optional — empty if untagged. |
| **Campaigns** | How many different campaigns this creator has been booked on. |
| **Posts** | Total posts delivered over total posts owed across every campaign (e.g. "12 / 12"). |
| **Total Spend** | The sum of all rates committed to this creator. |
| **Total Payout** | The sum of all rates actually paid out. Shown in green if fully paid up. |
| **Total Views** | Combined views across every matched video this creator has across all campaigns. |
| **Avg CPM** | The creator's average cost per 1,000 views across all campaigns. |

All columns can be sorted — click a header to sort, click again to reverse.

---

## The search bar

Type any part of a username to filter the table instantly. The list updates as you type.

---

## Niche filter chips

Below the search bar are colored chips showing the niches creators have been tagged with. Click a chip to filter the list to just creators tagged with that niche. Click it again (or click "Clear") to remove the filter. You can stack multiple niche filters.

If no creators have niche tags yet, no chips appear.

---

## Clicking a creator

Click any row (or the username) to open that creator's [Creator Profile page](./04-screens-creator-profile.md) — a complete view of every campaign they've been on, every post, and their full payment history.

---

## Why this is useful

Before this screen existed, there was no easy way to answer questions like:

- "Has this creator worked with us before?"
- "What rate did we pay them last time?"
- "How many views do they typically get?"

Now all of that is one click away. You can compare CPMs across creators to make better booking decisions on future campaigns, and you can see at a glance who's been paid up and who hasn't.

---

*Next: [Creator Profile Page](./04-screens-creator-profile.md)*
