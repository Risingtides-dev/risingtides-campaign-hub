# Original Sound Matching Fix

> **Date:** 2026-05-06
> **Status:** Plan approved, ready to implement
> **Branch:** `claude/fix-fuzzy-matching-scraping-TMM9R`
> **Files:** `campaign_manager/services/matching.py`, `campaign_manager/services/scheduler.py`

## Problem

Two compounding bugs in `campaign_manager/services/matching.py` make the "original sound" branch of fuzzy matching dead code in production. Originals are the case where a creator records audio over a campaign song instead of using the official sound — these get a brand-new TikTok `sound_id` and are labeled as "original sound - <creator_handle>" by the creator, not the artist.

### Bug 1: artist gate kills `discover_original_sounds`

`matching.py:178`:

```python
if is_orig and vid_artist in artist_variants and vid_music_id and vid_music_id not in sound_ids:
```

For an original sound post, yt-dlp returns:

- `song` = `"original sound - <creator_handle>"`
- `artist` = the creator's display name

So `vid_artist` is never the campaign artist (or `tt_artist_label`) — it's the creator. The artist gate is the wrong filter for the case the function is named after. The `creator_set` filter on line 170 is the actual safety check; the artist gate is over-restrictive and nullifies the function.

The same gate appears in `match_videos` strategy 2 (`matching.py:124`), but that branch wouldn't fire for originals anyway because `core_song_words` has no overlap with `"original sound - handle"`.

### Bug 2: English-only "original sound" prefix

`matching.py:176`:

```python
is_orig = video.get("is_original_sound", False) or vid_song.startswith("original sound")
```

`is_original_sound` is only set by the Apify scraper (`apify_scraper.py:62`); yt-dlp never sets it, so the cron path (which uses `master_tracker.py`) collapses to the English prefix. TikTok localizes this label by region, so creators outside English markets show up as `"sonido original"`, `"suono originale"`, `"audio originale"`, `"som original"`, `"origineel geluid"`, `"son original"`, etc. The legacy code in `scrape_external_accounts_cached.py:399-505` handled these locales explicitly — that handling was lost in the refactor into the shared matching module.

### Prior partial fix

Commit `c0d36a4` ("use tt_artist_label for original sound matching") added `tt_artist_label` / `tt_track_name` campaign fields and threaded them through `build_sound_sets` / `match_videos` / `discover_original_sounds`. This helps when TikTok labels the artist differently from the campaign's "real" artist (e.g. "Music for the Soul" vs. "Sam Barber"), but it doesn't help the original-sound case at all — for originals, the artist label is the creator, never the artist or any label variant.

## Fix

### 1. `discover_original_sounds`: drop the artist gate

Remove `vid_artist in artist_variants` from the matching condition. Trust the existing safeguards:

- `vid_account in creator_set` — only videos from this campaign's booked creators
- `is_orig` — must look like an original sound
- `vid_music_id and vid_music_id not in sound_ids` — must be a sound we don't already track
- Campaign `start_date` filter applied upstream in `_filter_by_date`

Together these are sufficient: a tracked creator posting an original sound in the campaign window with a new sound_id is the exact pattern we want to discover. The artist gate was a redundant filter that never fires for the case the function exists to solve.

### 2. Locale-aware "original sound" detection

Replace the bare `startswith("original sound")` with a tuple of locale variants matching the legacy list:

```python
ORIGINAL_SOUND_PREFIXES = (
    "original sound",
    "sonido original",
    "audio original",
    "suono originale",
    "audio originale",
    "som original",
    "origineel geluid",
    "son original",
)
```

Use `any(vid_song.startswith(p) for p in ORIGINAL_SOUND_PREFIXES)`. Module-level constant so both `discover_original_sounds` and any future caller share the list.

### 3. Conservative auto-add to `additional_sounds`

`scheduler._refresh_single_campaign` (lines 401-408) currently auto-appends every discovered sound_id to the campaign's `additional_sounds` and re-saves the campaign. With the artist gate removed this becomes more permissive, so we add a small safeguard: only auto-add when **at least one** matched video for the discovered sound came from a tracked creator (which is already guaranteed by `discover_original_sounds`'s creator-set filter, so the existing flow is fine — no extra logic needed, but worth confirming during implementation).

We do **not** add a separate "review queue" flag. The campaign-window + tracked-creator scoping is tight enough that false positives should be rare, and Jake can manually remove a bad sound_id from `additional_sounds` via the existing campaign edit UI if one slips through.

## Tradeoff

**Coverage win:** Discovery now actually fires for originals (currently it never does in practice). Locale-broken originals from non-English creators are caught.

**Risk:** A tracked creator posting unrelated original-sound content during the campaign window would auto-attach that sound_id to the campaign. Mitigated by:

- `start_date` filter (creators only count from campaign launch)
- Booked creators are paid per campaign and unlikely to spam unrelated originals in window
- Visible in campaign UI; Jake can remove

The legacy code's per-campaign hardcoded artist-substring rules (e.g. `'kami kehoe' in video_artist_lower`) achieved tighter precision but at the cost of every new campaign needing code changes. We're trading that brittleness for a generic rule that works without code changes.

## Implementation Steps

1. Add `ORIGINAL_SOUND_PREFIXES` constant at module top of `matching.py`
2. Update `discover_original_sounds`:
   - Replace `is_orig` line with the locale-aware check
   - Remove `vid_artist in artist_variants` from the gating condition
   - Keep `artist_variants` build for now (still used for logging / future signal)
3. (Optional cleanup) Remove now-unused `artist_variants` if nothing else references it
4. Verify `match_videos` strategy 2 still gates on artist — it should, since it's for *non*-original fuzzy matching where the artist label is meaningful
5. Manual smoke test: pick one campaign known to have original-sound posts, run `trigger_job("campaign_refresh")` locally or in staging, confirm new matches surface

## Out of Scope

- Apify scraper path (`apify_scraper.py`) — already sets `is_original_sound` reliably
- New DB columns / review queue UI
- Backfilling missed historical originals (cron will pick them up on next run since `creator_set` and `start_date` apply retroactively)
- Changing fuzzy strategy 2 in `match_videos` (irrelevant for originals)
