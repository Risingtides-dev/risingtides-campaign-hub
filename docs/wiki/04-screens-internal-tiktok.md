# 4g. The Internal TikTok Tool

**URL:** `/internal`

**Who uses it:** Jake and the Rising Tides team to monitor the performance of their own internal TikTok accounts — accounts owned or managed directly by Rising Tides (not external creator accounts).

---

## What it is

Campaign Hub doesn't just track creator posts for client campaigns — it also monitors a set of "internal" TikTok accounts. These are accounts that Rising Tides controls directly (e.g. personal accounts used by Jake and other team members, or pages associated with labels they work closely with).

The Internal TikTok tool lets the team:
- See all internal TikTok accounts grouped by owner
- Check how many posts those accounts have made recently
- View total views, likes, and post counts for each group
- Browse individual accounts and their video history

---

## Layout description (main page)

```
┌─────────────────────────────────────────────────────────────┐
│ Internal TikTok                                             │
├─────────────────────────────────────────────────────────────┤
│  Time window: [7 days ▼]    [Run Internal Scrape]          │
├─────────────────────────────────────────────────────────────┤
│  PEOPLE                                                     │
│  ┌────────────────────┐  ┌────────────────────┐           │
│  │ jake_balik          │  │ john_smathers       │           │
│  │ 12 accounts        │  │ 8 accounts          │           │
│  │ 2.1M views         │  │ 800K views          │           │
│  │ 45 posts · 90K likes│  │ 20 posts · 40K likes│          │
│  └────────────────────┘  └────────────────────┘           │
├─────────────────────────────────────────────────────────────┤
│  LABELS                                                     │
│  ┌────────────────────┐  ┌────────────────────┐           │
│  │ warner_pages        │  │ atlantic_pages      │           │
│  │ ...                │  │ ...                │           │
│  └────────────────────┘  └────────────────────┘           │
├─────────────────────────────────────────────────────────────┤
│  ALL ACCOUNTS (list to add/remove individual accounts)     │
└─────────────────────────────────────────────────────────────┘
```

---

## The group cards

Internal accounts are organized into **groups** — one group per person or label. Each group card shows:

- **Group name** — the name of the person or label
- **Account count** — how many TikTok accounts are in this group
- **Views** — total views across all accounts in this group (within the selected time window)
- **Posts** — number of posts made within the time window
- **Likes** — total likes within the time window

Click a group card to go to the [Group Detail Page](#the-group-detail-page).

---

## The time window selector

Above the group cards is a dropdown to select how far back to look: 7 days, 14 days, or 30 days. Changing this updates the stats on all group cards.

---

## Run Internal Scrape

The **Run Internal Scrape** button triggers the tool to go out and fetch the latest posts from all internal accounts. This runs in the background — a progress indicator appears showing how many accounts have been checked so far. When it finishes, the stats update automatically.

Scraping takes a few minutes depending on how many accounts are in the system.

---

## Adding and removing accounts

Below the group cards is a section where you can type in a TikTok username to add it to a group, or remove an existing account from the system.

---

## The Group Detail Page

**URL:** `/internal/group/<group-name>`

When you click a group card, you go to a detail page for that group. It shows:

- All the TikTok accounts belonging to that group
- Each account's recent posts, views, and likes
- A breakdown by song/sound — which sounds are those accounts posting to most

This is useful for checking whether a label's pages are using the sounds from active campaigns, or for understanding what content a particular person's accounts are posting.

---

## The Per-Creator Detail Page

**URL:** `/internal/<username>`

Click an individual account within a group to see their full post history:

- Every video cached in the system for that account
- View count, like count, and post date for each video
- Which sound each video used

This is useful for spotting trends in what's performing, and for finding videos that might not have been matched to a campaign yet.
