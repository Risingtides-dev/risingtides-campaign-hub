# 5. The Outside Connections

Campaign Hub doesn't work alone. It connects to four outside systems. Here's what each one does, what it gives us, and what would break if it stopped working.

---

## Notion — where client bookings come from

**What it is:** Notion is a notes-and-database tool that Rising Tides uses as a Client Relationship Manager (CRM). This is where the team tracks conversations with labels, the status of deals, and confirmed campaign bookings.

**What it gives us:** When a label signs on and a campaign is confirmed, that booking lives in Notion as a record with the artist name, song, sound link, budget, label name, and contact info. Campaign Hub can pull that record in automatically, saving the team from manually re-entering all those details.

**How the connection works:** Campaign Hub periodically checks the Notion database for new entries where the status is "Client" (confirmed booking). When it finds one, it creates a matching campaign in Campaign Hub with all the details already filled in.

**What would break if Notion stopped working:** New campaigns would need to be created manually instead of automatically importing. Existing campaigns wouldn't be affected. The connection is one-directional — Notion pushes data in, nothing goes back from Campaign Hub to Notion.

---

## Slack — where new creator bookings get sent for Jake to approve

**What it is:** Slack is the team's main messaging app. An automated assistant called **Open CLAW** monitors specific Slack channels where booking messages are posted.

**What it gives us:** When someone types a booking message in Slack (like "book @creator for 3 posts at $200 on X campaign"), Open CLAW reads it, figures out the creator name, post count, rate, and campaign, and sends a formatted suggestion into Campaign Hub's Slack Inbox.

**How the connection works:** Open CLAW sends booking data to Campaign Hub through an automated call. Jake sees the suggestion in the Slack Inbox and clicks Approve or Dismiss. If approved, the creator is added to the campaign instantly.

**What would break if Slack stopped working:** No new booking suggestions would appear in the Slack Inbox. Jake could still add creators manually on the Campaign Detail page. Existing campaigns and creators wouldn't be affected.

---

## Cobrand — where live performance numbers come from

**What it is:** Cobrand is a third-party service that tracks social media campaign performance. Labels use it to see how their campaign is doing — how many videos were submitted, how many views they're getting, etc.

**What it gives us:** Campaign Hub pulls live numbers from Cobrand so the team can see performance stats without switching between tools. The numbers shown in Campaign Hub's Cobrand Stats section (submissions, comments, status) come directly from Cobrand.

**How the connection works:** For each campaign, the team enters a "Cobrand share URL" — a special link that Cobrand generates for that campaign. Campaign Hub fetches that page in the background and reads the performance numbers out of it. There is no official Cobrand API; Campaign Hub is essentially reading the Cobrand page like a human would.

**What would break if Cobrand stopped working:** The performance numbers (submissions, comments, status) on each campaign's detail page would stop updating or show stale data. The team would need to log into Cobrand directly to check stats. Everything else in Campaign Hub — budgets, creator payments, scraping — would be completely unaffected.

**Important:** Campaign Hub only reads performance data from Cobrand. It never writes financial data (budgets, rates, payments) to Cobrand. Money information stays in Campaign Hub.

---

## TikTok and Instagram — where the actual posts and sounds live

**What they are:** The social media platforms where creators post their videos. Rising Tides doesn't control these platforms — we're working within them.

**What they give us:** The post videos themselves, plus the "sounds" (audio tracks) that creators can attach to their videos. Each sound has a unique ID that identifies it across the platform.

**How the connection works:** Campaign Hub's scrapers use tools to search TikTok and Instagram for videos that use a specific sound ID. When the scraper finds a matching video, it records the post link, view count, and like count. The team then submits those links to Cobrand.

**What would break if TikTok/Instagram stopped working or blocked us:** Scraping would fail — no new post links would be collected automatically. The team would need to collect links manually (asking creators directly, or browsing TikTok for the sound). Live performance tracking via Cobrand would also be affected since Cobrand itself relies on these platforms. This is the most fragile connection — TikTok actively changes how their platform works to make scraping harder, so occasional scraper issues are expected.
