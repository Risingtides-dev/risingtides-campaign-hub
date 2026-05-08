# 7. The Scrapers

## What is "scraping"?

Imagine you want to find every TikTok video that uses a specific song. You could open TikTok, search for the song, and copy down each video link by hand. That would take hours — and you'd have to redo it every day.

**Scraping** is what happens when a program does that automatically. It visits TikTok (or Instagram) on your behalf, looks for the right videos, and records the links — in seconds, for hundreds of accounts at once.

Campaign Hub has scrapers built in. You don't need to think about the technical details; you click a button and wait for results.

---

## Why we scrape

Rising Tides needs to know three things on every campaign:

1. **Have creators actually posted?** We want to verify that booked creators delivered.
2. **What are those post links?** We need the actual TikTok/Instagram URLs to submit them to Cobrand.
3. **How are the posts performing?** Initial view and like counts.

The scrapers answer all three questions automatically.

---

## When scraping runs

There are two scrapers in Campaign Hub.

### Campaign scraping (finding creator posts)

Triggered manually from a Campaign Detail page using the **Refresh Stats** button (the arrow icon in the campaign header). When clicked, Campaign Hub searches TikTok for videos that use the campaign's sound ID and tries to match them to creators booked on the campaign.

Results land in the campaign's "Live Posts" / matched-videos list, which feeds the Cobrand upload workflow.

The campaign scrape can also run automatically as part of background jobs — see the **Scrape Tasks** screen in the sidebar to monitor in-progress jobs.

### Internal TikTok scraping (monitoring our own pages)

On the Internal TikTok screen, the **Scrape & View Links** action triggers a scrape of a pre-set list of accounts that Rising Tides controls directly. It pulls the latest videos and stats for those accounts, with a configurable date range.

Both scrapers run in the background. A progress indicator shows how far along they are. You can navigate away — the scrape keeps going.

---

## How the scraper finds the right videos

The scraper uses a **sound ID** — the unique number TikTok and Instagram assign to every audio track. When a creator uses a specific sound in their video, that sound ID gets attached to the video.

The scraper looks up all videos using a given sound ID and tries to figure out which were posted by creators we booked.

**The matching logic, step by step:**

1. **Username match.** If a video was posted by a username on our creator list, that's a match.
2. **Fuzzy match.** If the username isn't an exact match, the scraper strips punctuation and checks for common variations (e.g. underscores vs. dots).
3. **Strict mode.** For campaigns where the sound is unusual or where multiple campaigns use the same artist, a stricter mode matches *only* on the exact sound ID — no fuzzy guesses.
4. **Multiple sound IDs.** If a song has more than one sound (an original plus a remix, or different regional uploads), the campaign can store extra sound IDs. The scraper checks all of them.

---

## What can go wrong

### TikTok blocks or throttles the scraper

TikTok actively fights automated tools. Occasionally it slows or blocks scrape requests, causing fewer matches than expected or outright failures.

- **Signs:** "Live Posts" stops growing; the scrape log shows errors for multiple accounts.
- **What to do:** Wait an hour and try again — these blocks are usually temporary. If it persists for more than a day, flag it to Smaths.

### Wrong sound ID

If the campaign's sound ID is incorrect, the scraper looks for the wrong audio track and finds nothing (or finds the wrong videos).

- **Signs:** Creators you know have posted show "0" in Live Posts.
- **What to do:** Open a known creator's video on TikTok, tap into the sound, and check the URL — it contains the real sound ID. Update the campaign if they don't match.

### Creator changed their username

If a creator changed their TikTok username between booking and posting, the scraper may not match their videos.

- **What to do:** Update the username on their row in the Campaign Detail Creators Table.

### Multiple sound versions

Sometimes a song has different versions (original, remix, promo) each with their own sound ID. If the creator used a different version than expected, their post won't match.

- **What to do:** Add additional sound IDs to the campaign (via the Edit button) to cover all versions.

### Creator's account went private

The scraper can only see public posts. If a creator's account is private, their videos won't appear.

- **What to do:** Ask the creator to make their account public, or note that their posts need to be added manually.

### Short URLs

TikTok sometimes uses short URLs (`vm.tiktok.com/...`) that redirect to the actual video. The scraper resolves these automatically, but they occasionally time out.

---

## What to do when scraping seems broken

1. **Check the sound ID.** Verify it on the Campaign Detail page against the sound's URL on TikTok.
2. **Try again.** Most blocks clear within an hour or two.
3. **Check creator usernames.** Make sure no one's account changed handles.
4. **Check creator privacy.** Private accounts can't be scraped.
5. **Add links manually.** If scraping keeps failing, ask creators directly for their video URLs and add them by hand on the Campaign Detail page.
6. **Ask Smaths.** If you've tried the above and the scrape is still broken, it may need a code fix.

---

*Next: [What's Currently In Progress](./08-whats-in-progress.md)*
