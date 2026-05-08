# 3. How a Campaign Moves Through the System

This is the full story of a campaign — from the first booking all the way to the campaign being marked as finished.

---

## Step 1: A label books a campaign

A label (say, Warner) reaches out to Rising Tides and says: "We have a song by Artist X coming out. We want 30 TikTok creators to post about it. Here's our budget."

Rising Tides and the label agree on the terms. The label becomes a client. That relationship — who the client is, what they're paying for, which artist is involved — gets recorded in **Notion**, Rising Tides' CRM system (CRM just means "contact and relationship manager," like a fancy address book for business relationships).

## Step 2: The campaign appears in Campaign Hub

Once the label is marked as a "Client" in Notion, Campaign Hub can pull that information in automatically.

A team member triggers a sync (or the system does it on a schedule), and a new campaign entry appears in Campaign Hub. It shows up on the **Promotions** page — the main page you land on when you open the app.

If the campaign comes in from Notion, Campaign Hub fills in what it can: the artist name, the song title, sometimes the label and project manager. The team then fills in any missing details — the budget total, the start date, the unique sound ID for the song on TikTok.

Campaigns can also be created manually by clicking "New Campaign" at the top of the Promotions page.

## Step 3: Creators get added

Now the team needs to figure out who's going to post for this campaign.

**Via Slack:** There's an automated assistant called Open CLAW that monitors a Slack channel where the team discusses bookings. When someone posts a message like "Book @username for 5 posts at $150 on [campaign name]," Open CLAW parses that and sends it to Campaign Hub's **Slack Inbox** page. Jake reviews it and either approves (which adds the creator to the campaign automatically) or dismisses it.

**By hand:** Any team member can also go directly to a campaign's detail page and use the "Add Creator" form at the bottom of the page. You type in the creator's username, how many posts they owe, their rate, their PayPal email, and any notes.

Either way, the creator now shows up in the campaign's creator table with their rate, their post count, and a "Paid" status that starts as "No."

## Step 4: Creators post their videos

The creators go off and make their TikTok (or Instagram) videos, using the specified song. This happens off-platform — rising Tides communicates with creators directly (usually via DM or email).

Campaign Hub doesn't know about these posts yet. It needs to go find them.

That's where **scraping** comes in. Rising Tides' system searches TikTok (and sometimes Instagram) for videos that use the exact sound that belongs to this campaign. It matches videos by the song's unique ID on TikTok, then checks whether the account that posted the video is one of the booked creators.

When a match is found, the video link gets saved to the campaign. That's how Campaign Hub knows "Creator X posted their video."

You can manually trigger a scrape from the campaign detail page by clicking the refresh button in the campaign header. The system runs in the background and updates automatically — you don't have to wait while it works.

## Step 5: Performance tracking starts

Once a campaign has real videos posted, the team submits those video links to **Cobrand**, an external tracking tool.

In Campaign Hub, there's a spot on each campaign's detail page to enter a "Cobrand tracking link." Once that link is entered, Campaign Hub will automatically pull live performance numbers from Cobrand — things like how many videos have been submitted, how many total comments have come in, and what the engagement looks like.

These numbers update automatically. You don't have to go to Cobrand's website to check — Campaign Hub shows the live numbers right on the campaign page.

There's also a Cobrand upload section at the bottom of each campaign page (toggled by a button in the header). That's where you go to copy the scraped video links and open the Cobrand upload page to submit them.

## Step 6: Tracking budget and payments

As creators post their videos, the team marks them as delivered (posts done). Once a creator has completed their posts and is ready to be paid, a team member marks them as "Paid" using the checkbox in the creators table on the campaign detail page.

The budget section at the top of the campaigns list shows at a glance: total budget, how much is booked (committed to creators), how much has been paid out, how much is left. A progress bar shows what percentage of the budget has been used.

CPM is also calculated automatically. CPM means "cost per thousand views" — it tells you how much the campaign is spending per 1,000 video views, which is how the label (and Rising Tides) measures efficiency.

## Step 7: The campaign finishes

When a campaign wraps up — all creators have posted, all payments are done — Jake marks it as complete.

On the Promotions page, each campaign row has a small checkbox in the far left column. Clicking it cycles through three states:

- **Empty box** → the campaign is running normally
- **Gray checkmark** → booking is complete (all creators are booked, no more being added)
- **Green checkmark** → campaign is fully wrapped

Once the green checkmark is set, the campaign moves from the **Active** tab to the **Finished** tab on the Promotions page. It's archived — it's still visible and you can still look at all its data, but it's out of the active list.

---

*Next: [The Screens](04-screens.md)*
