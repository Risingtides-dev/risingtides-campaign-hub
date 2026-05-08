# 10. If Something Looks Weird

Quick fixes for the most common problems. Read this before pinging Smaths or Jake.

---

## A campaign isn't showing up after a Notion booking

**What happened:** A label was booked in Notion, but the campaign isn't appearing in Campaign Hub.

**Try these steps:**

1. Check that the booking in Notion has its **Pipeline Status** set to "Client" — that's the trigger Campaign Hub looks for.
2. Manually trigger the Notion sync. The poll isn't fully automatic yet — someone may need to kick it off. Ask Jake or Smaths.
3. If the sync runs and still nothing shows up, create the campaign manually. On the Promotions page, click **+ New Campaign** and fill in the details from the Notion record.

---

## Cobrand stats look stale

**What happened:** The views, submissions, or comments on a Campaign Detail page haven't updated in a while, or they look wrong.

**Try these steps:**

1. Click the **Refresh** button (arrow icon) in the campaign header. This pulls fresh numbers from Cobrand.
2. Wait 30–60 seconds and reload the page.
3. Open the Cobrand share URL directly in your browser and compare. If Cobrand itself shows different numbers than Campaign Hub, the refresh didn't take — try again.
4. If Cobrand looks right but Campaign Hub keeps showing stale numbers, flag it to Smaths.

---

## The Slack Inbox has duplicates

**What happened:** The same creator booking is showing up multiple times in the Pending section.

**Why it happens:** Open CLAW may have parsed the same Slack message more than once (e.g. the original was edited, or there was a processing hiccup).

**What to do:**

1. Dismiss all duplicates — click **Dismiss** on every copy except one.
2. Approve the remaining one.
3. If duplicates already made it onto the campaign (check the Campaign Detail page), remove the extras using the trash icon on the Creators Table.

---

## A scrape says it finished but found 0 videos

**What happened:** You ran Refresh on a campaign, the scrape completed, but 0 matched videos appeared.

**Most common causes:**

1. **Wrong sound ID.** Open the Campaign Detail page → check the sound ID against the actual sound's URL on TikTok. Update it if they don't match.
2. **Creators haven't posted yet.** Normal at the start of a campaign — the scraper is correct that nothing exists.
3. **TikTok blocked the scraper.** Try again in an hour. See [The Scrapers](./07-scrapers.md).
4. **Creator usernames changed.** If videos exist on TikTok but aren't being matched, one or more creators may have changed handles. Update their username on the Campaign Detail Creators Table.
5. **Creator accounts went private.** The scraper can only see public posts. Ask the creator to make their account public.

---

## A creator's post count isn't going up even though they posted

**What happened:** You know a creator posted, but their **Posts Done** count still shows the old number.

**Try these steps:**

1. Go to the Campaign Detail page and click **Refresh** in the header. This triggers an immediate scrape for that one campaign.
2. Wait 30 seconds and reload.
3. If it still doesn't appear, check the campaign's Sound ID against the sound the creator actually used in their video.
4. If the creator's username has changed, update it on their row.

---

## A creator is showing as unpaid but they were definitely paid

**What happened:** The Paid checkbox on a creator's row is empty, but you know the payment went out.

**What to do:**

1. On the Campaign Detail page, find the creator in the Creators Table.
2. Click the checkbox in the Paid column. It turns green immediately. Saves instantly, no reload.

If the wrong PayPal email is on file, click the pencil (edit) icon on the row and update it.

---

## A campaign is showing in the wrong tab

**What happened:** A finished campaign is showing in Active, or an active campaign is in Finished.

**What to do:**

1. Find the campaign in the Promotions list.
2. Look at the checkbox in the far-left column:
   - If it has a green ✓ but should be Active: click it once more to reset to empty.
   - If it's empty/gray but should be Finished: click it twice to reach the green ✓ state.

---

## The budget numbers don't add up

**What happened:** The budget cards on a Campaign Detail page show numbers that look wrong.

**How they're calculated:**

- **Booked** = sum of every creator's rate (paid or not)
- **Paid** = sum of rates where the Paid checkbox is checked
- **Remaining** = Budget − Paid

If something looks off, scan the individual creator rates in the Creators Table — one bad rate on one creator can throw off the whole rollup. Edit and save corrects it instantly.

---

## I can't find a campaign in the list

**What happened:** A campaign you're looking for isn't visible on the Promotions page.

**Try these steps:**

1. Check the **Finished** tab — if it was marked complete, it moved there.
2. Use the search bar — type the artist or song name. Search works within whichever tab is active.
3. If neither works, the campaign may not have been created in Campaign Hub yet. Check Notion or ask Jake.

---

## Something looks really broken and none of the above helps

1. Try reloading the page (Cmd+R or Ctrl+R).
2. If it still looks wrong, describe what you see and ping Smaths (anything technical) or Jake (anything campaign-related).

Things that need human eyes — wrong budget, missing campaign, incorrect payment history — won't get fixed by a refresh. Flag them rather than guessing.

---

*Back to: [Index](./index.md)*
