# Song attribution card — closing report

**Branch:** `feat/campaign-attribution` · **Closed:** 2026-09-30 · **Contract:** `docs/plans/2026-09-29-campaign-attribution.md`

## What was asked (EC) and where it stands

| Ask | Verdict | Evidence |
|---|---|---|
| Spotify popularity from campaign start to end | MET | Snapshot table row + headline "Popularity 88 → 88" |
| Streaming data and rate of growth | MET | Daily streams before → during → after, lift %, "+1.4% growth" |
| Percent growth of streams start → end | MET | `growth_pct_campaign` = recount-adjusted gain ÷ reported Start total |
| TikTok UGC growth (new videos made to the song during the campaign) | MET | Chartmetric TikTok posts series; "35.3K new during the campaign" |
| A few weeks after: rate of impact | MET | +28-day follow-up column; "→ 1.3M after (−18.2% vs before)" |
| End date = the day the campaign moves to Finished | MET | Stamped on Finish (Eastern time), cleared on reopen, manual dates kept |
| Snapshot of where it is now | MET | "Now" column, change since start and since end |
| Complements total views / CPM, doesn't repeat them | MET | Card never shows them; the page's stat cards still do |
| Subtle design, Mon Rovîa as reference | MET | Muted headline line, compact table, trend chart collapsed by default |
| Each campaign pulls only its own song's data (active and finished) | MET | Per-campaign track id and overrides; two-campaign isolation tests; live check |

## Defects column — clean twice

19 adversarial review passes. Every pass after the first used two independent reviewers on different models (Claude agents and Codex). Every fix round was re-gated by the lead and red-proven: each fix has a test that fails by assertion when the fix is reverted. The last two passes (18 and 19) found **no regressions**. Codex's last three full-feature reviews (passes 17–19) found no behaviour defects.

What the passes caught and fixed, in short:
- Setting an end date wiped a campaign's extra sounds and Cobrand link (partial edits now change only the fields sent).
- The header edit form and the card overwrote each other's end date.
- Background scrape and manual refresh could undo Finish or an end date (they now save only the fields they own).
- Chartmetric repeats yesterday's total on quiet days and sometimes restates the total by hundreds of thousands. Early rules either counted those restatements as campaign growth or threw away real growth on small songs. This went through six versions. It ends as a per-day rule that is safe for small songs, plus a **manual per-campaign override**, because no automatic rule can always tell a restatement from a real one-day jump.
- Charts: bars vanished when markers were present, tooltips showed raw timestamps, and labels were clipped.
- Growth % used the wrong starting figure after a pre-campaign restatement.
- Re-saving the same song link, or saving during a Chartmetric outage, could wipe the team's choices.

## Banked (known, documented, not fixed)

- **Recount heuristic tuning constants** (pace floor, window length ±1, pair tolerance floor, post-window length) have mutants the suite does not kill. The product invariants are pinned by scenario tests: small songs never lose real growth, large one-off restatements are excluded, a team override always wins, and campaigns are isolated. Any single call can be corrected on the card.
- **Headline "(to date)" wording.** It is chosen by phase: in the follow-up phase the campaign-window figures are final but still say "(to date)", and the "vs before" follow-up figure has no "to date" marker. Wording only.
- **Change chips** in the table use a plain hyphen for negatives while percentages use "−".
- **Test gaps with correct behaviour today:** the streams follow-up lift % value, the streams null follow-up guard, the streams growth "*".
- **Pre-existing, outside this feature:** `test_services_matching.py::TestBuildSoundSets::test_sound_keys_include_tt_labels_when_set` fails on `main` too. 9 ESLint errors in files this branch does not touch.
- **Chartmetric rate limit** is per gunicorn worker (4 workers). A card makes 4 calls under a 75-second budget. Fine at today's volume.

## Go-live checklist

1. **Rotate the Chartmetric refresh token that was pasted in chat on 2026-09-29.** Production uses a *different* token (verified by hash), so prod is not exposed, but the pasted one should be revoked in Chartmetric.
2. `CHARTMETRIC_REFRESH_TOKEN` is already set on Railway. Nothing else to set.
3. Schema: three columns (`end_date`, `end_date_auto`, `attribution_overrides`) are added automatically on boot by the existing self-heal. Expand-only: the old revision never reads them, so a rolling deploy is safe. On boot it also runs an idempotent `UPDATE … SET end_date_auto = FALSE WHERE end_date_auto IS NULL`.
4. **Existing finished campaigns have no end date.** Their card says "Finished · end date not set" with a date picker. Someone should backfill the real finish dates for campaigns the team will show clients.
5. Each campaign needs its song linked (Spotify link, Chartmetric link or ISRC) for the card to show anything. This is unchanged from the Pop Score card.
6. **Soak: 48 hours after deploy.** Watch Railway logs for `pop-score` 502s and `Chartmetric` errors. Rollback if the campaign detail page fails to load. Hotfix if only the card errors. Owner: whoever merges.

## Deliberate non-goals

- No stored daily snapshots: Chartmetric keeps the history, and responses are cached for 1 hour.
- No cross-campaign attribution leaderboard.
- No per-campaign follow-up length (fixed at 28 days).
- One song per campaign.
- Card is internal only: it is not on the client share view.

## Mainline

The branch is merged up to date with `origin/main` (includes #230). It is **not merged to main**, because merging deploys to production on Railway, and production deploys are operator-gated. It goes out as a PR for EC to merge.
