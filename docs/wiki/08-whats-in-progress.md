# 8. What's Currently in Progress

This page translates the current known issues, active work, and upcoming changes into plain terms. If you're wondering "why does X seem off?" or "I heard they're working on something" — this is the page to check.

---

## Things we're still working on

**Importing past campaign data.** Campaign Hub is live and working, but the database is currently empty (or has limited data). Jake has 14 active campaigns worth of data on his local computer — creator rosters, budgets, matched video links, scrape results. That data needs to be imported into Campaign Hub before the app reflects reality. Until that's done, you may see an empty campaigns list or missing information even for campaigns that are very much active.

**Scraper accuracy.** The scraper that finds creator posts on TikTok has some known issues with matching sounds to the right videos. Specifically, it sometimes misses posts because it's looking for the wrong sound ID, or it finds posts that don't actually belong to the campaign. This is being investigated and improved.

**Platform-aware social links.** Right now, every creator profile shows a "View on TikTok" button regardless of whether that creator was actually booked for TikTok or Instagram. The fix — showing TikTok links for TikTok campaigns and Instagram links for Instagram campaigns — is planned but not done yet.

---

## Things we know are flaky

**Cobrand stats.** Campaign Hub pulls live numbers from Cobrand by visiting the share page. This works most of the time, but it's not an official connection — if Cobrand changes how their pages are built, the stats could stop updating without warning. If you see "Failed to load stats" or stale numbers, try refreshing the page. If the problem persists, check Cobrand directly.

**TikTok scraping.** As described in the Scrapers section, TikTok actively tries to block automated tools. Scrapes sometimes fail with zero results even when posts genuinely exist. This is an ongoing reality, not a bug with a clean fix.

**Notion sync.** The automatic syncing of new campaigns from Notion into Campaign Hub has been built and is working in principle, but hasn't been fully tested with real data yet. The manual trigger works; an automated schedule hasn't been set up.

---

## Coming soon

**Automated Notion sync.** Right now, pulling new bookings from Notion requires someone to manually trigger the sync. The plan is to make this happen automatically on a schedule (every few minutes), so new campaigns appear in Campaign Hub without anyone having to do anything.

**Creator tagging and ratings.** The Creator Database currently shows performance stats but doesn't let you tag creators by content style, reliability, or other qualities. A future update will add that, making it easier to find the right creator for a new campaign.

**Cleaning up old code.** The original version of Campaign Hub — which predates the current React app — still exists inside the codebase for safety reasons. Once the team has confirmed the new version is working correctly and all the data is migrated, the old code will be removed.

---

*Next: [Glossary](09-glossary.md)*
