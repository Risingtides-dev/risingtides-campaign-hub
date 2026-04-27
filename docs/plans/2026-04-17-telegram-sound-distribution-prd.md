# Telegram Sound Distribution — PRD

> **Status:** Draft for review. No code written yet.
> **Author:** AI-assisted PRD from exploration session, 2026-04-17.
> **Owner:** John (john_smathers)
> **Target repos:** `risingtides-campaign-hub` (this repo) + `content-posting-lab` (peer repo)
> **Primary outcome:** A Campaign Hub tab that sends niche-targeted sound assignments to the 7 operator Telegram groups, without duplicating data between the two apps.

---

## 1 · TL;DR

Build a **Sound Distribution** tab in Campaign Hub that lets John (or any internal user) trigger a Telegram blast of active sound campaigns to the 7 operator poster groups. Each operator only sees sounds their pages are niche-matched for. Campaign Hub owns the **assignment logic** (creators × niche tags). `content-posting-lab` stays the **Telegram execution engine** (bot, chat IDs, actual `sendMessage` calls). The two apps cooperate over HTTP with clean source-of-truth boundaries — no data is duplicated, no two-way sync is needed.

The feature sits on top of infrastructure that already exists in both apps and mostly adds the missing "per-niche" filtering layer. Estimated scope: **~2 weeks of focused work** (see §11 for phase breakdown).

---

## 2 · Background & motivation

### 2.1 What exists today

**In `risingtides-campaign-hub`** (Flask + React, deployed on Railway + Vercel):
- 29 internal "free-agent" TikTok pages are already modeled as `InternalCreator` rows.
- 6 `booked_by` groups (Johnny's, John's, Sam's, Eric's, Jake's, Seeno's Pages) already exist with correct memberships.
- 3 `label` groups (Warner/Atlantic/Warner Test) also exist but are **out of scope** — label posters self-serve from TikTok favorites and don't need Telegram drops.
- `InternalCreatorGroup` schema supports `kind='niche'` but **no `niche` groups have been created yet**.
- `InternalCreator.niche` is a free-text string field (not a controlled vocabulary) and is largely empty.
- Existing REST endpoints: full CRUD for groups and group-member management at `/api/internal/groups*`.

**In `content-posting-lab`** (FastAPI + React, deployed on Railway, separate Vercel):
- Telegram bot is live and connected (`@content_lab_dev_bot` or equivalent).
- All 7 operator poster groups are registered with real chat IDs, seeded in `services/telegram.py:25` (`_DEFAULT_POSTERS`):
  - seffra → `-1003869464172`
  - gigi → `-1003814954137`
  - johnny-balik → `-1003754164520`
  - sam-hudgen → `-1003691005229`
  - jake-balik → `-1003867018292`
  - eric-cromartie → `-1003796560010`
  - john-smathers → `-1003302681249`
- Staging group "Rising Tides Pages" → `-1003748889949`.
- Per-poster "Campaign Sounds" topics auto-created on first send (`routers/telegram.py:1375` `_ensure_sounds_topic`).
- A working sound-forward pipeline: `POST /api/telegram/sounds/forward/{poster_id}` sends all active sounds to a single poster; `POST /api/telegram/sounds/forward-all` blasts to every poster.
- Already pulls active campaigns from Campaign Hub via `services/campaign_hub.py` (URL: `https://risingtides-campaign-hub-production.up.railway.app`).
- Already matches Campaign Hub campaigns to Notion CRM rows using a deterministic slug pass + GPT-4.1-mini fuzzy fallback to discover the TikTok Sound Link.

**In Notion CRM** (`1961465bb82980c9a1b5c4cb3284149a`, titled "Rising Tides CRM"):
- Field **`Types of Content Creators`** is a **multi-select** with 10 options:
  1. Everything Welcome (wildcard)
  2. POV
  3. Trucktok
  4. NatureTok
  5. Face Creators
  6. Anime
  7. Country-Leaning
  8. Relationship
  9. Poetry
  10. other
- As of 2026-04-17 the field is empty on most rows — tagging is aspirational/incomplete, not historical data.
- Other relevant fields already consumed by `content-posting-lab/services/notion.py`: `Artist Name`, `Song Name`, `TikTok Sound Link`, `Insta Sound Link`, `Campaign Stage`, `Pipeline Status`.

### 2.2 The gap

The `content-posting-lab/HANDOFF.md` file literally names this as the next feature:

> **"Sound-to-video pairing — currently all posters get all sounds. Future: campaign-aware assignment based on which pages are on which campaigns."**

Today, when someone runs `/sounds/forward-all`, every poster gets every active sound regardless of fit. That's wasteful and noisy. The feature in this PRD adds the missing **per-niche filter** so each operator only sees sounds tagged for content types their pages produce.

### 2.3 Why Campaign Hub is the right UI home

The original ask was a tab in Campaign Hub. After exploration, that's still correct because:

1. **Campaign Hub is where campaigns are managed.** Users are already there to check stats, book creators, and track performance. Adding sound distribution there is a natural extension.
2. **The assignment data (creators × niches) belongs to Campaign Hub's domain.** `content-posting-lab` is a thin execution shell over Telegram; putting niche UI there would split CRUD across two apps.
3. **`content-posting-lab` stays headless for this feature.** Its existing UI can keep its manual send buttons for ops/testing, but the primary workflow becomes Campaign Hub → cross-app send.

---

## 3 · Design decisions (the three questions John asked me to answer)

These were the last three open questions in the exploration session. **All three are resolved in this PRD with explicit recommendations; John should confirm or override before implementation starts.**

### 3.1 Decision: where does the tab live?

**✅ Campaign Hub.** Execution stays in `content-posting-lab` via HTTP calls.

See §4 for the full architecture and §5 for the explicit source-of-truth split.

### 3.2 Decision: what to do with untagged sounds

Three options:
1. **Skip** — sound has no `Types of Content Creators` value → don't send anywhere. Safest; requires manual tagging.
2. **Fallback to "Everything Welcome" pages** — untagged sounds still go out, but only to the subset of pages tagged as wildcards.
3. **Alert & block** — explicit UI warning, send disabled until tagged.

**✅ Recommendation: hybrid of 1 and 3.**
- In the UI, untagged sounds render with a yellow warning badge ("No content type assigned — will not be sent").
- They're *excluded* from send-by-default.
- A **"Tag in Notion"** button deep-links to the Notion row so the user fixes it there (source of truth stays in Notion).
- A **force-send toggle** (checked off by default) lets you override and send to "Everything Welcome" pages if the user insists.

Rationale: Silent drops are worse than loud warnings. Forcing users to tag in Notion keeps the vocabulary clean (no drift between CH and Notion), and tagging a single field takes 5 seconds.

### 3.3 Decision: how do the 29 internals get niche-tagged initially?

Three options:
1. **Manual in CH UI, zero seeding** — John tags each of 29 pages by hand (~10 min of work).
2. **Seed from existing `InternalCreator.niche` free-text** — best-effort auto-map, user corrects.
3. **Pull from Notion** — if there's a parallel "internal creators" DB in Notion with niches, import from there.

**✅ Recommendation: option 1, with a well-designed UI.**
- Build a bulk-tag interface (page rows × niche columns as checkboxes, batch-save).
- `InternalCreator.niche` text field is too noisy to auto-seed usefully (sample check showed mostly empty strings).
- 29 pages × ~30 seconds each = 15 minutes of work one-time. Not worth automating.
- Option 3 is unknown territory (no such Notion DB confirmed to exist).

---

## 4 · Architecture

### 4.1 High-level flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Campaign Hub (Flask + React)                       │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────┐         │
│  │ NEW: "Sound Distribution" tab                            │         │
│  │                                                           │         │
│  │  1. Manage niche tags (CRUD)                              │         │
│  │  2. Tag creators with niches                              │         │
│  │  3. View active sounds + their Notion content tags        │         │
│  │  4. Preview per-operator send (who gets what)             │         │
│  │  5. Send (triggers content-posting-lab)                   │         │
│  │  6. View send history                                     │         │
│  └──────┬──────────────────────────────────────────┬────────┘         │
│         │ CRUD (local)                             │ HTTP POST (fwd)  │
│         ▼                                          │                  │
│  ┌─────────────────────────────┐                   │                  │
│  │ Flask backend                │                   │                  │
│  │ /api/internal/groups*        │                   │                  │
│  │ /api/campaigns               │                   │                  │
│  │ NEW: /api/distribution/*     │───────────────────┘                  │
│  └──────┬──────────────────────┘                                     │
│         ▼                                                             │
│  ┌─────────────────────────────┐                                     │
│  │ PostgreSQL (Railway)         │                                     │
│  │  - internal_creators         │                                     │
│  │  - internal_creator_groups   │                                     │
│  │  - internal_creator_group_   │                                     │
│  │    members                   │                                     │
│  │  NEW: distribution_sends     │  (audit log table)                  │
│  └──────────────────────────────┘                                     │
│                                                                       │
└──────────────────────────────────────────────────┼────────────────────┘
                                                    │
                                                    │ HTTPS (JSON)
                                                    │ X-Distribution-Token header
                                                    ▼
┌──────────────────────────────────────────────────────────────────────┐
│              content-posting-lab (FastAPI + React)                    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────┐         │
│  │ Existing endpoints (unchanged):                           │         │
│  │  POST /api/telegram/sounds/forward/{poster_id}            │         │
│  │  POST /api/telegram/sounds/forward-all                    │         │
│  │  GET  /api/telegram/posters                               │         │
│  │  GET  /api/telegram/sounds                                │         │
│  │                                                           │         │
│  │ NEW endpoint:                                             │         │
│  │  POST /api/telegram/sounds/forward-filtered               │         │
│  │    body: {poster_id, sound_ids, header_override?}         │         │
│  └───────────────────┬──────────────────────────────────────┘         │
│                      ▼                                                │
│  ┌───────────────────────────────┐                                   │
│  │ Telegram Bot API              │                                   │
│  │ (sends to poster Telegram     │                                   │
│  │  groups via stored chat_ids)  │                                   │
│  └───────────────────────────────┘                                   │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.2 Key architectural principles

1. **No data duplication.** Niches and creators-by-niche live in Campaign Hub's Postgres. Sounds live in `content-posting-lab`'s `telegram_config.json` (already synced from CH via `services/campaign_hub.py`). Neither side writes to the other's source of truth.
2. **Cross-app calls are stateless.** Campaign Hub's "send" button calls `content-posting-lab` with a fully-resolved payload (poster_id + sound_ids + formatted message). No ongoing sync. If the HTTP call fails, CH logs it and lets the user retry.
3. **Auth between the two apps uses a shared secret header.** New env var `DISTRIBUTION_SHARED_SECRET` on both ends. CH sends `X-Distribution-Token: <secret>`; CPL validates. Keeps infra simple — no OAuth dance needed for 2 internal services.
4. **The existing CPL endpoints stay as-is.** The new filtered endpoint (`/forward-filtered`) is purely additive. Ops can still manually hit `/forward-all` from CPL's own UI for emergencies.

---

## 5 · Source-of-truth split (the full table)

Answers John's "can we make this 2-way" question concretely.

| Concept | Source of truth | Other side reads via | Write direction |
|---|---|---|---|
| Creator identity (username, display_name) | Campaign Hub | CPL calls `GET /api/internal/creators` | 1-way (CH → CPL reads) |
| Niche tag definitions (the 10 niches as CH groups) | Campaign Hub | CPL doesn't read (not needed) | CH-only |
| Creator × niche assignments | Campaign Hub (`InternalCreatorGroupMember`) | CPL doesn't read | CH-only |
| Notion content-type tags on sounds | Notion | Both apps read on demand via Notion API | Read-only in both apps; editing happens in Notion UI |
| Active sound list | Notion → CPL's `telegram_config.json` (already synced) | CH reads via `GET {cpl}/api/telegram/sounds` | 1-way (Notion → CPL) |
| Poster chat_ids, Telegram topics | CPL (`telegram_config.json`) | CH reads via `GET {cpl}/api/telegram/posters` | CPL-only |
| Sound send history (audit log) | Campaign Hub (NEW table `distribution_sends`) | CPL's `/forward-filtered` returns the ID; CH persists | CH writes on its side; CPL is stateless |

**Nothing is 2-way in the read/write sense.** The *appearance* of a unified UI is achieved by having the CH tab call the right backend per concept. This was the key insight in the exploration session: "2-way" sounds clean but creates drift bugs — keeping each concept 1-way on one side is the actually-clean design.

---

## 6 · Data model changes

### 6.1 Campaign Hub — new Postgres table

**`distribution_sends`** — audit log of every send triggered from the tab.

```python
# campaign_manager/models.py — add to the Internal creator groups section

class DistributionSend(Base):
    """Log of a Telegram sound distribution triggered from the CH tab.

    Each row = one send action (one user click on "Send"). Records who
    was targeted, what sounds, and what the CPL response was. This
    gives us an audit trail even though CPL itself is stateless.
    """
    __tablename__ = "distribution_sends"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    triggered_by = Column(String(255), default="")  # user identifier; free text for now, no auth yet

    # What was sent
    sound_ids = Column(JSONB, nullable=False)  # list[str] — CPL sound IDs (opaque)
    sound_labels = Column(JSONB, nullable=False)  # list[str] — denormalized for audit readability
    niche_slugs = Column(JSONB, nullable=False, default=list)  # which niches were in the filter
    poster_ids = Column(JSONB, nullable=False)  # list[str] — target posters

    # Outcome per poster
    results = Column(JSONB, nullable=False, default=dict)
    # shape: {"<poster_id>": {"status": "sent"|"failed", "sent_count": int, "error": str|null, "cpl_response": {...}}}

    status = Column(String(20), default="partial", index=True)
    # "success" (all posters ok), "partial" (some failed), "failed" (all failed), "pending" (in progress)

    # Optional — for "what would have been sent" previews; null if this was a real send
    is_dry_run = Column(Boolean, default=False)

    def to_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "triggered_by": self.triggered_by or "",
            "sound_ids": self.sound_ids or [],
            "sound_labels": self.sound_labels or [],
            "niche_slugs": self.niche_slugs or [],
            "poster_ids": self.poster_ids or [],
            "results": self.results or {},
            "status": self.status or "pending",
            "is_dry_run": bool(self.is_dry_run),
        }
```

### 6.2 Campaign Hub — no changes to existing tables

`InternalCreatorGroup` and `InternalCreatorGroupMember` are already perfect for niche tagging. The only new data is **instances of `InternalCreatorGroup` where `kind='niche'`**, created via the existing POST endpoint. A seed migration populates 10 niche groups (one per Notion content-type tag, plus "other" → skip).

### 6.3 content-posting-lab — no data model changes

Everything needed is already in `telegram_config.json`. The new endpoint (`/forward-filtered`) is a thin variant of the existing `/forward/{poster_id}`.

### 6.4 Migration plan for existing data

1. Run Alembic migration creating `distribution_sends` table (new).
2. Run a one-time seed script that creates the 10 niche groups (see §9).
3. No migration needed for `InternalCreator` — its `niche` text field stays as-is (cosmetic/legacy; not used by this feature). Could be backfilled in a follow-up cleanup task.

---

## 7 · API contract — new endpoints

### 7.1 Campaign Hub — new endpoints (under `/api/distribution/*`)

Mounted as a new blueprint `campaign_manager/blueprints/distribution.py`.

#### 7.1.1 `GET /api/distribution/sounds`
Returns the list of active sounds **augmented with Notion content-type tags and matched-posters preview**.

```jsonc
// Response
[
  {
    "cpl_sound_id": "a1b2c3d4e5f6",              // from content-posting-lab
    "label": "Mon Rovia - Worship or Love",
    "url": "https://www.tiktok.com/music/...",
    "active": true,

    // From Notion lookup (matched by artist+song slug, same logic CPL already uses)
    "notion_page_id": "1991465b-b829-8066-aecc-dbbb49e6a155",
    "notion_url": "https://www.notion.so/...",
    "content_types": ["POV", "Relationship"],    // empty array if untagged
    "campaign_stage": "Posts are live",

    // Per-niche resolution preview
    "matched_creators": ["yellowfont.halfspeed", "buck.wilders", "..."],  // derived via creator↔niche joins
    "matched_posters": ["john-smathers", "sam-hudgen"],                   // derived via matched_creators × booked_by

    // Warning flags for UI
    "warnings": ["untagged"]  // possible values: "untagged", "no_matches", "missing_notion"
  },
  ...
]
```

Backend implementation:
1. Call `GET {CPL}/api/telegram/sounds?active_only=true`.
2. For each sound, look up Notion by artist+song (cache 5 min) to fetch `Types of Content Creators`.
3. For each content type, resolve to CH `InternalCreatorGroup(kind='niche', slug=<slugified>)` → members.
4. Pivot members through `InternalCreatorGroupMember` joined with `booked_by` groups to get posters.
5. Return enriched list.

#### 7.1.2 `GET /api/distribution/posters`
Proxies `GET {CPL}/api/telegram/posters`, filtered to only `booked_by` posters (skip label-page posters). Cached 1 min.

```jsonc
[
  {
    "poster_id": "john-smathers",
    "name": "John Smathers",
    "chat_id": -1003302681249,       // echoed for debugging; hidden in UI
    "has_sounds_topic": true,
    "ch_booked_by_slug": "john_smathers",  // cross-referenced with CH's group
    "page_count": 9,                 // from CPL's page_ids
    "member_count": 9                // from CH's group members (should match)
  },
  ...
]
```

#### 7.1.3 `GET /api/distribution/niches`
List all `kind='niche'` groups with member counts. Wraps existing `/api/internal/groups` with a filter.

```jsonc
[
  {"slug": "pov", "title": "POV", "member_count": 12, "color": "blue"},
  {"slug": "trucktok", "title": "Trucktok", "member_count": 5, "color": "orange"},
  ...
]
```

#### 7.1.4 `POST /api/distribution/niches`
Create a new niche. Wraps `POST /api/internal/groups` with `kind='niche'` forced.

Body: `{"slug": "pov", "title": "POV", "notion_tag": "POV"}` — notion_tag optional; defaults to title.

#### 7.1.5 `PATCH /api/distribution/niches/<slug>/members`
Bulk update creator membership in a niche. Supports the "page × niche checkbox matrix" UI in bulk.

Body:
```jsonc
{
  "add": ["yellowfont.halfspeed", "buck.wilders"],
  "remove": ["some.other.user"]
}
```

#### 7.1.6 `POST /api/distribution/preview`
Dry-run: compute who would get what without actually sending. Writes a `DistributionSend` row with `is_dry_run=true`.

Body:
```jsonc
{
  "sound_ids": ["a1b2c3d4e5f6", "f7e8d9c0b1a2"],   // if empty, use all active sounds
  "niche_filter": ["pov", "country_leaning"],       // if empty, use all niches implied by sounds' Notion tags
  "poster_filter": ["john-smathers", "sam-hudgen"], // if empty, all booked_by posters
  "include_untagged_sounds": false
}
```

Response:
```jsonc
{
  "dry_run_id": 42,
  "summary": {
    "sound_count": 2,
    "poster_count": 2,
    "untagged_sounds_excluded": 1
  },
  "per_poster": {
    "john-smathers": {
      "sound_ids": ["a1b2c3d4e5f6"],
      "sound_labels": ["Mon Rovia - Worship or Love"],
      "matched_via_creators": ["yellowfont.halfspeed", "johnsamuelsmathers"],
      "message_preview": "🎵 Active Sounds — April 17, 2026\n\n• Mon Rovia - Worship or Love\n  https://tiktok.com/music/..."
    },
    "sam-hudgen": { ... }
  },
  "warnings": [
    {"level": "warn", "code": "untagged", "message": "Sound 'Artist - Song' has no content type and was excluded"}
  ]
}
```

#### 7.1.7 `POST /api/distribution/send`
Real send. Same request body as `/preview` + optional `idempotency_key`. Writes a `DistributionSend` row with `is_dry_run=false` and a `status="pending"` initially, updated as CPL calls complete.

Response: identical shape to preview but with `send_id` instead of `dry_run_id`, and `results` populated from CPL responses (per-poster success/failure).

#### 7.1.8 `GET /api/distribution/sends?limit=50`
List recent `DistributionSend` rows (paginated). For the "Send history" panel.

#### 7.1.9 `GET /api/distribution/sends/<id>`
Single send detail (for drilling into a past send).

### 7.2 content-posting-lab — one new endpoint

#### 7.2.1 `POST /api/telegram/sounds/forward-filtered`
Variant of `/sounds/forward/{poster_id}` that sends only a subset of sounds, not all active ones.

Request headers: `X-Distribution-Token: <DISTRIBUTION_SHARED_SECRET>` (required).

Body:
```jsonc
{
  "poster_id": "john-smathers",
  "sound_ids": ["a1b2c3d4e5f6", "f7e8d9c0b1a2"],
  "header_override": "🎵 Today's Drops — April 17",  // optional, defaults to same format as /forward-all
  "ch_send_id": 42                                     // optional, echoed back for CH audit log correlation
}
```

Response:
```jsonc
{
  "ok": true,
  "sent": 2,
  "poster_id": "john-smathers",
  "chat_id": -1003302681249,
  "topic_id": 5,
  "ch_send_id": 42
}
```

Implementation: near-clone of existing `forward_sounds_to_poster` at `routers/telegram.py:1398`, but iterates over the provided `sound_ids` only. Reuses `_ensure_sounds_topic`, `_tg_bot.send_text_to_topic`, and existing auth/config code.

### 7.3 Auth/security between CH and CPL

- **Shared secret** in env var `DISTRIBUTION_SHARED_SECRET` (both Railway deployments).
- Header `X-Distribution-Token: <secret>` on every cross-app call.
- CPL validates via a FastAPI dependency:
  ```python
  def require_distribution_token(x_distribution_token: str = Header(...)):
      expected = os.getenv("DISTRIBUTION_SHARED_SECRET", "").strip()
      if not expected or x_distribution_token != expected:
          raise HTTPException(status_code=403, detail="Invalid distribution token")
  ```
- This is sufficient because **both services are internal Railway deployments** with non-public URLs; the token is defense-in-depth not the only control.
- No user-level auth in Campaign Hub yet (CLAUDE.md: "Don't add auth yet. Internal tool, small team, no auth for now."). The `triggered_by` field in `DistributionSend` stays free-text for now; when auth lands later, backfill by joining with session cookies.

---

## 8 · Frontend — the "Sound Distribution" tab

### 8.1 Route & sidebar entry

- New route: `/distribution`
- Sidebar link "Distribution" under the existing nav, with an icon like `Send` from `lucide-react`.
- Page component: `frontend/src/pages/Distribution.tsx`
- Supporting components in `frontend/src/components/distribution/`

### 8.2 Layout — four sections in the tab

```
┌───────────────────────────────────────────────────────────────────────┐
│  Sound Distribution                                    [Send history] │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ▶ Active Sounds                                 [Sync from Notion]   │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ ✓ Mon Rovia - Worship or Love    [POV] [Relationship]  → 2 posters│ │
│  │ ✓ Ryan Beatty - Cinnamon Bread   [Anime]               → 1 poster│ │
│  │ ⚠ Unknown Artist - Demo Track    [no tags]             [Tag in Notion]│ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ▶ Targets                                                            │
│  ┌──────────────┬──────────────┬─────────────────────────────────┐  │
│  │ Posters       │ Niches        │ Preview                         │  │
│  │ ☑ John  (9)   │ ☑ POV         │ John Smathers (9 pages)         │  │
│  │ ☑ Sam   (5)   │ ☑ NatureTok   │   → 2 sounds                    │  │
│  │ ☐ Jake  (5)   │ ☐ Trucktok    │   Mon Rovia, Ryan Beatty        │  │
│  │ ...           │ ...           │                                  │  │
│  └──────────────┴──────────────┴─────────────────────────────────┘  │
│                                                                       │
│  ▶ Message preview                                                    │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 🎵 Active Sounds — April 17, 2026                                │ │
│  │                                                                   │ │
│  │ • Mon Rovia - Worship or Love                                     │ │
│  │   https://www.tiktok.com/music/...                               │ │
│  │                                                                   │ │
│  │ • Ryan Beatty - Cinnamon Bread                                    │ │
│  │   https://www.tiktok.com/music/...                               │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│                                    [Preview] [  Send to 2 posters  ] │
└───────────────────────────────────────────────────────────────────────┘
```

### 8.3 Component breakdown

- **`pages/Distribution.tsx`** — page shell, loads sounds + posters + niches in parallel via React Query, manages selection state.
- **`components/distribution/SoundsTable.tsx`** — scrollable table of active sounds with their Notion tags and a checkbox column. Untagged sounds show a yellow warning badge with a "Tag in Notion" deep link (`notion_url`).
- **`components/distribution/PosterSelector.tsx`** — checkbox list of the 6 booked_by posters with page counts.
- **`components/distribution/NicheSelector.tsx`** — checkbox list of the 10 niches. Selecting niches filters sounds; selecting sounds auto-highlights their niches.
- **`components/distribution/PreviewPane.tsx`** — shows per-poster summary with matched sounds.
- **`components/distribution/MessagePreview.tsx`** — renders the exact Telegram message that will be sent (mirrors CPL's format from `routers/telegram.py:1425-1431`).
- **`components/distribution/SendHistory.tsx`** — slide-out panel (drawer component from shadcn/ui) listing past sends with status and drill-in.
- **`components/distribution/NicheManagement.tsx`** — separate dialog/modal for CRUD on niche tags and bulk creator tagging (the "page × niche checkbox matrix"). Accessible via a small "Manage niches" link in the header.

### 8.4 Niche management UI (the checkbox matrix)

When the user opens "Manage niches":

```
┌─────────────────────────────────────────────────────────────────────┐
│  Manage Niche Tags                                    [+ New niche] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                POV  TruckT  NatureT  Face  Anime  CountryL  Poetry  RelationS  Everything  │
│  @brew.pilled   ☐    ☐      ☐       ☑     ☐     ☐         ☐       ☐          ☑            │
│  @buck.wilders  ☑    ☐      ☑       ☐     ☐     ☐         ☑       ☑          ☐            │
│  @holy.fumble   ☐    ☐      ☐       ☐     ☑     ☐         ☐       ☐          ☐            │
│  ... 26 more                                                        │
│                                                                     │
│                                      [Cancel]  [Save changes]        │
└─────────────────────────────────────────────────────────────────────┘
```

- Rows: 29 internal creators (sorted by booked_by operator, then username).
- Columns: the 10 niches (minus "other" which is excluded from assignment by design).
- Save button fires one `PATCH /api/distribution/niches/<slug>/members` per niche with diffs.

### 8.5 React Query hooks

Add to `frontend/src/lib/queries.ts`:
- `useDistributionSounds()` → `GET /api/distribution/sounds`
- `useDistributionPosters()` → `GET /api/distribution/posters`
- `useDistributionNiches()` → `GET /api/distribution/niches`
- `useDistributionPreview(payload)` → `POST /api/distribution/preview` (manual trigger)
- `useDistributionSend(payload)` → `POST /api/distribution/send` (mutation)
- `useDistributionSends(limit)` → `GET /api/distribution/sends`
- `usePatchNicheMembers(slug, diff)` → `PATCH /api/distribution/niches/<slug>/members` (mutation)

---

## 9 · Seeding: creating the 10 niche groups

Run this one-time script against production CH:

```python
# scripts/seed_niche_groups.py
"""Seed the 10 Notion-matching niche groups in Campaign Hub.

Run once after deploy:
    python scripts/seed_niche_groups.py --base https://risingtides-campaign-hub-production.up.railway.app
"""
import argparse, sys, requests

NICHES = [
    # (slug, title, notion_tag_name)
    ("everything_welcome", "Everything Welcome", "Everything Welcome"),
    ("pov",                "POV",                "POV"),
    ("trucktok",           "Trucktok",           "Trucktok"),
    ("naturetok",          "NatureTok",          "NatureTok"),
    ("face_creators",      "Face Creators",      "Face Creators"),
    ("anime",              "Anime",              "Anime"),
    ("country_leaning",    "Country-Leaning",    "Country-Leaning"),
    ("relationship",       "Relationship",       "Relationship"),
    ("poetry",             "Poetry",             "Poetry"),
    # "other" is intentionally skipped — treated as untagged
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://risingtides-campaign-hub-production.up.railway.app")
    args = ap.parse_args()
    for idx, (slug, title, _) in enumerate(NICHES):
        r = requests.post(
            f"{args.base.rstrip('/')}/api/internal/groups",
            json={"slug": slug, "title": title, "kind": "niche", "sort_order": 100 + idx},
            timeout=30,
        )
        if r.status_code == 201:
            print(f"  + created {slug}")
        elif r.status_code == 409:
            print(f"  = {slug} already exists")
        else:
            print(f"  ! {slug} failed: {r.status_code} {r.text}", file=sys.stderr)

if __name__ == "__main__":
    main()
```

The `notion_tag_name` column is stored (future work: CH stores it in a new column on `InternalCreatorGroup` so the slug can diverge from Notion's human-readable tag). For v1, slug-from-title is enough since there's a clean 1:1.

---

## 10 · The Notion ↔ CPL ↔ CH lookup chain (worked example)

To make the flow concrete, here's what happens when the user clicks **Send** with 2 sounds selected for john-smathers + sam-hudgen:

1. **CH frontend** calls `POST /api/distribution/send` with
   `{sound_ids: ["a1b2c3d4e5f6", "f7e8d9c0b1a2"], poster_ids: ["john-smathers", "sam-hudgen"]}`.

2. **CH backend** writes a `DistributionSend` row with `status="pending"`.

3. **CH backend** calls CPL: `GET /api/telegram/sounds` → gets full sound list including labels and URLs (cached 60s).

4. For each sound, **CH backend** queries Notion (cached 5min) to fetch `Types of Content Creators`:
   - `a1b2c3d4e5f6` (label "Mon Rovia - Worship or Love") → `[POV, Relationship]`
   - `f7e8d9c0b1a2` (label "Ryan Beatty - Cinnamon Bread") → `[Anime]`

5. **CH backend** resolves niches to creators via its own DB:
   - niche `pov` → members: `[buck.wilders, johnsamuelsmathers, ...]`
   - niche `relationship` → members: `[buck.wilders, ...]`
   - niche `anime` → members: `[holy.fumble]`

6. **CH backend** pivots creators to posters via `booked_by` groups:
   - `buck.wilders` ∈ `sam_hudgens` → poster `sam-hudgen` gets Mon Rovia
   - `johnsamuelsmathers` ∈ `john_smathers` → poster `john-smathers` gets Mon Rovia
   - `holy.fumble` ∈ `johnny_balik` → poster `johnny-balik` gets Ryan Beatty
     - **But** `johnny-balik` wasn't in the user's `poster_ids` filter → skip.

7. Final per-poster plan:
   - `john-smathers` → `[a1b2c3d4e5f6]` (Mon Rovia only)
   - `sam-hudgen` → `[a1b2c3d4e5f6]` (Mon Rovia only)
   - Ryan Beatty goes nowhere this send because no selected poster has an anime-tagged creator.

8. **CH backend** makes 2 parallel calls to CPL:
   - `POST /api/telegram/sounds/forward-filtered` with `{poster_id: "john-smathers", sound_ids: ["a1b2c3d4e5f6"], ch_send_id: 42}`
   - `POST /api/telegram/sounds/forward-filtered` with `{poster_id: "sam-hudgen", sound_ids: ["a1b2c3d4e5f6"], ch_send_id: 42}`

9. **CPL** resolves each sound_id to its full sound record, formats the message (reusing existing format from `routers/telegram.py:1422-1438`), and calls Telegram `sendMessage` to the correct forum topic.

10. **CPL** returns per-call `{ok: true, sent: 1}`.

11. **CH backend** updates the `DistributionSend` row with `status="success"` and per-poster `results`. Returns the enriched response to the frontend.

12. **Frontend** shows a success toast and refreshes the send history.

**If Ryan Beatty had been tagged with a second content type that John or Sam had pages for, it would have been included for them too.** A single sound can fan out to multiple posters; a single poster can receive multiple sounds in one message (they're batched into one Telegram message per poster, matching the existing format).

---

## 11 · Phased implementation plan

Each phase is independently shippable. Total estimate: ~10 engineering days spread over ~2 calendar weeks with review cycles.

### Phase 0 — Prep (0.5 day)
- Create feature branch `feat/sound-distribution` in both repos.
- Add `DISTRIBUTION_SHARED_SECRET` env var to both Railway deployments (generate via `openssl rand -hex 32`).
- Confirm the 7 posters' `ch_booked_by_slug` mapping (see §12 for the open mapping question).

### Phase 1 — Campaign Hub: data + seed (1 day)
- Add `DistributionSend` model + Alembic migration.
- Add `scripts/seed_niche_groups.py`; run against prod to create the 10 niche groups.
- Add `scripts/backfill_niche_membership.py` (optional starter — reads `InternalCreator.niche` text and proposes group assignments for John to confirm in UI).

### Phase 2 — Campaign Hub: backend blueprint (2 days)
- Create `campaign_manager/blueprints/distribution.py`.
- Implement all 9 endpoints from §7.1.
- Implement the Notion lookup helper (`_fetch_notion_content_types(artist, song)`) with 5-min in-memory cache (module-level dict with TTL; no Redis needed for v1).
- Implement the CPL client module `campaign_manager/services/cpl.py` with shared-secret auth.
- Unit tests covering: the resolution chain (§10 step 4-7), untagged-sound warnings, idempotency key behavior.

### Phase 3 — content-posting-lab: new endpoint (0.5 day)
- Add `/api/telegram/sounds/forward-filtered` in `routers/telegram.py`.
- Add `require_distribution_token` FastAPI dependency.
- Deploy to Railway. Smoke-test via curl from John's laptop.

### Phase 4 — Campaign Hub: frontend shell (1.5 days)
- New route + sidebar entry.
- `Distribution.tsx` page shell with 4 sections (Sounds / Targets / Preview / Send).
- React Query hooks for sounds, posters, niches.
- Empty states and loading skeletons.

### Phase 5 — Frontend: sounds table + selector UX (1 day)
- `SoundsTable` with content-type badges and untagged warnings.
- `PosterSelector` and `NicheSelector` with bidirectional sync (picking niches updates sounds and vice versa).
- `MessagePreview` renders exact CPL format.

### Phase 6 — Frontend: niche management modal (1 day)
- `NicheManagement.tsx` checkbox matrix.
- Save diff as batched PATCH calls.
- Validation: can't delete a niche if it's referenced by a pending send.

### Phase 7 — Frontend: send history + polish (1 day)
- `SendHistory` drawer with status chips, per-poster drill-in.
- Toast notifications on send success/failure.
- Error handling for CPL timeouts (show which posters failed, allow retry per-poster).

### Phase 8 — E2E testing + docs (1 day)
- Tag all 29 internal creators via the matrix UI.
- Dry-run a distribution with a real active sound.
- Real send to a single poster first (probably John's own group) to confirm Telegram delivery.
- Full send to all 6 operators once validated.
- Update `CLAUDE.md` in both repos with the new integration.
- Update `docs/handoff.md`.

### Phase 9 — Nice-to-haves (deferred, not in v1)
- Scheduled sends (cron job at 9am daily).
- Slack notification when a send completes.
- "Sound assignment history" per creator profile page.
- Bulk import creator × niche from a CSV.
- Notion 2-way: push niche assignments *back* to Notion per creator (needs a creator DB in Notion first; likely out of scope).

---

## 12 · Open questions for John (must resolve before Phase 1)

1. **Poster slug mapping.** CPL uses `johnny-balik`, `sam-hudgen`, etc. CH uses `johnny_balik`, `sam_hudgens`. Are these the same person 1:1? We need a confirmed mapping:

   | CPL `poster_id` | CH `booked_by` slug | Same person? |
   |---|---|---|
   | seffra | (none) | Is Seffra's pages group in CH missing? |
   | gigi | (none) | Same question for Gigi |
   | johnny-balik | johnny_balik | ✅ assumed |
   | sam-hudgen | sam_hudgens | ⚠️ note the plural mismatch |
   | jake-balik | jake_balik | ✅ assumed |
   | eric-cromartie | eric_cromartie | ✅ assumed |
   | john-smathers | john_smathers | ✅ assumed |

   Resolution needed: either add Seffra and Gigi as CH `booked_by` groups (and assign their pages), or accept that those two posters won't be sendable from this tab.

2. **Username consistency.** CH's `InternalCreator.username` is a TikTok handle (e.g. `yellowfont.halfspeed`). CPL's `page_ids` are Postiz integration UUIDs. The mapping between the two lives... where? Currently nowhere. Possible approaches:
   - (a) CPL's page `name` field is the TikTok handle too — join on that.
   - (b) Add a `tiktok_handle` column to CPL's page roster.
   - (c) Since this feature *only sends to poster-level topics* (not per-page), we don't actually need the creator → integration_id mapping; we only need creator → booked_by group → poster_id. **That's the approach the PRD assumes.**

   Confirm (c) is acceptable.

3. **Who triggers sends?** For now, `triggered_by` is free-text set by the frontend (defaults to `"john"`). When user auth is added later, wire this up properly. OK for v1?

4. **Rate limits.** Telegram Bot API allows ~30 messages/sec globally. With 7 posters × 1 message each per send, we're nowhere near the limit. Confirm no need for rate-limiting in v1 beyond the existing 0.3s `asyncio.sleep` between posters in `/forward-all`.

5. **"Send" vs. "Schedule".** Feature is manual-trigger only in v1. Scheduled/cron sends are explicitly Phase 9 (nice-to-have). Confirm.

---

## 13 · Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Notion rate limits (3 req/sec per integration) | Low | Med | 5-min cache on content-type lookups; batch-fetch when possible. |
| CPL is down when CH tries to send | Med | High | CH writes `DistributionSend` row first, retries visible in history, graceful error UI. |
| Shared secret leaks | Low | High | Secret only in Railway env, never logged, rotatable by changing both services. |
| Operator receives wrong sound (bad niche tagging) | Med | Med | Dry-run preview is the primary defense. UI clearly labels which creators triggered inclusion. |
| Duplicate sends (user double-clicks) | High | Med | `idempotency_key` in `POST /send`; CH rejects duplicates within 60s window. |
| Niche groups get out of sync with Notion's tag vocabulary | Med | Low | Notion tags are rarely added. When a new tag appears in Notion, the next sound-sync will surface it as an untagged warning, prompting John to create the matching CH niche. |
| User deletes a `booked_by` group while pending sends reference it | Low | Low | FK constraints; sends already stored denormalized `poster_ids`. |
| `InternalCreator` rows get deleted out from under pending sends | Low | Low | Send history stores snapshotted `sound_labels` + `poster_ids`, not live references. |

---

## 14 · Success criteria

- John can open the Distribution tab, see today's active sounds with their content tags, and click Send to push each operator a tailored sound list in under 5 seconds.
- Operators (Johnny, Sam, Jake, Eric, John, Seeno) receive Telegram messages containing only sounds relevant to their pages' niches.
- 0 cases of a sound reaching a poster who shouldn't have received it.
- 0 cases of a sound failing to reach a poster who should have received it, given the current niche tagging.
- Send history shows a complete audit trail: what was sent, to whom, when, and whether it succeeded.
- Tagging all 29 internal creators with niches takes <20 minutes one-time via the matrix UI.
- Feature can be extended to scheduled sends (Phase 9) without schema changes.

---

## 15 · Appendix — key file locations (for the laptop session)

### Campaign Hub (this repo)
- Models: `campaign_manager/models.py` (add `DistributionSend` near line 486, after `InternalCreatorGroupMember`)
- DB helpers: `campaign_manager/db.py` (add `create_distribution_send`, `update_distribution_send`, `list_distribution_sends`)
- Existing group endpoints (reference for style): `campaign_manager/blueprints/internal.py:586-700`
- New blueprint: `campaign_manager/blueprints/distribution.py` (create)
- CPL client: `campaign_manager/services/cpl.py` (create)
- Notion client (reference from CPL): `/Users/risingtidesdev/dev/content-posting-lab/services/notion.py`
- Blueprint registration: `campaign_manager/__init__.py` (add `distribution_bp`)
- Frontend page: `frontend/src/pages/Distribution.tsx` (create)
- Frontend components: `frontend/src/components/distribution/` (create dir)
- API types: `frontend/src/lib/types.ts` (extend)
- API client: `frontend/src/lib/api.ts` (extend with distribution functions)
- React Query hooks: `frontend/src/lib/queries.ts` (extend)
- Sidebar: `frontend/src/components/layout/Sidebar.tsx` (add link)
- Seed script: `scripts/seed_niche_groups.py` (create)

### content-posting-lab (peer repo)
- Existing telegram router: `routers/telegram.py` (add `/sounds/forward-filtered` near line 1398)
- Shared-secret dependency: add to top of `routers/telegram.py` or new `routers/_auth.py`
- Telegram bot wrapper: existing at `services/telegram.py`
- Campaign Hub client (reverse direction, reference only): `services/campaign_hub.py`

### Production URLs
- Campaign Hub frontend: https://risingtides-campaign-hub.vercel.app
- Campaign Hub backend: https://risingtides-campaign-hub-production.up.railway.app
- content-posting-lab: (check `.env.example` in that repo for the Railway URL; `CAMPAIGN_HUB_URL` env var is hardcoded there but CPL's own URL needs to be discovered for CH → CPL calls)

### Notion
- CRM database ID: `1961465b-b829-80c9-a1b5-c4cb3284149a`
- Field to read: `Types of Content Creators` (multi_select, 10 options documented in §2.1)
- API token env var (existing): `NOTION_API_KEY`

---

## 16 · Appendix — PRD review checklist

Before merging this PRD:

- [ ] John confirms Decision 3.1 (CH as UI home) or overrides.
- [ ] John confirms Decision 3.2 (untagged → warn + exclude) or overrides.
- [ ] John confirms Decision 3.3 (manual tagging via matrix UI) or overrides.
- [ ] All §12 open questions have concrete answers.
- [ ] Shared secret rotation process documented (out of scope for PRD but needs a line in a runbook).
- [ ] Phase 0 env var set on both Railway deployments.
- [ ] content-posting-lab team (if it's anyone other than John) is aware of the new endpoint being added to their repo.

---

*End of PRD. When you pick this up in a fresh session: start by re-reading §2 (context), §5 (SoT split), and §12 (open questions). The implementation is §11 phase-by-phase.*
