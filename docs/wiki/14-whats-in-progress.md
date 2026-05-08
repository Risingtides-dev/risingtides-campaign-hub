# 14. What's In Progress

Campaign Hub is actively maintained and being improved. This page explains what's known to be incomplete, what's coming soon, and what's been recently added.

---

## We're Still Working On...

### Data Migration
The system has the right structure, but about 14 active campaigns currently live only on Jake's local machine in a different format. Migrating those campaigns — their creators, matched videos, and history — into Campaign Hub is a priority. Until that's done, the database is mostly empty and some features are hard to fully test with real data.

### Platform-Aware Social Links
When you look at a creator profile, the system should know whether to show a TikTok link, an Instagram link, or both — based on which platforms that creator has been booked for. Right now it always shows TikTok. This small fix is on the list.

### Notion Sync Verification
The connection between Notion and Campaign Hub has been built but hasn't been tested with real live data yet. There's a chance the field mapping (which Notion fields turn into which Campaign Hub fields) needs adjustments once it runs with real campaigns.

### Scraper Refinement
The original sound matching logic — the part that decides whether a video uses the right song — has some known edge cases. In particular, songs with unusual names, featuring artists, or promotional edits sometimes don't match correctly. This is being investigated.

---

## Coming Soon...

### Automated Notion Sync
Right now, syncing new campaigns from Notion requires someone to manually trigger it (or for Notion to send a signal when something changes). A future update will set up a regular automatic sync — e.g., every 5 minutes — so new campaigns appear without any manual step.

### Enhanced Creator Database
Future plans include creator tags (e.g., "dance," "lifestyle," "comedy"), ratings, and performance scores to make it easier to pick the right creators for new campaigns without going through the full history each time.

---

## Recently Added

### Active / Finished Campaign Tabs
The Promotions page now splits campaigns into Active and Finished tabs. Clicking the completion checkbox on a campaign cycles through: no status → booked → completed (green check). Completed campaigns move to the Finished tab.

### Cobrand Live Stats
The campaign detail page now shows live stats from Cobrand — submission count, comment count, and overall status — once a Cobrand tracking link is connected.

### Creator Database
The Creator Database (cross-campaign roster) is new. Before, creators only existed within a single campaign. Now you can see a creator's full history across all campaigns in one place.

### Notion CRM Integration
Campaign Hub can now receive new campaigns from Notion automatically, instead of requiring manual creation for every new client booking.

---

*Next: [Glossary →](15-glossary.md)*
