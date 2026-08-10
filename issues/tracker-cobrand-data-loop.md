# Tides Tracker Data Loop — Bug Fix + Skill Build

## Bug: tracker_names not populated on campaign link

### Description
When campaigns are linked to Tides Trackers through the Campaign Hub UI, the `tracker_campaign_links` table correctly stores the connection, but the `tracker_names` table is not being populated with the display name.

### Current State
- 49 tracker-campaign links exist in DB
- Only 4 have corresponding `tracker_names` entries
- 45 tracker IDs have no display name
- The link itself works — Cobrand data syncs correctly

### Impact
Claude can't automatically look up a campaign by name and find its tracker_id for the automated skill. Currently works via campaign slug matching but needs display names for clean automation.

### Fix
Ensure `tracker_names` rows are created when linking campaigns in the Tides Tracker UI.

---

## Discovery: Tides Tracker Public API

### Endpoint
```
GET https://risingtides-tracker.com/api/public/{tracker_id}
```

### What it returns
Every Cobrand submission with full per-creator data:
```json
{
  "success": true,
  "campaign_name": "Shaboozey - Cowgirl Promo",
  "count": 134,
  "videos": [
    {
      "username": "lifecontent1",
      "video_url": "https://tiktok.com/@lifecontent1/video/...",
      "views": 1491405,
      "likes": 23346,
      "comments": 165,
      "shares": 86695,
      "sound_title": "original sound - shaboozeybts",
      "published_at": "2026-05-10T21:57:37Z",
      "engagement_rate": 7.39,
      "author_followers": 1649169
    }
  ]
}
```

### Why this matters
- One API call returns everything Cobrand knows about a campaign
- No scraping needed for post counts or creator stats
- Real-time data, no rate limiting
- This is the source of truth for campaign tracking

---

## Skill Plan: Automated Campaign Status

### Data Flow
```
Campaign Hub DB (campaign slug) 
  → tracker_campaign_links (tracker_id)
    → Tides Tracker API (/api/public/{tracker_id})
      → Full per-creator stats from Cobrand
```

### Skill should:
1. Look up campaign in Railway DB → get tracker_id
2. Hit Tides Tracker API → get all submissions with per-creator data
3. Compare against creators table (posts_owed) → flag who's done, who's short
4. Optionally run master_tracker scrape for new post discovery
5. Output: status table + new links

### Tables involved
- `campaigns` — campaign metadata, slug
- `creators` — posts_owed, posts_done per creator
- `tracker_campaign_links` — maps campaign_slug → tracker_id
- `tracker_names` — display names (BUG: not being populated)

### Railway connection
- Project: happy-wholesome
- Service: Postgres
- CLI: railway v4.37.2 installed
