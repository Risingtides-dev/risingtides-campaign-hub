# 4g. The Internal TikTok Tool

**URL:** `/internal`

**Who uses it:** Jake and the Rising Tides team to monitor performance of **internal** TikTok pages — accounts that Rising Tides controls or manages directly (not external creator accounts).

This is the screen for watching the team's own content, plus pages we run on behalf of label partners.

---

## What it is

Beyond tracking external creator posts for client campaigns, Rising Tides also runs a set of in-house TikTok pages — some owned by team members, some run on behalf of labels. The Internal TikTok tool lets the team:

- See all internal accounts grouped by who runs them
- Pull fresh stats for any group with a date range
- Track total views, posts, and likes per group
- Drill into individual accounts and their video history
- Add or remove accounts and reorganize them into groups

---

## Top of the page — group cards

Just below the page heading is a row of four cards covering the main groupings of internal pages:

| Card | What it covers |
|---|---|
| **Internal Pages** | All accounts run by the Rising Tides team — Jake, Smaths (John), Sam, Eric, Johnny, and Seeno's pages |
| **Warner Pages** | Pages run on behalf of Warner |
| **Atlantic Pages** | Pages run on behalf of Atlantic |
| **Warner Test Pages** | Test/sandbox pages for Warner-related work |

Each card shows the group name, how many accounts are in it, and a **Scrape & View Links →** link. Clicking the link opens a scrape view where you can pick a date range and trigger a fresh scan of those accounts' recent posts.

---

## The three tabs

Below the cards, the page has three tabs: **Stats**, **All Accounts**, and **Groups**.

### Stats tab (the default)

Shows a stats card for every group, including per-person breakdowns (one card each for `jake_balik`, `john_smathers`, `sam_hudgens`, `eric_cromartie`, `johnny_balik`, `seeno`) and per-label cards (`warner`, `atlantic`, `warner_test`).

Each card shows:
- Group name
- Account count
- Total views, posts, and likes for the selected date range

A **date-range picker** at the top of the tab controls what window the cards measure (defaults to the last 30 days). Adjusting it updates every card.

Clicking a stats card opens that group's detail page (see "Group Detail Page" below).

### All Accounts tab

A flat list of every internal account being tracked across every group. Each row shows the account's username, total video count, and total views. There's a small **X** button next to each account to remove it from the system entirely.

At the top of the tab is an **Add Creators** form — type one or more TikTok usernames (comma-separated) to add them. New accounts can be assigned to a group from the Groups tab afterwards.

### Groups tab

Where you create, rename, and delete groups. Each group has:

- **Title** — the human-readable name (e.g. "Johnny's Pages")
- **Slug** — the short identifier (e.g. `johnny_balik`) used in URLs and code
- **Kind** — one of `booked_by` (a person who books pages), `label` (a record label's pages), `niche` (a content niche), or `custom` (anything else)

Deleting a group only removes the grouping — it doesn't delete the underlying accounts.

---

## The Group Detail page

**URL:** `/internal/group/<group-slug>`

Click any group card or the "Scrape & View Links" link to land here. It shows:

- Every TikTok account inside that group
- Recent posts, views, and likes for each
- A breakdown by sound — which sounds the group is posting to most
- Tools to trigger a fresh scrape and to add or remove accounts in the group

This is useful for checking whether a label's pages are actively using sounds from running campaigns, or for spotting which person's pages are over- or under-performing.

---

## The per-account detail page

**URL:** `/internal/<username>`

Click an individual account inside a group to see its full post history:

- Every video cached in the system for that account
- View count, like count, comment count, and upload date for each video
- Which sound each video used (sound IDs link out to TikTok)

Useful for spotting trends in what's performing and for finding videos that might not have been matched to a campaign yet.

---

## How this connects to campaigns

The Internal TikTok tool is largely separate from the campaign-creator workflow. But the data overlaps in two places:

1. **Sound tracking.** If the campaign's sound starts showing up across a lot of internal pages, the team can confirm internal activity at a glance.
2. **Johnny.** Johnny runs a group of internal pages (`johnny_balik`) but also gets booked as an external creator on some campaigns. Internal-page activity is tracked here; his external creator bookings live in the [Creator Database](./04-screens-creator-database.md).

---

*Next: [Sidebar / Navigation](./04-screens-sidebar-navigation.md)*
