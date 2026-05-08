# 4f. The Slack Inbox

**URL:** `/inbox`

**Who uses it:** Jake (primarily), to review and approve creator booking suggestions before they get added to campaigns.

---

## What it is

The Slack Inbox is a staging area for creator bookings that came through Slack.

Rising Tides uses an automated assistant called **Open CLAW** that monitors the company Slack. When someone in Slack mentions a creator booking (for example: "book @dancegirl_tiktok for 3 posts at $200 on the new Doja campaign"), Open CLAW parses that message and sends a booking suggestion into Campaign Hub.

That suggestion lands in the Slack Inbox as a card. Jake reviews it — if it looks right, he approves it and the creator is automatically added to the campaign. If it's wrong or a duplicate, he dismisses it.

---

## Layout description

```
┌─────────────────────────────────────────────────────────────┐
│ Slack Inbox                             12 pending          │
├─────────────────────────────────────────────────────────────┤
│  PENDING APPROVAL                                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ @dancegirl_tiktok · 3 posts · $200 · Doja - Say So   │  │
│  │ "book @dancegirl_tiktok for 3 posts..."               │  │
│  │                         [Approve]  [Dismiss]          │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ (more pending cards...)                               │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  RECENTLY APPROVED                                          │
│  (up to 10 approved cards shown)                           │
├─────────────────────────────────────────────────────────────┤
│  DISMISSED                                                  │
│  (up to 5 dismissed cards shown)                           │
└─────────────────────────────────────────────────────────────┘
```

---

## The three sections

**Pending Approval:** Suggestions from Open CLAW that haven't been acted on yet. This is what you need to review.

**Recently Approved:** The 10 most recently approved bookings. Just for reference — these creators have already been added to their campaigns.

**Dismissed:** The 5 most recently dismissed suggestions. Again, just for reference.

---

## Each inbox card shows

- The creator's username
- How many posts they'd be booked for
- Their proposed rate
- Which campaign they'd be added to
- The raw Slack message Open CLAW read (so you can verify it made sense)
- Two buttons: **Approve** and **Dismiss**

---

## Approving a booking

Click **Approve** on a card. Campaign Hub immediately:
1. Adds that creator to the specified campaign
2. Sets their posts owed and total rate as shown on the card
3. Moves the card from Pending to Recently Approved

No page reload. You can approve multiple cards in a row quickly.

---

## Dismissing a booking

Click **Dismiss** if the suggestion is wrong, a duplicate, or not relevant. The card moves to the Dismissed section. The creator is NOT added to any campaign.

---

## If the inbox is empty

If no bookings have come in yet, the page shows an empty state message: "No inbox items yet." This is normal when no Open CLAW suggestions have been sent. The inbox only fills up when the Slack agent is actively running and finds booking messages.

---

## What Open CLAW looks for in Slack

Open CLAW parses messages like:
- "book @username for X posts at $Y on [campaign name]"

It extracts the creator username, post count, rate, and tries to match the campaign name to an existing campaign in Campaign Hub. If it can't figure out the campaign, the card still appears in the inbox but Jake will need to manually select the right campaign before approving.
