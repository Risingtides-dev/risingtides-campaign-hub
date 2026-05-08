# 12. The Money Trail

One of the most important rules of Campaign Hub: **different types of money information live in different places.** Mixing them up causes confusion and errors.

Here's a plain-English map of where each type of financial information lives and why.

---

## What Lives in Campaign Hub (This App)

### Creator rates
When a creator is booked for a campaign, their agreed rate (total payment for all posts) is stored here. This is what Rising Tides owes them.

### Campaign budgets
Each campaign has a total budget set when the campaign is created. Campaign Hub uses this to calculate how much has been spent and how much is left.

### Payments to creators
When a creator gets paid, you check off the payment in Campaign Hub. It records whether they've been paid, what their PayPal address is, and when the payment was made.

### Budget calculations
Campaign Hub automatically calculates:
- **Booked** — the sum of all creator rates (what you've committed to spend)
- **Paid** — the sum of rates for creators marked as paid (what's gone out the door)
- **Remaining** — budget minus paid (what's left)
- **Budget used %** — paid divided by total budget
- **CPM** — cost per thousand views (paid divided by total views, times 1,000)

All of these are calculated live from the data you've entered. There's no manual updating.

---

## What Lives in Notion (Not Here)

### What the label pays Rising Tides
The amount a label pays Rising Tides for a campaign is tracked in Notion, the client CRM. Campaign Hub never sees or stores this number. The business relationship with clients belongs in Notion.

---

## What Lives in Cobrand (Not Here)

### Performance data (views, comments, engagement)
How many people watched the videos, how many comments they got, how engaged the audience was — all of this comes from Cobrand. Campaign Hub displays these numbers, but it doesn't calculate or store them. If the Cobrand connection is broken, the performance numbers disappear from Campaign Hub — but the financial data (rates, payments, budgets) is unaffected.

---

## The Big Rule

> **Money lives here. Performance lives in Cobrand. Client info lives in Notion. Don't mix them up.**

If someone asks you "how much did we make on this campaign?" — that answer is in Notion (what the label paid us) minus what Campaign Hub shows as paid out to creators. Neither system has the full picture alone; you have to look at both.

If someone asks "how many views did we get?" — that answer is in Cobrand (or displayed in Campaign Hub if the tracking link is connected).

If someone asks "how much did we pay creators?" — that answer is in Campaign Hub.

---

*Next: [The Scrapers →](13-scrapers.md)*
