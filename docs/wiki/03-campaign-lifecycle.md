# 3. How a Campaign Moves Through the System

Here is the full story of a campaign, from the moment a label books it to the moment it's archived — written in plain English, in the order it actually happens.

---

## Step 1: A label books a campaign

A record label reaches out to Rising Tides and agrees to pay for a UGC campaign. They provide the details: the artist name, the song title, the TikTok/Instagram sound link, the budget, and the timeline.

This booking is recorded in **Notion**, Rising Tides' client relationship system. The booking sits there until it's ready to move into Campaign Hub.

---

## Step 2: The campaign appears in Campaign Hub

There are two ways a campaign enters Campaign Hub:

**Automatic (via Notion sync):** Campaign Hub can pull new bookings directly from Notion. When a label entry in Notion is marked as a confirmed client, Campaign Hub creates a matching campaign automatically — with the artist name, song, sound, and other details already filled in. The team just needs to verify the details are correct.

**Manual:** Someone on the team clicks "New Campaign" in Campaign Hub, fills in the artist name, song title, sound ID, budget, platform (TikTok, Instagram, or both), and start date, and saves it. The campaign appears immediately in the Promotions list.

Either way, the new campaign shows up on the **Active** tab of the Promotions list (the homepage).

---

## Step 3: Creators get added to the campaign

Once a campaign exists, the team needs to fill it with creators — the TikTok or Instagram users who will actually make the posts.

There are two ways this happens:

**Through the Slack Inbox:** An automated assistant called Open CLAW monitors the company Slack. When someone in Slack mentions a booking (e.g. "book @creator_username for 3 posts at $200 on this campaign"), Open CLAW parses that message and sends a suggestion into Campaign Hub's Slack Inbox. Jake opens the inbox, reviews the suggestion, and clicks "Approve" or "Dismiss." If approved, the creator is automatically added to the right campaign with the right rate and post count.

**By hand:** On any campaign's detail page, there's an "Add Creator" form. You fill in the creator's username, how many posts they owe, their rate, and their PayPal email. Click save, and they're on the campaign.

---

## Step 4: Creators post their videos

Creators post on TikTok or Instagram on their own — Campaign Hub doesn't control that. But once posts exist, the team needs to know about them so they can be submitted to Cobrand for tracking.

This is where the **scrapers** come in. Campaign Hub can automatically search TikTok for videos that use the campaign's specific sound. It does this by looking up the sound's unique ID and finding all videos posted to that sound. This process is called "scraping."

The scraper collects links to all matching videos. Those links then get copied out of Campaign Hub and pasted into Cobrand's upload tool — which starts tracking them.

The team can also manually find post links (e.g. by asking the creator directly) and add them to the campaign.

---

## Step 5: Performance tracking starts

Once the post links are in Cobrand, Cobrand starts measuring how each video is performing — how many views, how many comments, how many total submissions across the campaign.

Campaign Hub displays these live numbers on the campaign's detail page. It fetches the latest data from Cobrand automatically, so the numbers stay up to date without anyone having to log into Cobrand separately.

---

## Step 6: The campaign wraps up

When all posts have been delivered and payments have been made, the campaign is done. The team marks it in two stages using the small checkbox in the Promotions table:

1. **First click** → Gray checkmark: "Booking complete" — all creators are booked
2. **Second click** → Green checkmark: "Campaign wrapped" — fully done
3. **Third click** → Resets back to empty (in case it was clicked by mistake)

Once a campaign has the green checkmark (status: "completed"), it moves from the **Active** tab to the **Finished** tab on the Promotions list. It doesn't disappear — it just gets out of the way so the Active tab stays clean.

---

## The full flow, in one diagram

```
Label books → Notion CRM
                 |
                 | (automatic sync, or manual entry)
                 ▼
         Campaign Hub — new campaign created
                 |
                 | (Slack inbox or hand-entry)
                 ▼
         Creators added to campaign
                 |
                 | (scrapers find TikTok/Instagram posts)
                 ▼
         Post links collected
                 |
                 | (copied into Cobrand)
                 ▼
         Cobrand tracks live performance
                 |
                 | (stats shown in Campaign Hub)
                 ▼
         Campaign wrapped → moved to Finished tab
```
