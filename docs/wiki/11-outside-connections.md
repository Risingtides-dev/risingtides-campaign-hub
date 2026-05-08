# 11. The Outside Connections

Campaign Hub does not exist in isolation. It connects to four outside systems. Here's what each one does, what it gives you, and what breaks if it stops working.

---

## Notion

**What it is:** Notion is a document and database tool that Rising Tides uses as a client relationship management system (CRM). When a label books a campaign, the details get entered in Notion.

**What it gives us:** Notion is the source of truth for client relationships. When a new "Client" entry is created in Notion — meaning a label has officially booked a campaign — Campaign Hub picks it up automatically and creates a matching campaign here.

The fields it maps over include: artist name, song, sound link, label, round number, campaign stage, project lead, and client email.

**What breaks if it stops:** New campaigns won't appear in Campaign Hub automatically. You'd have to create them manually using the "New Campaign" button and fill in all the fields by hand.

**The sync happens via:** Campaign Hub polls the Notion database periodically for new "Client" entries, and also has a webhook that Notion can ping when something changes. In practice, if you don't see a new campaign after a Notion booking, you can manually trigger the sync or create the campaign by hand.

---

## Slack

**What it gives us:** When someone posts a booking recommendation in the Rising Tides Slack channel (e.g., "Book @handle for 5 posts at $150 on SongName"), an AI assistant called Open CLAW reads it, interprets it, and sends a structured booking to Campaign Hub's Slack Inbox.

**What breaks if it stops:** New bookings won't appear in the Slack Inbox. You'd have to add creators to campaigns manually from the campaign detail page.

**Note:** Campaign Hub doesn't read Slack directly — Open CLAW does. Campaign Hub just receives what Open CLAW sends it.

---

## Cobrand

**What it is:** Cobrand is the platform Rising Tides uses to formally track and measure campaign post performance. When creators post their videos, those post links get uploaded to Cobrand, which then tracks views, engagement, and other metrics.

**What it gives us:** Live performance numbers — how many posts have been submitted to the tracking page, how many comments they received, and the overall campaign status. These numbers show up in the Cobrand section of the campaign detail page.

Campaign Hub pulls these numbers by reading the Cobrand share page that you paste into a campaign. It does this automatically in the background once a tracking link is connected.

**What breaks if it stops:** The performance stats on the campaign detail page will go stale or disappear. The rest of Campaign Hub still works — creators, payments, scraping all continue normally. Only the Cobrand stats section goes blank.

**Important:** Cobrand owns performance data. Campaign Hub never modifies Cobrand — it only reads from it.

---

## TikTok and Instagram

**What they give us:** The actual posts that creators make live on TikTok and Instagram. Campaign Hub's scraper reaches out to TikTok to find videos that use a campaign's sound and to check specific creator accounts.

**What breaks if they stop:** The scraper can't find creator posts. The "Posts Matched" count won't update. You'd have to manually paste post links into Cobrand instead of relying on automatic discovery.

TikTok in particular has blocking mechanisms that occasionally slow or stop scraping. See [The Scrapers](13-scrapers.md) for what to do when this happens.

**Note:** Campaign Hub reads from TikTok and Instagram (looking at public posts) — it never posts, comments, or takes any action on those platforms.

---

*Next: [The Money Trail →](12-money-trail.md)*
