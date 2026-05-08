# 8. What's Currently In Progress

This page translates the technical backlog into plain English. Here's where things stand as of May 2026.

---

## We're still working on…

**Importing old campaigns from Jake's computer.**
Jake has 14 active campaigns stored locally from before Campaign Hub was rebuilt. They haven't been imported into the new database yet. Until this happens, Campaign Hub's database is running on new data only. This is the top priority.

**Platform-aware social links for creators.**
On Creator Profile pages, there's a "View on TikTok" link for every creator. This should be smarter — if a creator was booked for Instagram campaigns, it should show an Instagram link; if both, show both. This is a small improvement that hasn't been done yet.

**Testing the Notion sync with real data.**
The connection between Campaign Hub and Notion is built and theoretically working, but it hasn't been fully tested with real bookings flowing through. The team should test it by creating a booking in Notion and seeing if it appears in Campaign Hub automatically.

---

## This is known to be flaky…

**The scraper (finding creator posts on TikTok/Instagram).**
TikTok actively tries to block automated tools, so the scraper occasionally returns fewer results than expected, or fails entirely for short periods. The original sound matching logic also has some known issues where it picks up the wrong videos or misses some. This is being investigated. In the meantime, if a scrape looks wrong, collect links manually and add them to the campaign.

---

## Coming soon…

**Automated Notion polling.**
Right now, pulling new bookings from Notion requires someone to manually trigger the sync. A future improvement will make this automatic — running in the background every few minutes.

**Cleaning up old code.**
There's a large chunk of old code left over from before the app was rebuilt. It's not causing any problems, but it makes the codebase bigger than it needs to be. Once the data migration from Jake's computer is confirmed working, that old code will be removed.

**Better creator database features.**
The Creator Database is functional but could be more powerful — creator tags, performance ratings, and notes would make it easier to quickly identify strong performers for future campaigns.

**Authentication (login).**
Campaign Hub currently has no login — anyone with the link can use it. This is fine for now while the team is small, but at some point a simple login will be added.

---

## Timeline note

The app itself is live and fully functional at `https://risingtides-campaign-hub.vercel.app`. The items above are improvements and edge cases, not blockers. The core features — campaigns, creators, budgets, payments, scraping, Cobrand stats, Slack inbox — all work.
