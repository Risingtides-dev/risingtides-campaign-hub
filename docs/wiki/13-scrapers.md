# 13. The Scrapers

## What Is "Scraping"?

Imagine you needed to check 50 TikTok accounts every day to see if any of them posted a video using a specific song. You could open each account in your browser, scroll through their recent videos, and check manually. That would take hours.

Scraping is the automated version of that. A program does the checking for you. It visits each account, looks at recent posts, and comes back with a report.

Campaign Hub has a scraper that does exactly this — it looks at every creator account on a campaign, scans their recent videos for ones that use the campaign's song, and records any matches.

---

## Why Do We Scrape?

Creators don't report back to us when they post. They just post. We have no way to know when a video goes up unless we check.

The scraper checks automatically so you don't have to. When it finds a match, the "Posts Matched" count on the campaign goes up, and the video link gets stored so it can be uploaded to Cobrand.

---

## How Does It Know Which Videos Match?

Each TikTok sound has a unique ID — a number that identifies that specific version of the song. When a creator makes a video using the campaign's sound, that video is tagged with the sound ID.

The scraper looks for posts tagged with the campaign's sound ID. This is why the "Sound ID" field is so important when creating a campaign — without it, the scraper has no way to know which videos to match.

For songs with multiple versions (remixes, regional variations), you can add additional sound IDs to the campaign. The scraper checks all of them.

---

## When Does It Run?

**Automatically:** Once a day, Campaign Hub automatically re-scans all active campaign creators. You don't have to do anything.

**Manually:** If you want fresh data right now — for example, a creator just told you they posted — click the **Refresh Stats** button on the campaign detail page. This triggers an immediate scrape for that campaign only.

The scraper runs in the background. A progress indicator shows while it's working. You can navigate away and come back — it keeps running.

---

## What Can Go Wrong?

### TikTok blocks the scraper
TikTok has systems that detect automated access and slow it down or block it temporarily. When this happens, fewer creators get scraped successfully, or the scrape takes much longer than usual.

Signs: "Posts Matched" counts stop updating. The scraper log shows errors for multiple accounts.

What to do: Wait a few hours and try again. This is usually temporary. If it persists for more than a day, flag it to Jake.

### Sound IDs don't match
Sometimes a campaign uses a sound that has multiple IDs (different uploads, different regions). If the sound ID in Campaign Hub isn't the one creators are actually using, the scraper finds no matches.

Signs: Creators you know have posted show "0" in Posts Matched.

What to do: Check the campaign's Sound ID field. Open a known creator's video on TikTok and look at the sound it uses — the URL of the sound page contains its ID. Update the campaign if the IDs don't match.

### A creator's account went private
The scraper can only see public posts. If a creator made their account private, their videos won't appear.

What to do: Reach out to the creator and ask them to make their account public, or note in their row that their posts need to be added manually.

### The scrape says it finished but found 0 videos
This can mean: the sound ID is wrong, all creators posted with a different sound, or TikTok blocked the scraper mid-run.

What to do: Check the sound ID first, then try a manual scrape again after a few hours.

---

## The Internal Scraper

There's a second scraper used by the Internal TikTok tool (described in [that section](09-internal-tiktok.md)). It works differently — instead of searching for a song, it looks at specific accounts and reports everything they've posted recently. It's used to monitor Rising Tides' own accounts and label partner pages.

---

*Next: [What's In Progress →](14-whats-in-progress.md)*
