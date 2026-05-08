# 4f. The Slack Inbox

**URL:** `/inbox`

**Who uses it:** Jake (primarily), to review and approve creator booking suggestions before they get added to campaigns.

---

## What it is

The Slack Inbox is a staging area for creator bookings that came in through Slack.

Rising Tides uses an automated Slack assistant called **Open CLAW** that watches the company Slack. When someone in Slack types a booking message — e.g. *"book @dancegirl_tiktok for 3 posts at $200 on the new Doja campaign"* — Open CLAW parses it, figures out who, how many posts, what rate, and which campaign, and sends a booking suggestion into Campaign Hub.

That suggestion lands in the Slack Inbox as a card. Jake reviews each card and clicks **Approve** or **Dismiss**. Approve adds the creator to the right campaign automatically. Dismiss just discards the suggestion.

---

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Slack Inbox                            12 pending           │
├─────────────────────────────────────────────────────────────┤
│  PENDING APPROVAL                                           │
│  ┌────────────────────────────────────────────────────┐    │
│  │ @dancegirl_tiktok · 3 posts · $200 · Doja - Say So │    │
│  │ "book @dancegirl_tiktok for 3 posts..."            │    │
│  │                          [Approve]  [Dismiss]      │    │
│  └────────────────────────────────────────────────────┘    │
│  (more pending cards…)                                     │
├─────────────────────────────────────────────────────────────┤
│  RECENTLY APPROVED  (up to 10 cards)                       │
├─────────────────────────────────────────────────────────────┤
│  DISMISSED  (up to 5 cards)                                │
└─────────────────────────────────────────────────────────────┘
```

---

## The three sections

| Section | What it contains |
|---|---|
| **Pending Approval** | Booking suggestions from Open CLAW that haven't been acted on yet. This is the main queue Jake works through. |
| **Recently Approved** | The 10 most recently approved bookings. Reference only — these creators have already been added to their campaigns. |
| **Dismissed** | The 5 most recently dismissed suggestions. Reference only — these were not added anywhere. |

---

## What each card shows

- The creator's username
- How many posts they'd be booked for
- Their proposed rate
- Which campaign they'd be added to
- The original raw Slack message (so you can verify Open CLAW parsed it correctly)
- Two buttons: **Approve** and **Dismiss**

---

## Approving a booking

Click **Approve**. Campaign Hub immediately:

1. Adds that creator to the specified campaign
2. Sets their posts owed and total rate as shown on the card
3. Moves the card from Pending into Recently Approved

No page reload. You can fly through approvals one after another.

---

## Dismissing a booking

Click **Dismiss** if the suggestion is wrong, a duplicate, or not relevant. The card moves into the Dismissed section. The creator is *not* added to any campaign.

---

## When the inbox is empty

If no bookings have come in yet, the page shows an empty state: "No inbox items yet." This is normal during quiet periods. The inbox only fills up when Open CLAW sees booking messages in Slack.

---

## What Open CLAW looks for

Open CLAW parses Slack messages roughly in this shape:

> *book @username for X posts at $Y on [campaign name]*

It pulls out the creator username, post count, rate, and tries to match the campaign name to an existing campaign in Campaign Hub. If it can't figure out which campaign, the card still shows up in the Inbox but Jake will need to manually pick the right campaign before approving.

---

*Next: [Internal TikTok Tool](./04-screens-internal-tiktok.md)*
