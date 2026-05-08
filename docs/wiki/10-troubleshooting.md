# 10. If Something Looks Weird

Quick fixes for the most common problems. Read this before asking Jake.

---

## Campaign not showing up after a Notion booking

**What happened:** A label was booked in Notion, but the campaign isn't appearing in Campaign Hub.

**Try these steps:**
1. Check that the booking in Notion has its Pipeline Status set to "Client" (that's the trigger Campaign Hub looks for).
2. Manually trigger the Notion sync — this isn't automatic yet, and someone may need to kick it off. Ask Jake or whoever manages the integrations.
3. If the sync runs and still nothing shows up, the campaign may need to be created manually. Go to the Promotions page, click "New Campaign," and fill in the details from the Notion record.

---

## Cobrand stats look stale

**What happened:** The views, submissions, or comments on a Campaign Detail page haven't updated in a while, or they look wrong.

**Try these steps:**
1. Click the **Refresh Stats** button (↺ arrow icon) on the Campaign Detail page. This pulls fresh numbers from Cobrand.
2. Wait 30–60 seconds and reload the page.
3. If numbers still look wrong, open the Cobrand share URL directly in your browser and compare. If Cobrand itself shows different numbers than Campaign Hub, it means the refresh didn't work — try again.
4. If Cobrand looks right but Campaign Hub keeps showing stale numbers, flag it for Jake.

---

## Slack inbox has duplicates

**What happened:** The same creator booking is showing up multiple times in the Slack Inbox.

**Why this happens:** Open CLAW may have parsed the same Slack message more than once (e.g. if someone forwarded or re-posted it, or if there was a processing hiccup).

**What to do:**
1. Dismiss all duplicates — click **Dismiss** on all but one copy.
2. Approve the remaining one.
3. If the creator ends up on the campaign twice (check the Campaign Detail page), remove one entry using the trash icon on the Creators Table.

---

## A scrape says it finished but found 0 videos

**What happened:** You ran Refresh Stats on a campaign, the scrape completed, but 0 matched videos appeared.

**Try these steps:**
1. **Check the sound ID.** Open the Campaign Detail page and look at the Sound ID field. Then find the actual sound on TikTok and verify the ID in the URL matches. If it doesn't, update it.
2. **Check if any posts exist.** Open TikTok and manually search for videos using this sound. If there are none, the creators may not have posted yet — the scrape result is actually correct.
3. **Check creator usernames.** If videos exist on TikTok but aren't being matched, one or more creators may have changed their username. Update the username on their row in the Creators Table.
4. **Try again in a few minutes.** TikTok sometimes temporarily blocks scraping requests. A short wait usually resolves it.
5. **Add links manually.** If the scraper keeps failing, ask the creators to send you their video links directly and add them to the campaign by hand.

---

## A creator is showing as unpaid but they were definitely paid

**What happened:** The "Paid" checkbox on a creator's row is unchecked, but you know the payment was sent.

**What to do:**
1. On the Campaign Detail page, find the creator in the Creators Table.
2. Click the checkbox in the "Paid" column to mark them as paid.
3. That's it — the change saves instantly, no page reload needed.

If you're seeing the wrong PayPal email on file, click the pencil (edit) icon on the creator's row and update it.

---

## A campaign is showing in the wrong tab

**What happened:** A finished campaign is showing in Active, or an active campaign is in Finished.

**What to do:**
1. Find the campaign in the Campaigns List.
2. Look at the checkbox in the far left column:
   - If it has a green ✓ and should be Active: click it once more to reset it to empty.
   - If it's empty/gray and should be in Finished: click it twice to reach the green ✓ state.

---

## Something looks really broken and none of the above helps

1. Try reloading the page (Cmd+R or Ctrl+R).
2. If it still looks wrong, describe what you see and **ask Jake**.

Jake can also be reached to escalate anything that looks like a data problem (wrong budget, missing campaign, incorrect payment history) — these need human eyes, not just a page reload.
