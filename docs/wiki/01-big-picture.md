# 1. The Big Picture

## What is Campaign Hub?

Campaign Hub is the internal tool Rising Tides uses to run its TikTok and Instagram influencer campaigns. Think of it as a command center: it's where the team keeps track of every active promotion, every creator booked on that promotion, how much each creator is being paid, what posts they've delivered, and how those posts are performing.

Before Campaign Hub existed, this information lived in spreadsheets, text threads, and Jake's memory. Campaign Hub puts it all in one place.

## What problem does it solve?

Rising Tides runs dozens of campaigns at once. Each campaign involves:

- A record label that paid Rising Tides to run a promotion
- A song (or sound) they want creators to use
- A list of TikTok or Instagram creators who agreed to post using that sound
- Specific deadlines for those posts
- Money owed to each creator when they deliver

Without a tool, tracking all of that across 10 or 20 active campaigns simultaneously would be nearly impossible. Campaign Hub makes it manageable: you can see everything in one screen, update it in real time, and know at a glance who's been paid, who still owes posts, and how the campaign is tracking.

## Who pays for the service, and what do they get?

The clients are **record labels** — companies like Warner Music Group, Atlantic Records, Republic Records, and similar. They pay Rising Tides to run User Generated Content (UGC) campaigns: they want real creators on TikTok and Instagram to post videos using a specific song.

When creators post using the sound, it drives streams, chart placements, and general buzz for the artist. The label pays Rising Tides a fee; Rising Tides pays the creators; the creators post. Campaign Hub is how Rising Tides manages that whole chain.

## Where does Campaign Hub fit in the bigger picture?

Campaign Hub is one piece of a larger system. Here's how it connects to everything else:

```
Notion (client bookings)
   |
   | A label books a campaign through our CRM
   |
   ▼
Campaign Hub  ← this is the tool you're reading about
   |
   +── Slack agent (Open CLAW) → Inbox → Jake approves → Creators added
   |
   +── Scrapers look for creator posts using the right sound
   |
   +── Post links copied → uploaded to Cobrand
   |
   ▼
Cobrand (live performance numbers: views, submissions, comments)
```

- **Notion** is where client relationships and bookings are managed. When a label signs on for a campaign, it starts in Notion and flows into Campaign Hub.
- **Slack** is where an automated assistant called Open CLAW surfaces creator booking suggestions for Jake to approve.
- **Cobrand** is the third-party tracking service that measures how a campaign is performing — it counts how many posts were submitted and how many views they're getting.
- **TikTok and Instagram** are the actual platforms where creators post. Campaign Hub doesn't control those — it just tracks what happens there.

---

*Next: [Who Does What](./02-who-does-what.md)*
