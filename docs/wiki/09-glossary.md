# 9. Glossary

An A–Z list of every term used in Campaign Hub that someone outside the team might not immediately understand.

---

**Active campaign**
A campaign that is currently running — creators are being booked or have posted, and the campaign hasn't been marked as finished. Active campaigns appear on the Active tab of the Promotions page.

**Artist**
The musician or band whose song is being promoted in a campaign.

**Booking**
The agreement between Rising Tides and a creator: the creator will post a certain number of videos using a specific song, in exchange for a set payment. "Booking a creator" means adding them to a campaign with agreed-upon terms.

**Budget**
The total amount of money Rising Tides has allocated to pay creators for a campaign. This is separate from what the label pays Rising Tides (that's billing, which lives in Notion).

**Booked (budget)**
The portion of the campaign budget that has been committed to creators — i.e., the sum of all creator rates. If the total budget is $5,000 and you've booked creators worth $3,200, then $3,200 is "booked."

**Campaign**
A single music promotion project. One campaign = one song + one client + one set of creators + one budget. Campaign Hub tracks everything about that project from start to finish.

**Campaign Hub**
The tool you're reading this wiki for. Rising Tides' internal dashboard for managing campaigns.

**Cobrand**
An external tracking tool that monitors how campaign videos are performing. Cobrand shows things like total video submissions, comments, and engagement. Campaign Hub reads those numbers from Cobrand automatically. Cobrand is not owned by Rising Tides.

**Cobrand share page**
A Cobrand URL that shows the performance data for a specific campaign. This is the page Campaign Hub visits to extract live stats. The URL contains an authentication token, so keep it private.

**Cobrand tracking link / share URL**
The link entered on the campaign detail page to connect a campaign to Cobrand stats. Once entered, Campaign Hub shows live Cobrand numbers on the campaign page.

**Cobrand upload page**
The Cobrand page where video links are submitted so Cobrand can start tracking them. Accessed through the Cobrand section at the bottom of a campaign detail page.

**Completion status**
A three-stage indicator on each campaign showing whether the campaign is still running (empty), booking is done (gray check), or the whole campaign is wrapped (green check). Controls which tab the campaign appears on.

**CPM (Cost Per Mille / Cost Per Thousand)**
A measure of how much the campaign is spending per 1,000 video views. Lower CPM = more efficient campaign. "Mille" is Latin for thousand.
> *Formula: (Amount Paid ÷ Total Views) × 1,000*

**Creator**
A TikTok or Instagram content creator — someone with their own account and audience — who gets paid to post videos using a campaign's song. Not a Rising Tides employee; a freelancer hired per campaign.

**Creator Database**
The section of Campaign Hub that shows every creator who has ever been booked on any campaign, along with their aggregate stats across all campaigns.

**CRM**
Short for Customer Relationship Manager. A tool for tracking business relationships. Rising Tides uses Notion as its CRM — that's where client (label) relationships and bookings are tracked.

**Finished campaign**
A campaign that has been marked as fully complete with the green checkmark. It moves from the Active tab to the Finished tab on the Promotions page and is effectively archived.

**Internal TikTok**
The section of Campaign Hub for monitoring Rising Tides' own TikTok pages (team members' pages and label pages they manage), separate from the creator campaigns.

**Label**
A record label — the client that hires Rising Tides to promote a song. Examples: Warner Music Group, Atlantic Records.

**Live posts**
Videos that have been found by the scraper and confirmed as posted by booked creators. The "Live Posts" count on the campaigns list shows how many such videos have been found for each campaign.

**Matched video**
A video found by the scraper that uses the campaign's sound and was posted by one of the booked creators. When a scrape runs, it saves matched videos to the campaign record.

**Notion**
The tool Rising Tides uses as a CRM to track client relationships and campaign bookings. Campaign Hub can pull new campaigns from Notion automatically.

**Open CLAW**
The automated assistant that monitors Rising Tides' Slack channel for creator booking messages and sends them to Campaign Hub's Slack Inbox for Jake to approve.

**PayPal email**
The PayPal address for a creator, stored in Campaign Hub. Used by the team when sending creator payments manually through PayPal.

**Platform**
Which social media platform a campaign is running on — TikTok, Instagram, or both.

**Posts done / Posts owed**
For each creator on a campaign, "posts owed" is how many videos they agreed to post. "Posts done" is how many we've confirmed they've actually posted. A creator at "3 / 5" has posted 3 of their 5 required videos.

**Promotions**
The main campaigns list page in Campaign Hub. The word "Promotions" is used in the app's header and sidebar instead of "Campaigns."

**Rate**
The agreed payment amount for a creator's full set of posts on a campaign. If a creator is being paid $350 for 5 posts, $350 is their "rate."

**Round**
Some campaigns run in multiple rounds — e.g., an initial push followed by a second wave. The "Round" field on a campaign (pulled from Notion) tracks which round this is.

**Scraping**
The process of automatically visiting a website (TikTok, Instagram) and collecting information from it. Campaign Hub uses scraping to find creator posts and monitor internal pages.

**Slack Inbox**
The page in Campaign Hub where booking suggestions from Open CLAW (the Slack assistant) appear for Jake to approve or dismiss.

**Slug**
A short, URL-friendly version of a campaign's name, used in the web address for that campaign's page. For example, the campaign "Artist Song Promo R1" might have a slug of `artist-song-promo-r1`, making its URL `/campaign/artist-song-promo-r1`. Slugs use lowercase letters, numbers, and hyphens only.

**Sound / Sound ID**
Every piece of audio on TikTok has a unique numeric ID. When the scraper searches for a campaign's posts, it uses the sound ID to find only videos that used exactly that song. The sound ID is stored on each campaign and needs to be accurate for the scraper to work.

**UGC (User-Generated Content)**
Content created by real people (users of the platform), as opposed to content produced by a brand or ad agency. Labels pay for UGC campaigns because authentic-seeming creator videos drive real cultural engagement — more effective than traditional advertising for the TikTok generation.

---

*Next: [If Something Looks Weird](10-troubleshooting.md)*
