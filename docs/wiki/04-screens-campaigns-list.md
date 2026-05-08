# 4a. The Campaigns List (Homepage)

**URL:** `/` (the main page of Campaign Hub)

**Who uses it:** Everyone, every day. This is the first thing you see when you open Campaign Hub.

---

## What you see

The Campaigns List is the home screen. At the top is a heading that says **"Promotions"** and a blue **"New Campaign"** button in the top right.

Below that is a white card with two tabs — **Active** and **Finished** — and a search bar. The number of campaigns in each tab is shown in parentheses next to the tab name.

Under that is the campaigns table.

---

## Layout description

```
┌─────────────────────────────────────────────────────────────┐
│ Promotions                              [+ New Campaign]    │
├─────────────────────────────────────────────────────────────┤
│ [Active (12)]  [Finished (3)]  [🔍 Search campaigns...]    │
├────┬────────────────┬────────┬───────┬──────┬──────┬───────┤
│ ✓  │ Campaign       │ Budget │ Spent │ Paid │ Views│  CPM  │
├────┼────────────────┼────────┼───────┼──────┼──────┼───────┤
│    │ Artist - Song  │ $5,000 │$3,200 │$2,800│ 1.2M │ $2.67 │
│    │ ...            │  ...   │  ...  │  ... │  ... │  ...  │
└────┴────────────────┴────────┴───────┴──────┴──────┴───────┘
```

---

## What every column means

| Column | What it shows |
|---|---|
| **Checkmark (✓)** | The campaign's completion status. Empty box = in progress. Gray check = booking complete. Green check = fully wrapped. Click to cycle through the states. |
| **Campaign** | The campaign name (artist + song). Click to open the Campaign Detail page. |
| **Budget** | The total amount Rising Tides has to spend on creator payments for this campaign. |
| **Spent** | How much has already been committed (i.e., total of all creator rates booked so far). |
| **Paid** | How much has actually been paid out to creators so far. |
| **Views** | Total views across all the scraped/matched videos for this campaign. |
| **CPM** | Cost Per Thousand views — how much it's costing per 1,000 views based on what's been paid. A lower number is better. |

All columns except Campaign can be sorted — click the column header to sort ascending or descending.

---

## The "New Campaign" button

Click the blue **+ New Campaign** button in the top right. A form slides open below the button asking for:

- **Title** — usually "Artist Name - Song Name" (e.g. "Taylor Swift - Shake It Off")
- **Artist** — the artist's name
- **Song** — the song title
- **Sound ID** — the unique TikTok or Instagram identifier for this song's sound (see Glossary)
- **Budget** — the total budget in dollars
- **Platform** — TikTok, Instagram, or both
- **Start Date** — when the campaign begins

Fill it in and click Save. The campaign appears immediately in the Active tab.

---

## The search bar

Type any part of a campaign name, artist, or song to filter the table instantly. The count on the right updates as you type. Click the X button to clear the search.

---

## Active vs. Finished tabs

- **Active tab:** Campaigns that are still running — no green checkmark yet.
- **Finished tab:** Campaigns that have been marked as fully wrapped (green checkmark).

Click either tab to switch. The search works within whichever tab is showing.

See also: [Active vs. Finished Tabs](./04-screens-active-finished-tabs.md)
