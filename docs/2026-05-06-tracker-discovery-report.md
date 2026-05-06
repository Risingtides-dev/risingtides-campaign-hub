# Campaign ↔ Tracker Discovery Report

> **Date:** 2026-05-06
> **Method:** Sound-ID overlap between Campaign Hub campaigns and TidesTracker
>            promotions (via Cobrand share page `__NEXT_DATA__` parsing).
> **Source data:** 29 campaigns in active tab (booked + none completion status),
>                  42 trackers from TidesTracker API.

## Headline numbers

| | Count |
|---|---|
| Active campaigns total | 29 |
| Confidently matched to a tracker | 17 |
| Likely-but-different-sound | 1 |
| Truly unmatched (no Cobrand presence) | 11 |
| Orphan trackers (exist but unmatched) | 14 |

## ✓ 17 campaigns confidently matched (sound-ID overlap)

These work with the new sound-ID-based discovery — no manual linking needed.
Several have multiple trackers because of rounds (each round got its own
Cobrand promotion using the same sound).

| Campaign | Tracker(s) |
|---|---|
| alex_nicol_bridge_back_to_me_acoustic | INTERNAL ACCOUNTS · Warner Music Campaign |
| bebe_rexha_new_religion | Bebe Rehxa "New Religion" |
| bella_kay_nation_original_sound | Bella Kay (Official Audio) |
| bella_kay_promise_official_audio | Bella Kay "Promise?" (official audio) |
| bella_kay_promise_official_audio_r2 | Bella Kay "Promise?" (official audio) |
| blake_whiten_bet_on_that_r2 | Warner TEST Pages · Blake Whiten "Bet on that" Round 2 · Test Pages Official · Warner Music Campaign |
| daniel_seavey_love_a_gun | Daniel Seavey "Loves a Gun" |
| diplo_two_steppin_feat_adrien_nunez | Diplo (Two Steppin') |
| emei_night_at_the_opera | Night at the Opera |
| forrest_frank_grateful | Forrest Frank "Grateful" |
| gavinadcockmusic_original_sound | Gavin Adcock "Wannabe" · Blake Whiten "Bet on that" Round 1 |
| isaiah_rashad_boy_in_red | Isaiah Rashad "Boy in Red" |
| odhran_murphy_original_sound | Odhran Murphy "Wild Mountain Thyme" |
| patrickdroney_back_in_my_body | Back in my Body |
| sam_barber_run | Sam Barber "Run" (×3) · INTERNAL ACCOUNTS |
| shaboozey_born_to_die | Shaboozey "Born To Die" |
| stella_lefty_i_know_i_know_r2 | Stella Lefty "I know I know" (Round 2) (×2) |

## ⚠ 1 likely-but-different-sound

### stella_lefty_boston_bridge

- **Campaign sound ID:** `7635077615128202510`
- **Existing tracker "Stella Lefty Boston R3/4" sound ID:** `7613470504645823262`
- Same artist + song family, but DIFFERENT sound IDs (Stella re-uploaded as a new "original sound"). This is the exact problem you described earlier in this thread.

**Action options:**

a. **Add `7613470504645823262` to the campaign's `additional_sounds`** so it shares the existing tracker. Use this if the same Cobrand promotion is tracking both versions.

b. **Create a new Cobrand promotion + tracker for the bridge variant.** Use this if "Boston bridge" is a separately-tracked campaign with its own submission list.

## ✗ 11 unmatched campaigns — no Cobrand presence

These campaigns have no TidesTracker / Cobrand setup at all. Either they need
one created, or someone needs to confirm they're real and active.

| Campaign | Sound ID | Status |
|---|---|---|
| brady_toops_fire_signs | 7629745113966611726 | Needs tracker |
| forrest_nolan_thank_you_i_guess | (none — bigger gap) | Needs tracker AND sound ID |
| in_color_headlights | 7621699891886034198 | Needs tracker |
| kascade_meet_again | 7632457268606797840 | Needs tracker |
| liam_st_john_man_of_the_north | 7452409675745676062 | Needs tracker |
| limage_dig_me | 7626861582656391169 | Needs tracker |
| madonna_bring_your_love | 7632800862550837265 | Needs tracker |
| noah_kahan_doors | 7623187821775964942 | Needs tracker |
| noah_kahan_willing_and_able | 7631924550058936336 | Needs tracker |
| summer_davis_magazine | 7631378264985208833 (+ corrupted URL in additional_sounds) | Needs tracker AND data cleanup |
| tom_river_27000 | 7626677349124425729 | Needs tracker |

## · 14 orphan trackers — exist but no active campaign matches

These trackers have no active campaign in Campaign Hub. Most are tied to
campaigns marked "completed" (still showing in completed tab) or test/old
promotions. Worth auditing to see which still need attention.

| Tracker name | Sound ID(s) |
|---|---|
| Not For Radio "Ache" | 7628531698363287569 |
| Sexy Redd "Hang Wit a Bad Bitch" | 7603877131789994001, 7598459430170135310 |
| Dexter and The Moonrocks "Freakin' Out" | 7614254007799876382 |
| Matilda Lyn "Detach" | 7608338167406151697 |
| Alex Warren - Fine Place to Die | 7620736186185304080, 7628722598469225247 |
| Gregory Alan Isakov - Fade Into You | 7628975959558424577, 7618431193382455297 |
| Willow Avalon - Cardinal Sin Promo | 7622074966330723085 |
| Charlie Puth - Home | 7610269398359657246, 7614193861880203280 |
| (3 unnamed "Campaign" trackers) | various |
| (2 trackers with raw share URLs as names) | various |

## What this enables

With sound-ID-based discovery now in code:

1. **The cron's Cobrand cross-check** automatically queries the right tracker(s) for each campaign — no manual linking required for the 17 matched campaigns.
2. **Rounds work natively** — campaigns like `blake_whiten_bet_on_that_r2` (4 trackers) and `sam_barber_run` (4 trackers) get their tracked-URLs sets unioned across all related trackers.
3. **The Scrape Tasks tab** can surface the 11 unmatched campaigns as "needs Cobrand setup" so your team fills them in over time.
4. **The 14 orphan trackers** become visible in a "trackers without an active campaign" list — easy to identify cleanup candidates.

## Endpoints exposed

- `GET /api/scrape-tasks/tracker-discovery` — returns the full discovery report as JSON.
  The Scrape Tasks tab will use this to render the "matched / unmatched / orphan" sections.

## Followups

- Frontend: render the discovery report on the Scrape Tasks tab so your team sees the gaps
- Decide how to handle Stella Lefty Boston Bridge (option a or b above)
- Audit the 14 orphan trackers — if they're all completed, no action; if any are still active campaigns, link them up
- Clean up `summer_davis_magazine.additional_sounds` (has a video URL where a sound ID belongs)
- For the campaigns missing sound IDs entirely (forrest_nolan_thank_you_i_guess), determine the canonical sound ID
