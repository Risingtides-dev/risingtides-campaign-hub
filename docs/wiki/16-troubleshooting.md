# 16. If Something Looks Weird

A quick reference for the most common "wait, why is this happening?" moments. When in doubt, ask Jake.

---

## A campaign isn't showing up after a Notion booking

**What happened:** Notion created a new "Client" entry, but Campaign Hub doesn't show the campaign yet.

**Try this:**
1. Wait a few minutes — the sync runs on a short delay.
2. Manually trigger a sync by asking someone to hit the sync button (or ask Jake to trigger it).
3. If it still doesn't appear after 15 minutes, create the campaign manually using the **New Campaign** button on the Promotions page. Fill in the artist, song, sound ID, and budget from the Notion entry.

---

## Cobrand stats look stale or blank

**What happened:** The Cobrand section on a campaign shows old numbers, zeros, or nothing at all.

**Try this:**
1. Check that the campaign has a Cobrand share link. If it's blank, no stats can be pulled.
2. Reload the campaign detail page — stats refresh when you open the page.
3. If the numbers still look old, the Cobrand connection may be temporarily down. This is Cobrand's issue, not Campaign Hub's. Check back in an hour.

---

## The Slack Inbox has duplicate items

**What happened:** The same booking appears twice in the Pending section.

**Why it happens:** Open CLAW sent the same booking twice, usually because the original Slack message was edited or the assistant ran twice.

**What to do:** Approve one and dismiss the other. If both get approved, you'll end up with duplicate creators on the campaign — which you can remove from the campaign detail page by clicking the trash icon next to a creator.

---

## A scrape says it finished but found 0 videos

**What happened:** The scraper ran and completed, but no new posts were matched.

**Most common reasons:**
1. **Wrong sound ID** — The Sound ID in the campaign doesn't match the one creators are actually using. Open a creator's video, tap the sound, and check the URL — it contains the real sound ID. Update the campaign if it's different.
2. **Creators haven't posted yet** — They're booked but haven't made their videos. Normal at the start of a campaign.
3. **TikTok blocked the scraper** — Try again in a few hours. See [The Scrapers](13-scrapers.md) for more detail.
4. **Creator accounts are private** — Private accounts can't be scraped. Ask the creator to make their account public.

---

## A creator's post count isn't going up even though they posted

**What happened:** You know a creator posted their video, but Posts Matched still shows 0 (or the old count).

**Try this:**
1. Go to the campaign detail page and click **Refresh Stats** in the campaign header. This triggers an immediate scrape for just that campaign.
2. Wait about 30 seconds, then reload the page.
3. If it still doesn't appear, check the campaign's Sound ID against the sound the creator actually used.

---

## A payment is showing as unpaid even though I paid it

**What happened:** The creator's row in the campaign table doesn't have the payment checkbox checked.

**What to do:** Click the payment checkbox in the creator's row. It toggles between paid and unpaid. Also make sure to set the payment date if you know it.

---

## The budget numbers don't add up

**What happened:** The budget card shows numbers that seem wrong.

**How it's calculated:**
- **Booked** = sum of all creator rates (paid or not)
- **Paid** = sum of creator rates where payment is checked
- **Remaining** = total budget minus Paid

If the numbers look off, check the individual creator rates in the table — an incorrect rate on one creator can throw off the whole budget summary.

---

## I can't find a campaign in the list

**What happened:** A campaign you're looking for isn't visible on the Promotions page.

**Try this:**
1. Check the **Finished** tab — if the campaign was marked complete, it moved there.
2. Use the search bar — type the artist or song name.
3. If neither works, the campaign may not have been created in Campaign Hub yet. Check Notion or ask Jake.

---

## When in doubt, ask Jake.

Jake built the original system and knows every corner of it. If something doesn't make sense and this guide doesn't cover it, he's the fastest path to an answer.

---

*Back to: [Index →](index.md)*
