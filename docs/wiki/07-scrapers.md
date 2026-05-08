# 7. The Scrapers

## What is "scraping"?

Scraping means automatically visiting a website — like TikTok — and collecting information from it, the way you'd look something up manually, but done by a computer program that can do it thousands of times faster.

Imagine you wanted to find every TikTok video that uses a specific song. You could spend hours clicking through TikTok manually. Or you could write a program that visits TikTok, searches for the song, and saves every result — in minutes. That program is a scraper.

Rising Tides uses scrapers for two purposes:
1. Finding creator posts for active campaigns (campaign scraping)
2. Monitoring Rising Tides' own internal TikTok pages and label pages (internal scraping)

---

## Why do we scrape?

**For campaigns:** Once creators post their videos, Rising Tides needs to know those posts exist. There's no way for TikTok to automatically notify us when a creator posts something — we have to go looking. The scraper finds those posts by searching for videos that use the campaign's specific sound (song).

**For internal pages:** Rising Tides manages a set of internal TikTok pages (belonging to team members and label accounts). The scraper checks what those pages have posted recently and collects the view and like counts, so the team has visibility into how that content is performing.

---

## When does it run?

**Campaign scraping** runs on demand. On each campaign's detail page, there's a "Refresh" button in the campaign header. Clicking it kicks off a scrape for that campaign — the system goes to TikTok, searches for the song, finds matching videos, and saves any new links it finds. It runs in the background (so the page doesn't freeze), and the results appear when it's done.

**Internal scraping** also runs on demand, from the Internal TikTok page. You pick a group of pages (Internal, Warner, Atlantic, or Warner Test), select a date range, and click to run the scrape. The page shows progress in real time and displays the results — videos organized by song — when it finishes.

There is no automatic, scheduled scraping. Someone on the team has to trigger it.

---

## How does it find the right posts?

This is the clever part. Every sound on TikTok has a unique ID — a number that identifies exactly which audio file is being used. When a creator posts a video using a specific song, that sound ID is baked into the video's page.

The scraper:
1. Looks up the sound ID for the campaign's song (sometimes extracting it from the TikTok URL for the song, sometimes from the song's TikTok page)
2. Searches TikTok for all recent videos that used that sound
3. Checks whether each result's account name matches one of the booked creators
4. If it matches, saves the video link to the campaign

For internal scraping, the process is different: instead of searching by sound, the scraper visits each internal creator's TikTok page directly and collects their recent posts.

---

## What can go wrong?

**TikTok blocks the scraper.** TikTok doesn't officially allow automated access to its data. It has systems that detect and block scrapers. When this happens, the scrape returns zero results even though posts genuinely exist. This is the most common problem. It usually resolves on its own after some time, or after trying again. There's no permanent fix — it's an ongoing challenge.

**Sound IDs don't match.** A song might appear on TikTok under multiple different sound IDs (for example, if it was uploaded multiple times, or if there's an official version and a fan-uploaded version). If the system is looking for the wrong ID, it won't find the right posts. Fixing this means updating the sound ID stored in the campaign.

**The creator's account name differs.** If a creator posted under a slightly different username than what's stored in Campaign Hub, the post won't be recognized as a match. This is rare but does happen — for example if a creator changed their username between being booked and posting.

**The song name is ambiguous.** The scraper uses song name and artist to match sounds, normalizing variations ("feat.", "Remix", "Promo" are stripped out). But if two songs have very similar names, or if a creator posted to an unrelated sound with a similar name, a wrong match could get saved.

---

## What should you do when scraping seems broken?

1. **Try again.** Click the Refresh button on the campaign detail page again. TikTok blocks are often temporary.

2. **Check the sound ID.** Go to the campaign's edit form and verify the TikTok sound ID. You can find the real sound ID by opening the song's TikTok page and looking at the URL. If the ID in Campaign Hub doesn't match, update it.

3. **Check if the posts actually exist.** Search for the song manually on TikTok and see if you can find the creator's post that way. If the post is there but not showing in Campaign Hub, it's a matching issue (wrong sound ID or username mismatch). If the post isn't there at all, the creator may not have posted yet.

4. **Ask Jake.** If you've tried the above and still can't get it working, Jake knows the most about how the scraper behaves.

---

*Next: [What's Currently in Progress](08-whats-in-progress.md)*
