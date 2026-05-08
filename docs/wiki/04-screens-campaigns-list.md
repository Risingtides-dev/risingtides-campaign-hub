# 4a. The Campaigns List (Promotions Page)

**URL:** `/` (the homepage of Campaign Hub)

**Who uses it:** Everyone, every day. It's the first thing you see when you open Campaign Hub and the starting point for most daily work.

---

## What you see

At the top of the page is a heading that says **"Promotions"** with a blue **+ New Campaign** button on the right.

Below that is a filter bar with two tabs — **Active** and **Finished** — a search box, and a count showing how many campaigns are currently visible.

Below the filter bar is the campaigns table itself.

---

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Promotions                              [+ New Campaign]    │
├─────────────────────────────────────────────────────────────┤
│ [Active (12)]  [Finished (3)]  [🔍 Search…]   12 visible    │
├──┬───────────┬────────┬───────────┬────────┬────────┬──────┬──────────┬──────┤
│✓ │Promotions │ Artist │ Start Date│ Status │ Budget │Views │Live Posts│ CPM  │
├──┼───────────┼────────┼───────────┼────────┼────────┼──────┼──────────┼──────┤
│  │Artist-Song│ Artist │ Apr 12    │ Active │$5,000  │1.2M  │   12     │$2.67 │
│  │Song title │        │           │        │ ███░░  │      │          │      │
└──┴───────────┴────────┴───────────┴────────┴────────┴──────┴──────────┴──────┘
```

---

## What every column means

| Column | What it shows |
|---|---|
| **Checkmark (far left)** | The campaign's completion state. Empty box = in progress. Gray check = booking complete (all creators locked in). Green check = fully wrapped. Click to cycle through the three states. |
| **Promotions** | The campaign title (bold) with the song title in smaller gray text underneath. Click anywhere in the row to open the Campaign Detail page. |
| **Artist** | The artist's name. |
| **Start Date** | When the campaign kicked off. |
| **Status** | A colored pill badge — typically blue for "Active" or green for other statuses. |
| **Budget** | The total budget in bold, a thin blue progress bar showing how much has been spent, then a small detail line: **Booked · Paid · Left**. |
| **Total Views** | Combined view count across every matched video on the campaign. |
| **Live Posts** | Number of posts the scraper has found and matched to this campaign. |
| **CPM** | Cost per thousand views. Lower is better. |

Every column can be sorted — click the column header to sort ascending; click again to reverse. There are also quick-sort buttons above the table for Start Date, A–Z, Overall Cost, Spend %, and Remaining.

---

## The "New Campaign" button

Click the blue **+ New Campaign** button in the top right. A form opens above the table. Fields:

- **Title** — the campaign name (typically "Artist - Song")
- **Artist** — the artist's name
- **Song** — the song title
- **TikTok Sound ID** — the unique TikTok identifier for this song's audio (see [Glossary](./09-glossary.md))
- **Instagram Sound ID** — same for Instagram, if applicable
- **Budget** — total budget Rising Tides will spend on creator payments
- **Start Date** — when the campaign begins
- **Status** — usually "Active"
- **Label** — which label is paying for this
- **Project Lead** — who on the team owns it (usually Jake)

Submit the form and the campaign appears immediately in the Active tab.

---

## The search bar

Type any part of a campaign title, artist name, or song title to filter the table instantly. No need to press Enter. The count on the right updates as you type. Click the **X** to clear the search and show all campaigns again.

---

## Active vs. Finished tabs

- **Active** — campaigns still running (no green checkmark yet). Default tab.
- **Finished** — campaigns that have been fully wrapped (green checkmark).

Click either tab to switch. The search bar works within whichever tab you're viewing.

For more on how the checkbox works, see [Active vs. Finished Tabs](./04-screens-active-finished-tabs.md).

---

## Clicking a row

Click anywhere on a campaign's row to open its [Campaign Detail page](./04-screens-campaign-detail.md).

---

*Next: [Campaign Detail Page](./04-screens-campaign-detail.md)*
