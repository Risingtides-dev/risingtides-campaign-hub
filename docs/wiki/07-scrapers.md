# 7. The Scrapers

## What is "scraping"?

Imagine you want to find every TikTok video that uses a specific song. You could sit at a computer and manually open TikTok, search for the song, and copy down every video link one by one. That would take hours.

**Scraping** is what happens when a program does that automatically. It visits TikTok (or Instagram) on your behalf, looks for the right videos, and records the links — in seconds, for hundreds of accounts at once.

Campaign Hub has scrapers built in. You don't have to think about the technical details; you just click a button and wait for the results.

---

## Why do we scrape?

Rising Tides needs to know:
1. **Have creators actually posted?** We want to verify that the creators we booked delivered their posts.
2. **What are those post links?** We need the actual TikTok/Instagram links so we can submit them to Cobrand for tracking.
3. **How are the posts performing?** We want the view and like counts.

The scrapers answer all three questions automatically.

---

## When does scraping run?

There are two types of scraping in Campaign Hub:

### Campaign scraping (finding creator posts)

This is triggered manually from a Campaign Detail page using the **Refresh Stats** button. When you click it, Campaign Hub searches TikTok for videos that use the campaign's sound ID. It compares the results against the list of creators booked on the campaign to find which ones have posted.

Results appear in the campaign's "matched videos" list, which feeds into the Cobrand upload workflow.

### Internal TikTok scraping (monitoring our own accounts)

On the Internal TikTok page (`/internal`), there's a **Run Internal Scrape** button. This scrapes a pre-set list of TikTok accounts that Rising Tides controls directly, pulling their latest videos and stats.

Both types run in the background — you don't have to stay on the page while they run. A progress indicator shows how far along the scrape is.

---

## How the scraper finds the right videos

The scraper uses a "sound ID" — a unique number that TikTok and Instagram assign to every audio track. When a creator uses a specific sound in their video, that sound ID is attached to the video.

The scraper looks up all videos that use that sound ID and tries to figure out which ones were posted by the creators we booked.

**The matching logic:**
1. If the video was posted by a username that matches someone on our creators list — that's a match.
2. If the username isn't exact, the scraper tries fuzzy matching: stripping out punctuation, checking for common variations.
3. For campaigns where the sound name is unusual (or there are multiple campaigns using the same artist), the scraper can use a stricter mode where it only matches on the exact sound ID.

---

## What can go wrong

**TikTok changes its rules:**
TikTok actively fights automated tools. Occasionally it blocks or throttles the scraper — causing scrapes to return fewer results than expected, or to fail entirely. This is the most common cause of scraping problems. There's no permanent fix; the scraper is regularly updated to adapt.

**Wrong sound ID:**
If the sound ID for a campaign is entered incorrectly, the scraper looks for the wrong audio track and finds nothing (or finds the wrong videos). Double-check the sound ID on the Campaign Detail page if scraping returns no results.

**Creator username mismatch:**
If a creator changed their TikTok username between when they were booked and when they posted, the scraper may not match their videos to the campaign. You'd need to manually update their username in Campaign Hub.

**The sound has multiple versions:**
Sometimes a song has different versions (original, remix, promo version) each with their own sound ID. If the creator used a different version than expected, their post won't match. You can add additional sound IDs to a campaign to cover multiple versions.

**Short URLs:**
TikTok sometimes uses shortened links (like `vm.tiktok.com/...`) that redirect to the actual video. The scraper resolves these automatically, but occasionally they time out.

---

## What to do when scraping seems broken

1. **Check the sound ID** on the Campaign Detail page. Make sure it's the right one (find it by opening the TikTok sound page and checking the URL).
2. **Try running the scrape again.** Transient blocks often clear up after a few minutes.
3. **Collect links manually.** If scraping keeps failing, ask creators directly for their video links and add them to the campaign by hand.
4. **Check if TikTok is down.** Occasionally TikTok itself has outages that affect scraping.
5. **Ask Jake.** If you've tried the above and it's still broken, flag it — it may require a code fix.
