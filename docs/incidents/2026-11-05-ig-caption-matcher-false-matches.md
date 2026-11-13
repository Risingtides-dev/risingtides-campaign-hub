# Handoff → risingtides-campaign-hub agent
## Instagram caption matcher claims a creator's entire feed (49 false rows/day)

**Date:** 2026-11-05 · **Reported by:** the scraper/Cobrand pipeline (separate repo)
**Severity:** high — produces false `matched_videos` rows daily, inflates delivery
counts, and nearly caused 53 unrelated reels to be pasted into a client's Cobrand
promotion.

---

## Symptom

`@theelliebarker` has **91 `matched_videos` rows** on campaign
`kygo_x_ava_max_before_you_know_it`. Every one is an Instagram reel on a
**different** audio — 49 currently-undismissed rows, each with its own unique
`music_id` (`26772088272488802`, `28537405102603859`, … 49 distinct values).

The campaign registers exactly two sounds:
- `sound_id = 7694776132743399425` (TikTok)
- `additional_sounds = ['4570677819866675']` (the Instagram audio)

**None** of the 49 rows carry either id.

42 of these rows were manually dismissed on 2026-11-04. The scraper re-created
49 more within 24 hours, so dismissal is not a durable fix.

Also affected on the same campaign: `@life.content1` × 4 rows.

## Scope

Only Instagram-booked creators are affected, and currently only this one
campaign. Query used to establish that (run against the Hub DB):

```sql
-- IG rows on an unregistered sound, per campaign/creator
SELECT ca.slug, mv.account, count(*)
FROM matched_videos mv JOIN campaigns ca ON ca.id = mv.campaign_id
WHERE mv.platform = 'instagram' AND mv.dismissed_at IS NULL
  AND (ca.completion_status IS NULL OR ca.completion_status <> 'completed')
GROUP BY 1, 2;
```
Result 2026-11-05: **57 IG rows on a registered sound, 53 on an unregistered
one** — the 53 being 49 × `@theelliebarker` + 4 × `@life.content1`, all Kygo.

## Root cause — `match_video_to_sounds` Strategy 5

`src/scrapers/master_tracker.py:740-770`, the Instagram caption fallback:

```python
song_match = any(word in caption_lower for word in song_words if len(word) > 2)
...
if song_match and (artist_match or len(song_words) >= 3):
    return True
if len(song_words) >= 3 and song_match:
    return True
```

Two independent problems compound:

1. **`any(word in caption)` is a substring test over single words.** For song
   `"Before You Know It"` the qualifying words are `before`, `you`, `know`.
   Virtually every English caption contains one.
2. **`len(song_words) >= 3` waives the artist check entirely.** With a 4-word
   title, `song_match` alone returns True — the artist is never consulted, and
   **the audio is never consulted at all.**

So for any campaign whose song title has ≥3 words, Strategy 5 matches *every
reel an IG-booked creator posts*, regardless of what audio it uses.

This also explains why `drunk_hold_my_purse` (9 IG creators, song `"Drunk"`) is
clean: a 1-word title still requires `artist_match`.

Reaching Strategy 5 at all requires `match_strategy = 'fuzzy'`; Kygo is `fuzzy`.
Strategies 1-4 correctly reject these rows.

## Suggested fix (your call on the shape)

The pipeline's need is simply that **an Instagram row must be justified by the
campaign's registered audio**, the same bar the TikTok path meets. Options, in
the order we'd favour them:

1. **Require the audio id.** Drop Strategy 5, or gate it behind
   `video['music_id'] in sound_ids`. The Hub already stores IG audio ids
   (`apify_instagram.py:124-133` maps `music.audio_id` into both `music_id` and
   `extracted_sound_id`), and Kygo already has its IG audio registered in
   `additional_sounds` — so Strategy 1 alone matches the genuine reels. This is
   the option we'd pick.
2. If caption matching must stay as a safety net for campaigns whose IG audio
   is unknown: require **both** `song_match` and `artist_match` (delete the
   `len(song_words) >= 3` waiver in both branches), and make `song_match` the
   full-title substring test rather than `any(word)`.

Either way the caption path should set a distinguishable
`match_strategy` value (e.g. `ig_caption`) so these rows are greppable; right
now they are indistinguishable from `music_id_or_song_key` matches after the
fact, which is why this went unnoticed.

## Verification

- `tests/backend/test_services_matching.py` and `tests/backend/test_apify_instagram.py`
  are the existing suites.
- A regression test worth adding: a reel with caption
  `"you know i had to do it"` and `music_id = '99999'` must **not** match a
  campaign whose song is `"Before You Know It"` with
  `sound_ids = {'7694776132743399425', '4570677819866675'}`.
- After the fix, re-run the scope query above; the expected result is
  **0 IG rows on an unregistered sound**.

## Cleanup needed after the fix

The 53 existing bad rows need dismissing (or deleting). Dismissing before the
code fix is pointless — they regenerate. `creators.posts_matched` for
`@theelliebarker` on this campaign will also need recomputing; it was manually
corrected to 0 on 2026-11-04 and has since drifted again.

## What the downstream pipeline has done meanwhile

`scripts/ig_gap_check.py` (scraper repo, morning Step 0.695) was reporting these
rows under *"N Instagram posts never reached Cobrand — recoverable, paste them"*.
It now filters `dismissed_at IS NULL` and excludes rows whose `music_id` is not
one of the campaign's registered sounds, reporting those separately as
*"do NOT paste"*. That stops the bad advice but does not stop the bad rows.
