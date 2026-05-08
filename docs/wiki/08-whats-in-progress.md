# 8. What's Currently In Progress

This page translates the technical backlog into plain English. State as of May 2026 — Smaths will update it as items get done.

---

## We're still working on…

**Importing old campaigns from Jake's computer.**
Jake has 14 active campaigns stored locally from before Campaign Hub was rebuilt. They haven't been imported into the new database yet. Until this happens, Campaign Hub is running on new data only. This is the top priority on the list.

**Platform-aware social links on creator profiles.**
The Creator Profile page currently shows a "View on TikTok" link for everyone. It should be smarter — TikTok link for TikTok creators, Instagram for Instagram, both if both. Small fix, just hasn't been done yet.

**Testing the Notion sync with real data.**
The connection between Campaign Hub and Notion is built and works in theory, but it hasn't been fully tested with real bookings flowing through. The team should test it by creating a confirmed booking in Notion and confirming the campaign shows up in Campaign Hub automatically.

---

## This is known to be flaky…

**The scraper (finding creator posts on TikTok/Instagram).**
TikTok actively tries to block automated tools, so the scraper occasionally returns fewer results than expected, or fails entirely for short periods. The original-sound matching logic also has known issues where it sometimes picks up the wrong videos or misses posts. This is being investigated. In the meantime, if a scrape looks wrong, collect links manually and add them to the campaign by hand.

---

## Coming soon…

**Automated Notion polling.**
Right now, pulling new bookings from Notion requires someone to manually trigger the sync. A future improvement will run it in the background every few minutes.

**Cleaning up old code.**
There's a chunk of old code left over from before the app was rebuilt. It's not causing problems but it makes the codebase bigger than it needs to be. Once the data migration from Jake's computer is confirmed working, that old code will be removed.

**Better Creator Database features.**
The Creator Database is functional but could be more powerful — creator tags, performance ratings, and notes would make it easier to identify strong performers for future campaigns.

**Authentication (login).**
Campaign Hub currently has no login — anyone with the link can use it. Fine for now while the team is small, but a simple login will be added at some point.

---

## Timeline note

The app itself is live and fully functional at <https://risingtides-campaign-hub.vercel.app>. The items above are improvements and edge cases, not blockers. The core features — campaigns, creators, budgets, payments, scraping, Cobrand stats, Slack Inbox — all work today.

---

*Next: [Glossary](./09-glossary.md)*
