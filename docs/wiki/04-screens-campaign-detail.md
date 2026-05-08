# 4b. The Campaign Detail Page

**URL:** `/campaign/<slug>` (e.g. `/campaign/taylor-swift-shake-it-off`)

**Who uses it:** Anyone managing an active campaign — to check budgets, add or update creators, mark payments, monitor performance, and prepare links for Cobrand.

---

## How to get here

From the Promotions list, click any campaign's row. You land on that campaign's detail page.

A breadcrumb at the top reads **Promotions > Campaign Name** so you always know where you are. Clicking "Promotions" takes you back to the list.

---

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Promotions > Artist - Song Title                            │
├─────────────────────────────────────────────────────────────┤
│  Campaign Header                                            │
│  Title / Artist / Song / Sound IDs / Status / Start         │
│  [✏ Edit]  [↺ Refresh]  [Cobrand]  [Create Tracker]         │
├─────────────────────────────────────────────────────────────┤
│  [Budget]  [Booked]  [Paid]  [Remaining]                    │
├─────────────────────────────────────────────────────────────┤
│  Cobrand share-URL input                                    │
│  Cobrand Stats Card (submissions, comments, status)         │
├─────────────────────────────────────────────────────────────┤
│  Share with Client (link to client-facing view)             │
├─────────────────────────────────────────────────────────────┤
│  Add Creator form                                           │
│  Creators Table                                             │
├─────────────────────────────────────────────────────────────┤
│  Cobrand Upload Section (visible when Cobrand toggle is on) │
└─────────────────────────────────────────────────────────────┘
```

---

## The campaign header

Top section. Shows the campaign's core information:

- **Title** — the campaign name
- **Artist** — the artist's name
- **Song** — the song title
- **Sound IDs** — TikTok and (if set) Instagram sound IDs
- **Budget** — the total budget, with a percentage bar showing how much has been committed
- **Start Date** — when the campaign started
- **Status** — the current status badge

### Header buttons

| Button | What it does |
|---|---|
| **Edit (pencil icon)** | Opens an inline form to update the title, artist, song, sound IDs, budget, start date, status, label, and project lead. Useful when the label adds budget or the sound link changes. |
| **Refresh (arrow icon)** | Triggers a fresh scrape to find new posts and update view counts. Runs in the background — takes a minute. |
| **Cobrand (bar chart icon)** | Toggles the Cobrand Upload Section at the bottom of the page on and off. |
| **Create Tracker** | Creates a TidesTracker record for this campaign (an internal tracking record). Only appears if a tracker hasn't been set up yet. |

---

## The stats cards

Four cards under the header that show the financial snapshot at a glance:

| Card | What it shows |
|---|---|
| **Budget** | Total budget for the campaign |
| **Booked** | Sum of all creator rates committed so far |
| **Paid** | Amount actually paid out so far |
| **Remaining** | Budget minus the amount paid out |

---

## The Cobrand section

This connects the campaign to Cobrand, the third-party service that tracks live post performance.

**Cobrand Share-URL Input:** A field where you paste the Cobrand "share URL" — a special link Cobrand provides for tracking this specific campaign. Once it's saved, Campaign Hub fetches live stats from it automatically.

**Cobrand Stats Card:** Once the share URL is set, this card appears showing live numbers pulled from Cobrand:
- **Submissions** — how many post links have been entered into Cobrand
- **Comments** — total comment count across tracked posts
- **Status** — Cobrand's current status for the campaign

**Cobrand Upload Section** (at the very bottom, visible when the **Cobrand** toggle is on): Lists every scraped post link for the campaign. There's a button to **Copy All Links** to your clipboard, plus a one-click link that opens the Cobrand upload page so you can paste them in.

---

## Share with Client

A separate section that generates a public share link the team can send to the label. The label can open that link to see live campaign performance without needing access to Campaign Hub itself.

---

## The Creators Table

This is the main working area of the page. Above the table is an **Add Creator** form, and below it is the table of every creator booked on this campaign.

### Adding a creator

The Add Creator form takes:
- **Username** — TikTok or Instagram handle (no @ symbol needed)
- **Posts Owed** — how many videos they agreed to post
- **Rate** — the total dollar amount they'll be paid
- **PayPal Email** — auto-fills if this creator has been paid before (the system remembers across campaigns)
- **Notes** — optional free-text notes (e.g. "wants payment up front", "delivers fast")

Click **Save** and the creator appears in the table immediately.

### The creators table columns

| Column | What it shows |
|---|---|
| **Creator** | Username with a TikTok icon. Click the username to open their [Creator Profile](./04-screens-creator-profile.md). |
| **Posts** | Posts done over posts owed (e.g. "3 / 5"). |
| **Rate** | Total dollar amount agreed for this creator on this campaign. |
| **PayPal** | Their PayPal email. |
| **Status** | Active or inactive on this campaign. |
| **Paid** | Checkbox — green check = paid, empty = unpaid. Click to toggle. Saves instantly, no reload. |
| **Notes** | Any notes attached to this creator for this campaign. |
| **Actions** | Edit (pencil) and Remove (trash) icons. |

### Editing a creator

Click the pencil icon on any row. An inline edit form lets you change posts owed, rate, PayPal, status, or notes. Save to apply, or Cancel to discard.

### Marking a creator as paid

Click the checkbox in the Paid column. It turns green immediately. Click again to mark unpaid. The Paid stat card at the top updates automatically.

### Removing a creator

Click the trash icon. A confirmation dialog appears — confirm to remove them from the campaign.

---

*Next: [Active vs. Finished Tabs](./04-screens-active-finished-tabs.md)*
