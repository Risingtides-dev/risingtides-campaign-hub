# 3. How a Campaign Works (The Full Lifecycle)

This page walks through the life of a campaign from the moment a label books it to the moment it's archived. Each step happens in a different place — here's the full story.

---

## Step 1: The Label Books a Campaign

A record label reaches out to Rising Tides and says they want to promote a song. Once the deal is confirmed, the label's information gets entered into **Notion** — Rising Tides' client relationship tool. The entry includes the artist name, song, sound link, budget, and which label it's from.

Campaign Hub watches Notion. When a new "Client" entry appears there, it automatically creates a matching campaign in Campaign Hub. This is the Notion sync — the campaign appears in the system without anyone having to re-enter all the same information by hand.

> **If a campaign doesn't show up after a Notion booking**, see [the troubleshooting guide](16-troubleshooting.md).

---

## Step 2: The Campaign Appears in Campaign Hub

The new campaign now shows up on the Promotions page (the homepage) under the **Active** tab. At this point it has a title, artist name, song, and budget — but no creators yet.

The campaign's "slug" (a short unique name like `sombr_homewrecker_promo_r3`) is also created automatically. This slug appears in the web address when you click into the campaign.

---

## Step 3: Creators Get Added

Creators get added to a campaign in two ways:

**Via Slack (the most common way):** An AI assistant called Open CLAW reads Rising Tides' Slack booking channel. When someone posts something like "book @xyzbca_quote for 5 posts at $150 on Sombr," Open CLAW parses it and sends a structured booking recommendation to Campaign Hub. It shows up in the **Slack Inbox** page as a pending item. Jake reviews it and clicks Approve to add the creators, or Dismiss to ignore it.

**Manually:** On the campaign detail page, there's an "Add Creator" form where you can type a username, set a rate, choose a platform (TikTok or Instagram), and set how many posts they owe. You can add creators one at a time.

Once added, each creator appears in the campaign's creator table with their username, rate, posts owed, and payment status.

---

## Step 4: Creators Post Their Videos

Creators go and make their TikTok or Instagram posts using the campaign's song. They don't have to report back or upload links — Campaign Hub finds the posts automatically.

This is called **scraping**. Once a day (or whenever you manually trigger a refresh), Campaign Hub runs a search for posts that use the song's unique sound ID. It checks each creator's account for recent videos that match. When it finds one, it links that video to the campaign.

You can see matched videos in the campaign detail page. The count of matched posts updates in the creator table — "Posts Matched" goes up as more videos are found.

> **For a detailed explanation of scraping**, see [The Scrapers](13-scrapers.md).

---

## Step 5: Cobrand Tracks Performance

Once creators are posting, you connect a Cobrand tracking link to the campaign. Cobrand is a third-party platform (the one you use to upload the post links). It measures how many people saw each post, how many comments there were, and how engaged the audience was.

To connect it:
1. On the campaign detail page, paste the Cobrand share link into the Cobrand section.
2. Campaign Hub automatically pulls in the live statistics: how many submissions, how many comments, and the overall status.

These performance numbers (views, engagement) live in Cobrand. Campaign Hub just displays them — it doesn't store or calculate them.

---

## Step 6: Payments Get Tracked

When it's time to pay a creator, you mark them as paid in the creator table. You can set their PayPal email (Campaign Hub remembers it for next time), click the payment checkbox, and record the payment date. The budget cards at the top of the campaign page update automatically: "Paid" goes up, "Remaining" goes down.

---

## Step 7: The Campaign Finishes

When a campaign wraps up, you click the completion checkbox in the campaigns list. It cycles through three states:

- **Empty** — active, no status set
- **Half-filled** — booked (creators are locked in but campaign may still be running)
- **Green check** — completed

A campaign with a green check moves to the **Finished** tab on the Promotions page and disappears from the Active tab. It's still in the system — you can still look it up — but it's out of your active workflow.

---

*Next: [Campaigns List →](04-campaigns-list.md)*
