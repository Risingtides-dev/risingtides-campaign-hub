# Rising Tides Campaign Hub

## Outreach Agent Notion schema

Use `scripts/create_outreach_notion_schema.py` to create the four Notion databases required by the outreach agent.

### Required environment variables

- `NOTION_API_KEY`: Notion integration token.
- `NOTION_PARENT_PAGE_ID`: Notion page ID where the new databases will be created.

### Run

```bash
NOTION_API_KEY=secret_xxx \
NOTION_PARENT_PAGE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
python scripts/create_outreach_notion_schema.py
```

The script creates the following databases and prints their IDs/URLs as JSON (for wrangler.toml configuration in follow-up tickets):

1. **Labels**
   - `name` (title)
   - `tier` (select)
   - `genres` (multi-select)
   - `contacts` (rich text)
   - `roster_size` (number)
   - `relationship_status` (select)
2. **Artists**
   - `name` (title)
   - `label` (relation → Labels)
   - `spotify_url` (url)
   - `monthly_listeners` (number)
   - `genres` (multi-select)
   - `recent_releases` (rich text)
   - `social_links` (url)
3. **Leads**
   - `artist` (relation → Artists)
   - `label` (relation → Labels)
   - `score` (number)
   - `score_reasoning` (rich text)
   - `signals` (multi-select)
   - `status` (select)
   - `scored_at` (date)
4. **Outreach Log**
   - `lead` (relation → Leads)
   - `draft_subject` (rich text)
   - `draft_body` (rich text)
   - `contact` (rich text)
   - `status` (select: `draft`, `sent`, `replied`, `converted`)
   - `created_at` (date)
