# 10. If Something Looks Weird

This page covers the most common "wait, that's not right" moments in Campaign Hub, with plain-English steps for figuring out what happened.

---

## A campaign isn't showing up after a Notion booking

**What you'd expect:** You marked a label as "Client" in Notion, and now the campaign should appear in Campaign Hub.

**Why it might not be there:**
- The sync hasn't run yet. The Notion-to-Campaign Hub sync needs to be triggered manually (as of this writing, it doesn't run automatically). Someone needs to go trigger the sync through the system, or ask Jake to do it.
- The entry in Notion might not be exactly in the right state. The sync only pulls entries with a specific pipeline status ("Client"). If the Notion entry is in a different status, it won't sync.

**What to do:**
1. Check Notion and confirm the campaign entry is marked as "Client" status.
2. Ask Jake to trigger the Notion sync.
3. If the campaign still doesn't appear after a minute or two, create it manually in Campaign Hub using the "New Campaign" button.

---

## Cobrand stats look stale or say "Failed to load"

**What you'd expect:** The Cobrand stats card on a campaign page shows up-to-date numbers.

**Why it might look wrong:**
- Campaign Hub reads Cobrand stats by visiting the share URL. If Cobrand's page is slow, down, or has been updated in a way the system doesn't understand, the numbers might not load.
- The share URL on the campaign might be incorrect or expired.

**What to do:**
1. Refresh the Campaign Hub page and wait a moment.
2. Check if the Cobrand share URL is still valid by opening it directly in your browser. If the page loads correctly there but not in Campaign Hub, ask Jake.
3. If the URL is wrong, click "Edit" on the campaign and update the Cobrand share URL.
4. If the URL looks right but stats still won't load, check Cobrand directly for the numbers.

---

## The Slack inbox has duplicate items

**What you'd expect:** Each creator booking suggestion appears once.

**Why duplicates happen:** Open CLAW (the Slack assistant) might send the same booking suggestion more than once if the Slack message was edited or if it encountered an error on the first try.

**What to do:**
1. Approve the correct one (the most recent or most complete version).
2. Dismiss all the duplicates.
3. Verify the creator was added to the campaign correctly on the campaign detail page.

---

## A scrape says it finished but found 0 videos

**What you'd expect:** After clicking Refresh on a campaign, some creator posts show up.

**Why it finds nothing:**
- TikTok blocked the scraper temporarily. This is the most common reason and usually fixes itself if you try again later.
- The sound ID stored for the campaign is wrong. If Campaign Hub is searching for the wrong sound, it won't find any posts that match.
- Creators genuinely haven't posted yet.

**What to do:**
1. Wait 10–15 minutes and try the Refresh button again.
2. If it keeps returning zero, check the TikTok sound ID in the campaign. Go to Edit on the campaign and look at the Sound ID field. Compare it to the actual TikTok URL for the song (the number in the URL is the sound ID).
3. Manually search TikTok for the song and see if the creator's videos appear. If they do, it's a sound ID or matching problem — update the sound ID and retry.
4. If the videos don't appear on TikTok at all, the creators may not have posted yet. Follow up with them directly.
5. If none of this resolves it, ask Jake.

---

## When in doubt, ask Jake

Campaign Hub is Jake's tool. He built the original version and has been using it daily. If something looks wrong and you've tried the steps above, Jake is the right person to ask.

For anything that seems like it might be a bug (the same thing going wrong for everyone, not just a one-time issue), you can also report it on the project's GitHub page so it gets tracked.

---

*Back to [Index](index.md)*
