# 5. The Outside Connections

Campaign Hub doesn't operate in isolation. Four outside systems plug into it. Here's what each one is, what it gives us, and what would happen if it stopped working.

---

## Notion

**What it is:** Notion is a combination note-taking and database tool. Rising Tides uses it as a CRM — a place to track client relationships. When a label reaches out and ultimately books a campaign, that booking gets recorded in a Notion database.

**What it gives us:** Notion is the source of truth for client bookings. Campaign Hub checks Notion for any entries where the label has moved to "Client" status, and automatically creates a corresponding campaign entry in Campaign Hub. This means the team doesn't have to enter the same information twice.

**What it sends over:** Artist name, song information, label name, who the project lead is, the platform the campaign is running on (TikTok, Instagram, or both), and sometimes the TikTok and Instagram sound links.

**What would break if it stopped:** New campaigns that come from Notion would need to be created manually in Campaign Hub instead of syncing automatically. The existing campaign data in Campaign Hub would be unaffected — Notion only writes to Campaign Hub when a new campaign is first created. Nothing would be lost; it would just mean more manual data entry.

**Note:** Client billing — what the label pays Rising Tides — lives in Notion, not in Campaign Hub. Campaign Hub only knows about the campaign budget (what Rising Tides is paying out to creators). Don't mix these up.

---

## Slack

**What it is:** Slack is the team's messaging tool. The Rising Tides team uses it to communicate day-to-day, including discussing which creators to book for which campaigns.

**What it gives us:** An automated assistant called Open CLAW listens to a specific Slack channel where booking discussions happen. When someone writes something like "Book @username for 5 posts at $150 on Campaign Name," Open CLAW parses that message and sends a structured booking suggestion to Campaign Hub's Slack Inbox. Jake then approves or dismisses each suggestion in the Campaign Hub interface.

**What would break if it stopped:** Slack is only used for the intake workflow — the Slack Inbox in Campaign Hub. If Slack or Open CLAW stopped working, new bookings would just need to be entered manually using the "Add Creator" form on each campaign's detail page. Nothing would be lost; it would just be more manual work.

---

## Cobrand

**What it is:** Cobrand is a third-party tool that Rising Tides uses to track how campaign videos are performing in real-time. The label can share a Cobrand tracking page with stakeholders to show campaign progress.

**What it gives us:** Live performance numbers — specifically, how many video submissions have come in, how many total comments, and overall engagement. Campaign Hub reads these numbers from Cobrand's page and displays them right in the campaign detail view, so you don't have to open Cobrand separately.

**How it works behind the scenes:** Campaign Hub's connection to Cobrand is unofficial — there's no formal partnership. The system visits the Cobrand share page (the same URL a label would open in their browser) and extracts the data it finds there. This is called "scraping the page." It works reliably but could theoretically break if Cobrand changes how their pages are built.

**What Rising Tides puts into Cobrand:** Video links for the campaign's matched posts. These are submitted via Cobrand's upload page (accessible through the Cobrand section at the bottom of each campaign detail page in Campaign Hub). Once submitted, Cobrand starts tracking those videos.

**What Campaign Hub never touches in Cobrand:** Budget, spend, or anything financial. Cobrand handles performance data only. Financial data lives in Campaign Hub.

**What would break if it stopped:** The live stats card on each campaign detail page would show an error or go blank. The campaigns themselves — creators, budgets, payment tracking — would be completely unaffected. The team would need to go to Cobrand directly to check performance numbers.

---

## TikTok and Instagram

**What they are:** The social media platforms where the actual campaign posts live. Creators post their videos there, using the designated song.

**What they give us:** The posts themselves. Campaign Hub's scraping system searches TikTok (and, in some campaigns, Instagram) for videos that use the correct song. When it finds a match, it saves that video link so the team knows the post exists.

**How it works:** The system looks for the song's unique TikTok sound ID — a number that identifies exactly which audio is being used in a video. It searches for all videos using that sound, then checks whether the poster's account matches one of the booked creators.

**What can go wrong:** TikTok sometimes blocks automated scanning tools, which can make scrapes fail or return zero results. Sound IDs can also be tricky — if a song is re-uploaded or has multiple versions, the IDs might not match what we expect. See the [Scrapers](07-scrapers.md) page for more on this.

**What would break if TikTok or Instagram access stopped:** The scraper would return no results, so the "Live Posts" count and matched video links would stop updating. Creators' posts would still go live on the platform — we just wouldn't be able to find them automatically and would have to collect links manually.

---

*Next: [The Money Trail](06-money-trail.md)*
