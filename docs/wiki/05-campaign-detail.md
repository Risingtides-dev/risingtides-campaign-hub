# 5. The Campaign Detail Page

**Where:** Click any campaign row on the Promotions page to land here. The web address looks like `/campaign/sombr-homewrecker-promo-r3`.

**Who uses it:** Jake and the team for day-to-day campaign management — adding creators, tracking payments, checking performance.

---

## Layout Overview

The page is organized top to bottom:

1. **Breadcrumb** — shows "Promotions › Campaign Name" so you know where you are and can click back
2. **Campaign header** — title, artist, song, dates, and action buttons
3. **Budget and stats cards** — at-a-glance numbers
4. **Cobrand section** — live performance data from Cobrand
5. **Creator table** — every creator booked on this campaign

---

## The Campaign Header

At the top of the page you'll see the campaign title in large text, with the artist and song name below it. Also shown: the start date, platform (TikTok or Instagram), label, round number, and campaign stage.

**Buttons in the header:**

- **Edit** — Opens an edit form where you can change the campaign title, artist, song, sound ID, budget, dates, and other metadata. Changes save immediately.
- **Refresh Stats** — Triggers the scraper to re-check all creator accounts for new posts. The button spins while it runs. Use this when you think a creator just posted and you want to see it immediately.
- **Cobrand** — Shows or hides the Cobrand integration section below.
- **Create Tracker** — (only visible if a Cobrand link hasn't been added yet) Sets up a TidesTracker link for the campaign.

---

## Budget and Stats Cards

Four stat cards sit side-by-side below the header:

| Card | What it shows |
|---|---|
| **Budget** | Total budget, and a breakdown: Booked (total rate of all creators), Paid (what's actually been paid out), and Remaining (budget minus paid). |
| **Budget Used** | A percentage: paid ÷ total budget. A progress bar fills as you pay creators. |
| **Live Posts** | How many creator posts have been found and matched to this campaign. |
| **Total Views / CPM** | Combined views on matched posts, and CPM (cost per thousand views). |

These update every time you refresh the page or take an action.

---

## The Cobrand Section

If you've added a Cobrand share link to this campaign, a stats card appears showing:

- **Submissions** — how many posts have been submitted to Cobrand
- **Comments** — engagement comments
- **Status** — the Cobrand campaign status (active, complete, etc.)

Below the stats, there's an embedded Cobrand upload page where you can paste post links directly without leaving Campaign Hub.

**To connect Cobrand:** Click the Cobrand button in the header (or paste the share URL into the input field that appears). Once saved, Campaign Hub automatically refreshes Cobrand stats in the background.

---

## The Creator Table

The main table shows every creator booked on this campaign. Each column is sortable.

**Columns:**

| Column | What it shows |
|---|---|
| **Creator** | Their username, clickable — goes to their creator profile page |
| **Platform** | TikTok or Instagram |
| **Posts Owed** | How many posts they agreed to make |
| **Posts Done** | How many posts the scraper has found from them |
| **Posts Matched** | Posts confirmed to match the campaign sound |
| **Rate** | Their total agreed rate for this campaign |
| **Per Post** | Rate divided by posts owed |
| **PayPal** | Their PayPal email (auto-filled if they've been paid before) |
| **Paid** | Checkbox — click to mark as paid. Also shows payment date if set. |
| **Notes** | Any notes about this creator on this campaign |
| **Remove** | A trash icon to remove this creator from the campaign |

**Clicking a creator's username** takes you to their full creator profile, where you can see all campaigns they've ever been on.

---

## Adding a Creator

Below the header (or via a button on the page) is the **Add Creator** form. Fill in:

- **Username** — their TikTok or Instagram handle (without the @)
- **Platform** — TikTok or Instagram
- **Posts Owed** — how many posts they're contracted for
- **Total Rate** — their total payment for this campaign
- **PayPal Email** — optional, auto-filled if they've been here before
- **Notes** — optional notes

Click Add. They appear in the table immediately.

---

## Editing a Creator

Click the pencil icon next to any creator in the table to edit their details inline — rate, posts owed, PayPal email, notes. Changes save when you click the checkmark.

---

*Next: [Creator Database →](06-creator-database.md)*
