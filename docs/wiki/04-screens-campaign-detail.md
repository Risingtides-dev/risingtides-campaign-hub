# 4b. The Campaign Detail Page

**URL:** `/campaign/<campaign-name>` (e.g. `/campaign/taylor-swift-shake-it-off`)

**Who uses it:** Anyone managing an active campaign — to check budgets, update creators, track payments, and monitor performance.

---

## How to get here

From the Campaigns List (homepage), click any campaign name. You'll land on that campaign's detail page.

At the top is a breadcrumb that reads **Promotions > Campaign Name** so you always know where you are. Clicking "Promotions" takes you back to the list.

---

## Layout description

```
┌─────────────────────────────────────────────────────────────┐
│ Promotions > Artist - Song Title                            │
├─────────────────────────────────────────────────────────────┤
│  [Campaign Header]                                          │
│  Title / Artist / Song / Sound ID / Budget / Start Date    │
│  [✏ Edit]  [↺ Refresh Stats]  [Cobrand]  [Create Tracker]  │
├─────────────────────────────────────────────────────────────┤
│  [Budget Card]  [Paid Card]  [Remaining Card]  [CPM Card]  │
├─────────────────────────────────────────────────────────────┤
│  [Cobrand Stats Card — submissions, comments]              │
│  [Cobrand Upload Section — copy links + open Cobrand]      │
├─────────────────────────────────────────────────────────────┤
│  [Add Creator Form]                                         │
│  [Creators Table]                                           │
└─────────────────────────────────────────────────────────────┘
```

---

## The Campaign Header

This section shows the campaign's core information:

- **Title** — the campaign name
- **Artist** — the artist's name
- **Song** — the song title
- **Sound ID** — the unique identifier for the TikTok/Instagram sound
- **Budget** — the total budget for this campaign, with a percentage bar showing how much has been committed
- **Start Date** — when the campaign started

**Buttons in the header:**
- **Edit (pencil icon):** Opens an edit form to update the title, sound IDs, budget, or start date. Useful if the label adds more budget or the sound link changes.
- **Refresh Stats (arrow icon):** Triggers a fresh scrape to update the view count and matched video numbers. This kicks off a background process — it takes a minute.
- **Cobrand (bar chart icon):** Toggles the Cobrand section of the page on and off.
- **Create Tracker:** Creates a TidesTracker for this campaign (an internal tracking record). Only appears if a tracker hasn't been set up yet.

---

## The Stats Cards

Four cards showing the financial snapshot at a glance:

| Card | What it shows |
|---|---|
| **Budget** | Total budget for the campaign |
| **Spent** | Total committed to creators (all creator rates added up) |
| **Paid** | Amount actually paid out so far |
| **CPM** | Cost per 1,000 views — lower is better |

---

## The Cobrand Section

This section connects the campaign to Cobrand, the third-party service that tracks live post performance.

**Cobrand Stats Card:** Shows live numbers pulled from Cobrand:
- **Submissions** — how many posts have been submitted to Cobrand for tracking
- **Comments** — total comment count across tracked posts
- **Status** — the current state of the Cobrand campaign

**Cobrand Link Input:** Where you paste the Cobrand "share URL" — the link Cobrand gives you to track this specific campaign. Once it's set, Campaign Hub fetches live stats automatically.

**Cobrand Upload Section:** A helper for getting posts into Cobrand. It shows a list of the scraped post links and a button to copy them all to your clipboard. You then open the Cobrand upload page and paste them in. Campaign Hub can open the Cobrand upload page for you with one click.

---

## The Creators Table

This is the main working area of the page — the list of all creators booked on this campaign.

### Adding a creator

Above the table is an **Add Creator** form. Fill in:
- **Username** — their TikTok or Instagram handle (no @ symbol needed)
- **Posts Owed** — how many videos they agreed to post
- **Total Rate** — the total dollar amount they'll be paid
- **PayPal Email** — where to send the payment (the form tries to auto-fill this if this creator has been paid before)

Click Save and they appear in the table immediately.

### The creators table columns

| Column | What it shows |
|---|---|
| **Creator** | Username, clickable — links to their Creator Profile page |
| **Posts Owed** | How many posts they agreed to deliver |
| **Posts Done** | How many posts have been found/matched |
| **Rate** | Their total payment amount |
| **Per Post** | Rate divided by posts owed — per-video cost |
| **PayPal** | Their PayPal email address |
| **Paid** | Checkbox — green = paid, gray = unpaid. Click to toggle. |
| **Actions** | Edit (pencil) and Remove (trash) icons |

### Editing a creator

Click the pencil icon on any row to edit their posts owed, rate, PayPal email, or notes. Click Save to apply, or Cancel to discard.

### Marking a creator as paid

Click the checkbox in the "Paid" column. It turns green immediately. Click again to mark as unpaid. No page reload needed.

### Removing a creator

Click the trash icon. A confirmation dialog appears — confirm to remove them from the campaign.
