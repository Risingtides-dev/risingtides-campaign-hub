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
- Add `campaigns.end_date_auto BOOLEAN DEFAULT FALSE` to distinguish an
  automatically stamped completion date from a manually entered date. Include
  it in the campaign detail `meta` object as `end_date_auto: false` by default
  and clear it with the date when reopening only if the date was stamped
  automatically; a manually entered date is retained. Re-finishing stamps a
  fresh automatic date.
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
  "end_date_auto": false,            // true when the end date was set by completion status
  "followup_days": 28,
  "followup_end": "2026-09-29",     // end_date + 28 days; "" when end_date is ""
  "phase": "live",                  // "not_started" | "live" | "followup" | "complete" | "no_start" | "finished_no_end"
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
    "lift_pct_followup": 78.6,      // (followup_daily - baseline_daily) / baseline_daily * 100 — the "rate of impact"
    "recounts": [],                 // {date, change, source}; source is auto|manual
    "unusual": []                   // {date, change, source}; counted unusual steps
  },
  "streams_history": [
    {"date": "2026-08-01", "total": 1000000, "daily": null},   // daily = total - previous total, divided by day gap; null for first point
    {"date": "2026-08-02", "total": 1005000, "daily": 5000}
  ],
  "followup_day": 8,                // only in follow-up; today - end_date, clamped 1..28
  "streams_error": null,            // present with user-facing text if streams fetch failed
  "ugc": {                          // same cumulative fields and semantics as streams
    "start_total": 100, "end_total": 140, "followup_total": 165,
    "gained_campaign": 40, "gained_followup": 25,
    "growth_pct_campaign": 40.0, "baseline_daily": 5.0,
    "campaign_daily": 14.3, "followup_daily": 8.9,
    "lift_pct_campaign": 185.7, "lift_pct_followup": 78.6,
    "recounts": [],                 // {date, change, source}; source is auto|manual
    "unusual": []                   // {date, change, source}; counted unusual steps
  },
  "ugc_history": [],                // adjusted daily history; block totals remain raw
  "ugc_error": null,                // present with user-facing text if UGC history fetch failed
  "data_as_of": "2026-09-28"        // latest reading across popularity, streams, and UGC
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
   start, end, follow-up end (only those that exist inside the plotted date range). Popularity = line (0–100 axis);
   daily streams = line/area of `daily`. Chart dates and tooltip labels use the
   same local calendar date basis; coincident campaign start/end uses one
   `Start/End` marker.
6. Footer: plain-language caveat "Shows what happened to the song around the
   campaign — not proof the campaign caused all of it." plus "Open Tides Tracker ↗"
   when the campaign has a `tracker_url`.
7. States: not linked (existing link form), loading, Chartmetric error (existing
   error treatment), linked but no end date (end values labelled "to date",
   follow-up values show "—" and the end-date setter is shown).

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

## Addendum 2026-09-29 (EC): the client story — five talking points, auto end date, "now" snapshot

Direction from EC after v1 review rounds:

1. **End date = the day the campaign is moved to Finished.** When `completion_status`
   changes to `"completed"` and the campaign has no `end_date`, the backend sets
   `end_date` to today. A manually set end date is never overwritten. Moving a campaign
   back out of Finished does not clear the date (use Clear on the card).
   Old campaigns that were finished before this existed have no end date: the card
   says "Finished · end date not set" and asks for one, instead of showing "Live".
2. **Snapshots: Start → End → +28 days → Now.** Every metric block also reports the
   latest reading (`now`) and its change since start and since end, so the story can be
   told at any later date.
3. **The three headline talking points** (in this order): Spotify popularity change;
   streaming growth rate; **UGC growth rate** — how many new TikTok videos were made
   to the song during the campaign. They complement the Tides numbers the page already
   shows in its stat cards (**total views** and **CPM**) — the card does not repeat those.
5. **Design stays subtle.** Supporting data, not the page's centrepiece: one muted
   headline line, a compact Start · End · +28 days · Now table, and the trend chart
   collapsed by default. Reuse the page's existing components and colors.
4. **UGC data source:** Chartmetric `GET /api/track/<cm_id>/tiktok/stats/most-history?type=posts&since=…`
   (verified live 2026-09-29: `obj[0].data[] = {timestp, value}`, `value` is the
   CUMULATIVE number of TikTok videos using the track, `track_domain_id` is null).
   Same rules as streams: raw readings for totals at dates, repeat runs smoothed only in
   the daily series, own error isolation (`ugc_error`), own to-date flags.

### Round 4 implementation contract updates

- Moving a campaign to Finished fills an empty end date with today's ISO date;
  existing manual dates are retained; reopening clears only an automatically
  stamped end date, and finishing again stamps a new date. Legacy finished
  campaigns without an end date use the `finished_no_end` phase.
- Streams and TikTok cumulative history share the same change-point daily
  calculation. A reading after a multi-day stall spreads the change over that
  interval; a trailing unchanged run has null daily values.
- Attribution blocks include the latest reading (`now`, `now_date`) and changes
  since start and end. The endpoint also returns campaign-scoped post event counts.
- The frontend presents a muted headline and compact Start / End / +28 days / Now
  table. Its trend chart is collapsed by default.

### Round 4 response JSON (authoritative shape)

`GET /api/campaign/<slug>/pop-score` retains all legacy top-level fields and adds
the following attribution payload. All numeric fields below can be `null` when
the reading/window is unavailable. Histories are arrays. `smoothed` is present
and `true` only on daily points spread across a multi-day change interval.

```json
{
  "linked": true,
  "link": "USUM72403305",
  "chartmetric_track_id": 118981138,
  "track": {"name": "Espresso", "artists": ["Sabrina Carpenter"], "image_url": "img"},
  "spotify_popularity": 69,
  "chartmetric_score": 99.3,
  "spotify_streams": 1700000,
  "baseline": 61,
  "change_since_start": 8,
  "start_date": "2026-08-01",
  "history": [{"date": "2026-08-01", "value": 61}, {"date": "2026-10-02", "value": 69}],
  "end_date": "2026-09-01",
  "followup_days": 28,
  "followup_end": "2026-09-29",
  "phase": "live",
  "popularity": {
    "start": 61, "end": 68, "end_is_to_date": false,
    "followup": 66, "followup_is_to_date": false,
    "now": 69, "now_date": "2026-10-02",
    "change_since_end": 1, "change_since_start": 8,
    "change_campaign": 7, "change_followup": -2
  },
  "streams": {
    "start": 1000000, "end": 1400000, "end_is_to_date": false,
    "followup": 1650000, "followup_is_to_date": false,
    "now": 1700000, "now_date": "2026-10-02",
    "change_since_end": 300000, "change_since_start": 700000,
    "start_total": 1000000, "end_total": 1400000,
    "followup_total": 1650000,
    "gained_campaign": 400000, "gained_followup": 250000,
    "growth_pct_campaign": 40.0,
    "baseline_daily": 5000.0, "campaign_daily": 14285.7,
    "followup_daily": 8928.6,
    "lift_pct_campaign": 185.7, "lift_pct_followup": 78.6
  },
  "ugc": {
    "start": 100, "end": 300, "end_is_to_date": false,
    "followup": 360, "followup_is_to_date": false,
    "now": 380, "now_date": "2026-10-02",
    "change_since_end": 80, "change_since_start": 280,
    "start_total": 100, "end_total": 300,
    "followup_total": 360,
    "gained_campaign": 200, "gained_followup": 60,
    "growth_pct_campaign": 200.0,
    "baseline_daily": 2.0, "campaign_daily": 7.1,
    "followup_daily": 2.1,
    "lift_pct_campaign": 255.0, "lift_pct_followup": 5.0
  },
  "streams_history": [
    {"date": "2026-08-01", "total": 1000000, "daily": null},
    {"date": "2026-08-02", "total": 1000000, "daily": null},
    {"date": "2026-08-04", "total": 1010000, "daily": 5000.0, "smoothed": true}
  ],
  "ugc_history": [
    {"date": "2026-08-01", "total": 100, "daily": null},
    {"date": "2026-08-02", "total": 107, "daily": 7.0}
  ],
  "followup_day": 8,
  "data_as_of": "2026-10-02",
  "post_events": [{"date": "2026-08-15", "count": 3}]
}
```

`streams_error` and `ugc_error` are omitted on success and included with
user-facing text when their respective request fails.

For cumulative `streams` and `ugc`, detection uses raw totals and never
popularity. Collapse every consecutive run of identical totals to one reading;
the next step spans from the last date in that run to the next distinct reading.
Displayed totals and histories retain raw readings. `step_rate` is absolute
change/gap days. Pace is the median of up to 14 prior collapsed step rates,
excluding recounts, after at least five prior steps, floored at 1/day. The
after-rate is the absolute change over the next three collapsed steps divided
by their combined days; all three are required. Floors are 10,000 UGC and
1,000,000 streams. With >=5 prior steps, recount iff step_rate >=50×pace,
after_rate < step_rate/40, and magnitude >= floor. Earlier steps recount iff
magnitude >= floor and >=10% of previous total, with three later steps and
after_rate < step_rate/40. Either sign qualifies. Non-recounts are unusual at
>=20× pace, or on an early step with magnitude >= floor. Listed recount and
unusual entries are `{date, change, source}` (`source`: `auto` or `manual`).
`post_events` remain available for the chart.

The `now` cumulative totals remain raw for display. `change_since_start`,
`change_since_end`, and campaign/follow-up deltas use the recount-adjusted
series consistently. A cumulative block sets `adjusted: true` when an
exclusion falls within the available history range from its first reading
through `now`; it is false in both `not_started` and `no_start` phases and when
no adjustment applies. A true flag means an exclusion affected adjusted
totals or rates; raw `now` and displayed raw totals remain unchanged.
This lets the UI footnote that displayed raw `now` and adjusted changes differ.

`popularity` uses `change_campaign` and `change_followup`; cumulative blocks
(`streams`, `ugc`) use `gained_campaign`, `gained_followup` and
`growth_pct_campaign`. All three blocks expose `start`, `end`, `followup`,
`now`, `now_date`, `change_since_start`, `change_since_end`,
`end_is_to_date`, and `followup_is_to_date`. The cumulative blocks additionally
expose totals, daily averages, and lift percentages shown above. `post_events`
counts only matched videos owned by the requested campaign, normalizes dates,
and is limited to the attribution history window. `finished_no_end` is returned
when completion status is completed and no effective end date exists.

## Addendum 2026-09-30 (lead): final recount approach — automatic default + manual override

After nine review passes it is clear that no automatic rule can perfectly tell a
Chartmetric recount from a real one-day jump. The design therefore is:

1. **Automatic default (rule v6)** — described in the recount section; it runs on
   stall-collapsed steps (repeated totals merged into one longer step) and uses a
   median per-day pace, so irregular Chartmetric update cadence can't erase growth.
   An opposite-sign adjacent glitch pair is additionally excluded when the first
   leg meets the 50× pace and metric floor gates, the leg magnitudes differ by at
   most `max(100, 5% of the first leg)`, and the next three collapsed steps have
   a combined absolute rate strictly below one-fortieth of the first-leg rate.
   The second leg must also meet the metric floor. Both legs are listed as
   recounts; the adjusted series applies each leg's own offset from its event
   date onward, preserving the pair's net change.
2. **Manual override per campaign.** Overrides constrain automatic classification before
   the rule runs: `include` steps cannot be recounts (including pair legs), and
   `exclude` steps are manual recounts excluded from pace. Automatic single and pair
   classification runs only over remaining steps, so a step appears in at most one list.
   A non-current override date is reported as `stale_overrides` and is not applied.
   Every step the rule flags (recount or unusual)
   is listed on the card with a small "Count it" / "Leave it out" action. The choice is
   stored on the campaign (`campaigns.attribution_overrides`, JSON:
   `{"streams": {"YYYY-MM-DD": "include"|"exclude"}, "ugc": {...}}`). Each listed step reports `source: "auto" | "manual"`.
   `POST /api/campaign/<slug>/pop-score/override {metric, date, action}` with
   action `include` | `exclude` | `auto` (auto removes the override). The endpoint
   locks the campaign row while updating the JSON so posts for separate dates persist.
3. **Now column** shows change since start AND since end.

## Addendum 2026-09-30 (round 13)

Manual attribution choices survive saving the same resolved Chartmetric track
again, including through an alternate link such as an ISRC. Changing to a
resolving track ID clears choices; unlinking clears them as well. For an
automatically detected rollback pair, including either leg accepts both raw
Chartmetric readings and counts both changes. The partner is shown as manually
counted with a cross-reference to the other date; excluding one leg remains a
single-leg decision. Stale choices show their date, metric, and saved decision,
with a pending reset disabled and reset failures reported beside the list.
Reference labels near the chart's right edge are anchored inward so their text
remains visible.
