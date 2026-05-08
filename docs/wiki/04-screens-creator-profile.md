# 4e. The Creator Profile Page

**URL:** `/creators/<username>` (e.g. `/creators/dancegirl_tiktok`)

**Who uses it:** Team members who want to see a creator's full history — what campaigns they've been on, what they were paid, and what posts they delivered.

---

## How to get here

From the **Creator Database** (`/creators`), click any creator's row or username. You can also get here from the Creators Table on a Campaign Detail page by clicking a creator's username.

---

## Layout description

```
┌─────────────────────────────────────────────────────────────┐
│ Creator Database > @username                                │
├─────────────────────────────────────────────────────────────┤
│  @username                                   [↗ TikTok]    │
│  5 campaigns · $1,200 total paid · 450K views · $2.67 CPM  │
├─────────────────────────────────────────────────────────────┤
│  Campaign History                                           │
│  ┌─────────────┬───────────┬──────┬──────┬────────┬──────┐ │
│  │ Campaign    │ Posts Owed│ Done │ Rate │ Paid?  │Views │ │
│  ├─────────────┼───────────┼──────┼──────┼────────┼──────┤ │
│  │ Artist-Song │     3     │  3   │ $300 │ ✓ Paid │ 90K  │ │
│  └─────────────┴───────────┴──────┴──────┴────────┴──────┘ │
├─────────────────────────────────────────────────────────────┤
│  Videos                                                     │
│  ┌─────────────────────┬────────┬────────┬──────────────┐  │
│  │ Post Link           │ Views  │ Likes  │  Campaign    │  │
│  ├─────────────────────┼────────┼────────┼──────────────┤  │
│  │ tiktok.com/...      │ 45,000 │ 3,200  │ Artist-Song  │  │
│  └─────────────────────┴────────┴────────┴──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## The creator summary header

At the top of the page you see the creator's username, a link to their TikTok profile, and four summary stats:

| Stat | What it means |
|---|---|
| **Campaigns** | Total number of campaigns this creator has been booked on |
| **Total Paid** | All payments made to them, summed across all campaigns |
| **Views** | Total views across all their matched posts |
| **CPM** | Their average cost per 1,000 views |

---

## Campaign History table

A row for every campaign this creator has been part of. Columns:

| Column | What it shows |
|---|---|
| **Campaign** | Campaign name — click to go to the Campaign Detail page |
| **Posts Owed** | How many posts they agreed to deliver for that campaign |
| **Posts Done** | How many posts the scraper found for them on that campaign |
| **Rate** | How much they were paid for that campaign |
| **Paid?** | Whether they've been paid — green ✓ or gray |
| **Views** | Total views from their posts on that campaign |

All columns can be sorted.

---

## Videos table

A list of every individual post (video) matched to this creator across all campaigns. Columns:

| Column | What it shows |
|---|---|
| **Post Link** | A clickable link directly to the TikTok or Instagram video |
| **Views** | How many views the video has |
| **Likes** | How many likes the video has |
| **Campaign** | Which campaign this post was matched to |

All columns can be sorted.

---

## Note on TikTok vs. Instagram links

Currently, the profile page shows a "View on TikTok" link for all creators. Improving this so it shows TikTok links for TikTok creators and Instagram links for Instagram creators is a known pending item — see [What's Currently In Progress](./08-whats-in-progress.md).
