# 4. The Screens

This section walks through every page in Campaign Hub — what you see, what it's for, who uses it, and what every button and column does.

Screenshots are not included in this version of the wiki. Each screen is described in enough detail that you should be able to open the app alongside this page and follow along.

---

## Navigation sidebar

**Where:** The narrow panel on the left side of every page.

**What you see:** The sidebar has the "Campaign Tracker" logo at the top, then a list of navigation sections. Each section has one or more links. Clicking a link takes you to that page.

**Sections and links:**
- **Campaigns:** Promotions, Scrape Tasks
- **Creators:** Creator Database
- **Internal:** Internal TikTok
- **Outreach:** Outreach Hub
- **Intake:** Slack Inbox
- **Tracking:** TidesTrackers
- **Distribution:** Sound Assignments

The currently active page is highlighted in blue with a blue left border.

**On mobile:** The sidebar is hidden by default. A hamburger menu button (three horizontal lines) appears in the top-left corner. Tapping it slides the sidebar in from the left. Tapping anywhere outside the sidebar closes it again.

---

## Promotions (the homepage)

**URL:** The main page when you open Campaign Hub.

**Who uses it:** Everyone. This is the first thing you see.

**What you see:**

At the top: the page title "Promotions" on the left, and a blue "New Campaign" button on the right.

Below that: a filter bar with two parts — on the left, tabs that say "Active" and "Finished" (with a count in parentheses if there are any), and a search box next to them. On the far right of the filter bar, a count shows how many campaigns are currently visible.

Below the filter bar: a table of campaigns.

**The tabs:**
- **Active** — all campaigns that haven't been marked as fully finished. This is the default tab.
- **Finished** — campaigns where Jake has clicked the green checkmark to close them out.

**The search box:** Type anything — a campaign name, artist name, song name — and the table instantly filters down to matching campaigns without reloading the page.

**The New Campaign button:** Opens a form at the top of the page where you can fill in a new campaign's details. Fields include: title, artist, song name, TikTok sound ID, Instagram sound ID, budget, start date, status, label, and project lead. Submitting the form creates the campaign and adds it to the table.

**The campaign table columns:**

| Column | What it shows |
|--------|---------------|
| (checkbox) | The completion status — empty = running, gray check = booking done, green check = fully wrapped. Click to cycle. |
| Promotions | Campaign name (bold) with the song title underneath in gray |
| Artist | The artist's name |
| Start Date | When the campaign kicked off |
| Status | A colored pill: blue for "Active," green for other statuses |
| Budget | Total budget (bold), a blue progress bar showing spend %, then a detail line: Booked / Paid / Left |
| Total Views | Total views across all matched videos |
| Live Posts | Number of posts that have been found and matched |
| CPM | Cost per thousand views — lower is better |

**Sort options:** Above the table, buttons let you sort by Start Date, A–Z, Overall Cost, Spend %, or Remaining budget. You can also click any column header to sort by that column.

**Clicking a row:** Takes you to that campaign's detail page.

---

## Campaign Detail Page

**URL:** Each campaign has its own page (e.g., `/campaign/artist-song-promo-r1`).

**Who uses it:** Jake and the team, constantly. This is where all the day-to-day campaign work happens.

**What you see, top to bottom:**

**Breadcrumb:** "Promotions > [Campaign Name]" — clicking "Promotions" takes you back to the main list.

**Campaign header:** A white card at the top with:
- Campaign title (large, bold)
- Artist name and song name underneath
- A row of action buttons: Edit (opens an inline edit form), Refresh (re-runs the video scraper to find new posts), Cobrand (toggles the Cobrand upload section at the bottom), and Create Tracker (creates a new Cobrand tracking page for the campaign)
- The campaign's status badge and completion indicator

**Stat cards:** Four small cards showing at a glance: total budget, amount booked (committed to creators), amount paid out, and amount remaining.

**Cobrand tracking link input:** A text field where you paste the Cobrand share URL for this campaign. Once saved, Campaign Hub will automatically pull live stats from Cobrand and show them below.

**Cobrand stats card:** (Appears once a tracking URL is saved.) Shows live numbers pulled from Cobrand: total submissions, comments, and engagement. These update automatically — you don't need to click anything.

**Share with Client:** A section for generating a link you can share with the label client so they can view campaign stats.

**Add Creator form:** A form at the bottom of the main section where you can add a new creator to this campaign. Fields: TikTok username, number of posts owed, rate (in dollars), PayPal email, and optional notes.

**Creators table:** A table listing every creator booked on this campaign. Columns:

| Column | What it shows |
|--------|---------------|
| Creator | @username, with a TikTok icon link to their profile |
| Posts | Posts done / Posts owed (e.g., "3 / 5") |
| Rate | Dollar amount agreed for all their posts |
| PayPal | Their PayPal email for payment |
| Status | Active or inactive on this campaign |
| Paid | Checkbox — green check means paid, empty means unpaid. Click to toggle. |
| Notes | Any notes about this creator for this campaign |
| Actions | Edit (pencil icon) and Remove (trash icon) buttons |

Clicking a creator's username takes you to their profile page.

**Cobrand upload section:** (At the very bottom, visible only when you click the "Cobrand" button in the header.) Shows all the video links that have been scraped for this campaign, with a button to copy them all to your clipboard. Also includes a link that opens the Cobrand upload page so you can paste the links in.

---

## Active vs. Finished tabs

These are part of the Promotions page, not a separate page. See the Promotions section above for details.

The key point: a campaign moves to the Finished tab when Jake clicks its completion checkbox all the way to the green checkmark. To move it back to Active, click the green checkmark again to cycle it back to empty.

---

## Creator Database

**URL:** `/creators`

**Who uses it:** Anyone who wants to look up a creator's history across all campaigns, or find creators to book for a new campaign.

**What you see:**

At the top: the page title "Creator Database."

Below that: a search box, niche filter chips (colored category tags), and a count of how many creators are shown.

Below that: a table of every creator who has ever been booked on any campaign in Campaign Hub.

**Search:** Type a username to filter instantly.

**Niche filter chips:** If creators have been tagged with content niches (e.g., "music," "lifestyle"), small colored chips appear that you can click to filter by niche. Click a chip to filter, click again to clear. A "clear" link appears when a filter is active.

**The creator table columns:**

| Column | What it shows |
|--------|---------------|
| Creator | @username with a TikTok icon link. Clicking the username goes to their profile. |
| Niches | Colored tags showing what content categories this creator works in |
| Campaigns | How many campaigns this creator has been part of |
| Posts | Total posts delivered / total posts owed across all campaigns |
| Total Spend | How much Rising Tides has committed to pay this creator in total |
| Total Payout | How much has actually been paid — shown in green if fully paid up |
| Total Views | Total views across all their matched videos |
| Avg CPM | Average cost per thousand views across all their campaigns |

**Clicking a row or username:** Goes to that creator's individual profile page.

---

## Creator Profile Page

**URL:** `/creators/@username`

**Who uses it:** Anyone looking up a specific creator's history and performance.

**What you see:**

**Breadcrumb:** "Creator Database > @username"

**Header card:** Shows the creator's username (large), their PayPal email if on file, and a "View on TikTok" button that opens their TikTok profile.

**Stat cards:** A row of six cards showing: Campaigns count, Total Spend, Total Payout (with a "% paid" sub-label), Posts (done/owed), Total Views, and Average CPM.

**Campaign History table:** Every campaign this creator has been part of, with columns: Campaign (link to campaign page), Posts (done/owed), Rate, Paid status (green = paid, red = unpaid), Status (active/inactive), and Notes.

**Live Posts table:** (Only appears if scraped video links exist for this creator.) Every video we've found from this creator across all campaigns, with columns: Campaign (link), Post (link to the actual video), Views, Likes, and Date uploaded.

---

## Slack Inbox

**URL:** `/inbox`

**Who uses it:** Jake, primarily. He reviews and approves or dismisses creator booking suggestions here.

**What you see:**

At the top: the page title "Slack Inbox" and a count of pending items on the right.

If there's nothing in the inbox, you see an empty state message explaining that booking suggestions from Open CLAW (the Slack assistant) will appear here.

If there are items, they appear in three sections: **Pending Approval**, **Recently Approved**, and **Dismissed**.

**Each inbox card shows:**
- The source message (what was parsed from Slack)
- The suggested campaign
- The creator(s) being suggested, with their proposed rate and posts
- **Approve** and **Dismiss** buttons

Clicking **Approve** adds the creator(s) to the suggested campaign and moves the card to the Approved section. Clicking **Dismiss** moves the card to the Dismissed section. Neither action reloads the page.

---

## Internal TikTok

**URL:** `/internal`

**Who uses it:** Jake and the team, to monitor Rising Tides' own TikTok pages and the label pages they manage. This is separate from the campaign creator tracking — it's for watching the team's own content.

**What you see:**

At the top: the page title "Internal TikTok" and a count of total accounts being tracked.

Below that: four cards labeled **Internal Pages**, **Warner Pages**, **Atlantic Pages**, and **Warner Test Pages**. Each shows how many accounts are in that group and a "Scrape & View Links →" link. Clicking a card takes you to a scrape view where you can choose a date range and trigger a fresh scan of those accounts' recent posts.

Below the scrape cards: three tabs — **Stats**, **All Accounts**, and **Groups**.

**Stats tab:** Shows performance cards for each group of internal pages. Each card shows the group name, how many accounts are in it, and the total views, posts, and likes for a chosen date range. A date picker at the top lets you change the range (defaults to the last 30 days). Clicking a card goes to the group's detail page.

**All Accounts tab:** A list of every account being tracked, with their total video count and total views. Includes an "Add Creators" form at the top (type usernames, comma-separated). An X button next to each account removes it.

**Groups tab:** Lets you create and manage named groups of accounts (e.g., "Jake's Pages," "Warner Pages"). Each group has a title, a slug (a short identifier), and a kind (booked_by, label, niche, or custom). You can delete groups here (accounts aren't deleted, just removed from the group).

---

## Internal Creator Detail Page

**URL:** `/internal/@username`

**Who uses it:** Jake and the team, to see what a specific internal creator has posted recently.

**What you see:**

The creator's username at the top, then a table of their cached video links — each row shows the video URL, view count, like count, comment count, and upload date. Links open the actual TikTok video. The page shows the 30-day rolling cache of that creator's content.

---

## Sidebar / Navigation / Mobile hamburger menu

See the **Navigation sidebar** section at the top of this page.

---

*Next: [The Outside Connections](05-outside-connections.md)*
