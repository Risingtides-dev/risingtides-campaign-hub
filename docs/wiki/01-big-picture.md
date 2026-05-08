# 1. The Big Picture

## What Is Campaign Hub?

Campaign Hub is Rising Tides' internal command center for managing music promotion campaigns on TikTok and Instagram.

When a record label pays Rising Tides to promote a song, everything about that campaign — who gets hired to post about it, how much they're paid, how many posts they owe, what videos they've already made, and how the campaign is performing — lives here.

## What Problem Does It Solve?

Before Campaign Hub existed, Jake kept all of this information in spreadsheets, local files, and his head. Finding a creator's PayPal address meant digging through a CSV. Checking how much budget was left meant doing math by hand. Seeing which creators still owed posts required cross-referencing multiple documents.

Campaign Hub puts all of that in one place and makes it fast to look up, update, and act on.

## Who Pays for What?

**Record labels** (like Warner Bros. or Atlantic) are Rising Tides' clients. They pay Rising Tides to run promotion campaigns — to find creators and get them to post videos using a specific song.

**Creators** are the people who actually make the videos. Rising Tides pays them. Their rates, payment status, and post counts all live in Campaign Hub.

Campaign Hub tracks the money flowing *out* to creators. The money flowing *in* from labels is tracked in a separate system called Notion. Campaign Hub never touches that side of the ledger.

## Where Does Campaign Hub Fit?

Campaign Hub is one piece of a larger workflow. Here's the full picture:

```
Label books a campaign
        ↓
Notion CRM (client info lives here — not in Campaign Hub)
        ↓
Campaign Hub (your control panel)
    ├── Slack inbox → Jake approves creators
    ├── Scraper finds creator videos using the song's sound
    └── Cobrand tracks live performance numbers
```

In plain English:
- **Notion** is where clients are tracked. A new "Client" entry in Notion triggers a new campaign in Campaign Hub.
- **Slack** is where an automated assistant sends booking suggestions. Jake approves or dismisses them in Campaign Hub.
- **Cobrand** is a third-party platform that measures how well the campaign posts are performing (views, engagement). Campaign Hub pulls those numbers in automatically once you connect a tracking link.
- **TikTok and Instagram** are where the actual posts live. Campaign Hub finds them automatically using the song's unique sound ID.

Campaign Hub is the hub in the middle — it connects all of these moving parts and gives the Rising Tides team a single place to manage everything.

---

*Next: [Who Does What →](02-who-does-what.md)*
