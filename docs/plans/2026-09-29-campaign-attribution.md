# Campaign Attribution card (Spotify popularity + streams, before / during / after)

**Date:** 2026-09-29
**Builds on:** the Pop Score card (commit `1d50037`, Chartmetric integration).

## Goal

On every campaign's detail page, one internal box that tells the attribution
story for the campaign's song:

- Spotify popularity (0–100) at campaign start → campaign end → end of follow-up
- Spotify streams (cumulative total) at the same three points
- Percent growth of streams from start to end
- Follow-up period (default **28 days** after the campaign ends) so we can see
  whether the lift held — the "rate of impact"
- A daily chart with start / end / follow-up-end marked

The Tides Tracker stays the source for post-level social stats; this card links
out to it. This card is internal only — it must never appear on a share/public
view.

## Facts about the Chartmetric data (verified against the live API 2026-09-29)

- `GET /api/track/<cm_id>/spotify/stats/most-history?type=streams` returns
  `obj: [ {domain, track_domain_id, type, data: [{timestp: "YYYY-MM-DD", value: <int>}...]} ]`.
- **`value` is the CUMULATIVE total stream count, not daily streams.** Daily
  streams = difference between consecutive readings. Days can be missing, so
  never assume one reading per day.
- Without a `since` param the API returns only ~6 months. Pass
  `since=YYYY-MM-DD` (verified to work) for both `type=streams` and
  `type=popularity`, otherwise campaigns older than ~6 months lose their
  baseline. The existing `popularity_history()` does not pass `since` — fix it.
- Some readings carry extra keys (`monthly_diff`, ...). Ignore them.
- A song can have several Spotify IDs (series). Popularity selects the highest
  latest value among series whose latest reading is within 3 days of the newest
  series. Streams receives popularity's selected `track_domain_id` explicitly,
  then uses that same recency-tolerant rule. Raw cumulative readings are kept
  for campaign boundary totals. Daily history smooths an interior repeated
  run by spreading the total change from the reading before the run through
  the first changed reading; extra readings in a tail run have null daily.

## Data model

- New column `campaigns.end_date` — `String(20)`, default `""`, same format as
  `start_date` (`YYYY-MM-DD`). Add it to the model, both dict serialisers, the
  JSON-file storage path in `db.py` if it round-trips meta, and the self-heal
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` block next to the chartmetric columns.
- `POST /api/campaign/<slug>/edit` accepts `end_date`. Semantics: key absent →
  unchanged; `""` → cleared; otherwise must parse as `YYYY-MM-DD` and be on or
  after `start_date` (400 with a plain message if not).
  Full header saves may echo an unchanged legacy timestamp in `start_date`;
  format validation applies when that value changes. Date comparisons require
  valid dates when an end date is involved.
- Follow-up length is a module constant `FOLLOWUP_DAYS = 28` (not per campaign yet).

## API contract — `GET /api/campaign/<slug>/pop-score`

Existing fields stay exactly as they are (`linked`, `link`, `chartmetric_track_id`,
`track`, `spotify_popularity`, `chartmetric_score`, `spotify_streams`, `baseline`,
`change_since_start`, `start_date`, `history`). Add:

```jsonc
{
  "end_date": "2026-09-01",         // "" when not set
  "followup_days": 28,
  "followup_end": "2026-09-29",     // end_date + 28 days; "" when end_date is ""
  "phase": "live",                  // "not_started" | "live" | "followup" | "complete" | "no_start"
  "popularity": {
    "start": 61,                    // last reading on/before start_date
    "end": 68,                      // last reading on/before end_date; latest reading if end_date "" or in the future
    "end_is_to_date": false,        // true when "end" is the latest reading rather than a reading at end_date
    "followup": 66,                 // last reading on/before followup_end; latest if not reached. null when end_date "" or today <= end_date
  "followup_is_to_date": false,
    "change_campaign": 7,           // end - start (points), null if either null
    "change_followup": -2           // followup - end (points), null if either null
  },
  "streams": {
    "start_total": 1000000,
    "end_total": 1400000,
    "end_is_to_date": false,
    "followup_total": 1650000,
    "followup_is_to_date": false,
    "gained_campaign": 400000,      // end_total - start_total
    "gained_followup": 250000,      // followup_total - end_total
    "growth_pct_campaign": 40.0,    // (end_total - start_total) / start_total * 100; null if start_total null or 0
    "baseline_daily": 5000.0,       // avg daily streams over the 14 days before start_date
    "campaign_daily": 14285.7,      // avg daily streams start_date -> end (or -> latest)
    "followup_daily": 8928.6,       // avg daily streams end_date -> followup_end (or -> latest); null when no follow-up yet
    "lift_pct_campaign": 185.7,     // (campaign_daily - baseline_daily) / baseline_daily * 100; null if baseline null or 0
    "lift_pct_followup": 78.6       // (followup_daily - baseline_daily) / baseline_daily * 100 — the "rate of impact"
  },
  "streams_history": [
    {"date": "2026-08-01", "total": 1000000, "daily": null},   // daily = total - previous total, divided by day gap; null for first point
    {"date": "2026-08-02", "total": 1005000, "daily": 5000}
  ],
  "followup_day": 8,                // only in follow-up; today - end_date, clamped 1..28
  "streams_error": null,            // present with user-facing text if streams fetch failed
  "data_as_of": "2026-09-28"        // date of the latest reading across both series ("" if none)
}
```

### Calculation rules (put these in a pure, unit-tested module — no Flask, no HTTP)

- "Reading at date D" = last reading with `date <= D`. If none exists → `null`.
- Average daily streams over a window [A, B] = `(total_at(B) - total_at(A)) / (days between those two readings' dates)`.
  Use the dates of the readings actually found, not A and B, so gaps don't distort it.
  `null` if either reading is missing or they are the same day.
- Baseline window = `[start_date - 14 days, start_date]`; fetch history from
  `start_date - 21 days` so a last reading before the boundary can still anchor it.
- A negative daily delta (data correction) is reported as-is in `streams_history`
  but must not crash anything.
- `phase`: no start_date → `"no_start"`; today < start → `"not_started"`;
  no end_date or today <= end_date → `"live"`; today <= followup_end → `"followup"`; else `"complete"`.
- History fetch window: `since = start_date - 21 days`;
  fall back to today - 90 days when start_date is blank/invalid.
- Percent values rounded to 1 decimal; daily averages rounded to 1 decimal.
- `today` must be injectable in the pure module so tests are deterministic.
- `not_started` has null attribution values and deltas. `*_is_to_date` follows
  the latest available reading date (`data_as_of`) relative to the target date.
- A failed streams history request preserves popularity and returns
  `streams_history: []` plus `streams_error`.

## UI — evolve `PopScoreCard` into the attribution card

Keep the component file and the track-link form. Card title: **"Song attribution"**.

1. Header row: track art + name + artists (as today), phase badge
   (`Live` / `Follow-up (day N of 28)` / `Complete` / `Not started`), "Data as of <date>".
2. Dates row: `Start <date> → End <date or "not set" + inline date input to set it> → Follow-up ends <date>`.
   Setting the end date calls the existing campaign edit endpoint with `{end_date}`
   and refreshes the campaign + pop-score queries.
   The campaign header refreshes its edit fields whenever Edit opens and only
   sends `end_date` when that field changed in the current edit session; failed
   saves leave the form open and display the error.
3. Two metric rows, each with three cells (Start / End / Follow-up) and change chips:
   - **Popularity** — values 0–100, change in points (`+7 pts`).
   - **Streams** — cumulative totals in compact form (`1.4M`), gained counts, and
     `Growth during campaign: +40.0%`.
   Values marked `*_is_to_date` show a small "to date" label. Missing values show "—",
   never 0. Percentages that are null show "N/A".
4. **Impact** row: `Avg daily streams — before 5.0K · during 14.3K (+185.7%) · after 8.9K (+78.6% vs before)`.
5. Chart with a toggle `Popularity | Daily streams`. Vertical reference lines at
   start, end, follow-up end (only those that exist). Popularity = line (0–100 axis);
   daily streams = line/area of `daily`. Chart dates and tooltip labels use the
   same local calendar date basis; coincident campaign start/end uses one
   `Start/End` marker.
6. Footer: plain-language caveat "Shows what happened to the song around the
   campaign — not proof the campaign caused all of it." plus "Open Tides Tracker ↗"
   when the campaign has a `tracker_url`.
7. States: not linked (existing link form), loading, Chartmetric error (existing
   error treatment), linked but no end date (end values labelled "to date",
   follow-up cells show "Set an end date").

Styling: match the existing card (same tokens, `ACCENT`, spacing). Mobile: rows
stack; the chart stays full width.

## Out of scope for v1

- Storing daily snapshots in Postgres (Chartmetric keeps history; 1h cache is enough).
- A cross-campaign attribution leaderboard.
- Per-campaign follow-up length.
- Multiple songs per campaign.

## Ops note

Requires `CHARTMETRIC_REFRESH_TOKEN` on Railway (already required by the Pop Score
card). The token pasted in chat on 2026-09-29 must be treated as exposed and rotated
by the operator; it is not stored in this repo.
