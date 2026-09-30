# Chartmetric auto-link diagnosis and read-only acceptance

**Date:** 2026-09-30  
**Scope:** Fresh `GET https://campaignhub.risingtidesviral.com/api/campaigns` response, sorted by `start_date` descending. The endpoint returned HTTP 200 with 36 campaigns, so the acceptance pass covered all 36 (the newest ~40). Chartmetric resolution was read-only; no production links were written. The refresh token was used in memory only and was not recorded or printed.

## Before and after

| Snapshot | Campaigns | Outcome |
|---|---:|---|
| Previously documented snapshot from the old production URL | 40 | 5 reported already linked; 35 unlinked; resolver projected 23 links |
| Fresh production snapshot from the verified URL | 36 | 28 resolve to a uniquely credited track; 4 `not_released`; 3 `ambiguous`; 1 `no_song_info` |

The earlier 40-row snapshot is not the current production list. The fresh campaign-list response does not expose saved Chartmetric link fields, so the 28 are read-only resolver outcomes and cannot be described as persisted links. `Evergreen (Round 2)` now resolves to Chartmetric track `79459861`, “Evergreen (You Didn't Deserve Me At All)” by Omar Apollo. `Evergreen Rd 3` resolves to the same track in a direct read-only resolver check and is covered in tests; it is not in the latest 36-row response.

The fallback applies only when no exact title match exists and the campaign title, after round and feat cleanup, has no parenthetical. It accepts catalogue titles formed from the cleaned campaign title plus a parenthetical or dash subtitle. Version subtitles are excluded: remix, mix, edit, version, sped up, slowed, acoustic, live, instrumental, extended, radio edit, club mix, demo, cover, karaoke, reprise, remaster, and remastered. Campaign artist credit is still required. Different subtitle titles remain distinct songs and produce `ambiguous`.

## Prospective links for human review

| Campaign | Campaign song / artist | Chartmetric track / credited artists | ID | Method |
|---|---|---|---:|---|
| wynne_hold_my_purse | Hold My Purse / Wynne | Hold My Purse / Wynne | 173088069 | artist_tracks |
| britney_spears_i_m_a_slave_4_u_thunderpuss_club_mix | I'm a Slave 4 U (Thunderpuss Club Mix) / Britney Spears | I'm a Slave 4 U (Thunderpuss Club Mix) / Britney Spears | 15445278 | artist_tracks |
| dolly_babe_pink_blush_remix | Pink Blush (Remix) / Dolly Babe | Pink Blush (Remix) / Dolly Babe | 171358572 | artist_tracks |
| denise_julia_changes_round_2 | Changes (Round 2) / Denise Julia | CHANGES / Denise Julia | 166667682 | artist_tracks |
| britney_spears_i_m_a_slave_4_u | I'm a Slave 4 U / Britney Spears | I'm a Slave 4 U / Britney Spears | 15445265 | artist_tracks |
| quail_p_what_you_got_round_2 | What You Got (Round 2) / Quail P | What You Got / Quail P | 33746211 | artist_tracks |
| madonna_x_charli_xcx_danceteria_afterhours | Danceteria Afterhours / Madonna x Charli xcx | Danceteria Afterhours / Madonna, Charli xcx | 173110867 | artist_tracks |
| matroda_nights_with_you | Nights With You / Matroda | Nights With You / Matroda | 173119382 | artist_tracks |
| limage_unforgettable_feat_malikaa | Unforgettable (feat. Malikaa) / Limage | Unforgettable / Limage, MALIKAA | 172761361 | artist_tracks |
| bushbaby_danny_p_back_to_funk_round_3 | Back To Funk (Round 3) / Bushbaby & Danny P | Back To Funk / Bushbaby, Danny P | 170988722 | artist_tracks |
| armen_paul_hangman | Hangman / Armen Paul | Hangman / Armen Paul | 161168357 | artist_tracks |
| disco_dom_there_is_life | There Is Life / Disco Dom | There is Life / Disco Dom, Dombresky | 172702784 | artist_tracks |
| bebe_rexha_new_religion_r3 | New Religion R3 / Bebe Rexha | New Religion / Bebe Rexha, Faithless | 161194443 | artist_tracks |
| azkal_friend_of_a_friend | Friend of a Friend / AZKAL | Friend of a Friend / AZKAL | 171120247 | artist_tracks |
| depeche_mode_people_are_people | People Are People / Depeche Mode | People Are People / Depeche Mode | 12475859 | artist_tracks |
| gregory_alan_isakov_time_will_tell | Time Will Tell / Gregory Alan Isakov | Time Will Tell / Gregory Alan Isakov | 15184769 | artist_tracks |
| karol_g_drake_ahi_round_2 | Ahi (Round 2) / Karol G & Drake | Ahí / KAROL G, Drake | 171142088 | artist_tracks |
| denise_julia_changes | Changes / Denise Julia | CHANGES / Denise Julia | 166667682 | artist_tracks |
| julian_fijma_broken_love | Broken Love / Julian Fijma | Broken Love / Julian Fijma | 171834684 | artist_tracks |
| bollywoodro_dnd | DND / bollywoodro | DND / BollywoodRo | 165361141 | artist_tracks |
| ag_club_baby_boy_sum1else_mp3 | SUM1ELSE.MP3 / AG Club & Baby Boy | SUM1ELSE.mp3 / AG Club, Baby Boy | 171275808 | artist_tracks |
| monic_gone_astray_meant_to_be | Meant To Be / Monic, GONE ASTRAY | Meant To Be / Monic, GONE ASTRAY | 172233045 | artist_tracks |
| faouzia_unethical_round_2 | Unethical (Round 2) / Faouzia | UNETHICAL / Faouzia | 150902255 | artist_tracks |
| overtonight_coffin_rock | Coffin Rock / Overtonight | coffin rock / overtonight | 171955526 | artist_tracks |
| omar_apollo_evergreen_round_2 | Evergreen (Round 2) / Omar Apollo | Evergreen (You Didn't Deserve Me At All) / Omar Apollo | 79459861 | artist_tracks |
| yakiyn_talkin_fye | Talkin Fye / Yakiyn | Talkin Fye / Yakiyn | 171261120 | artist_tracks |
| johnny_balik_favorite_ghost | Favorite Ghost / Johnny Balik | Favorite Ghost / Johnny Balik | 172764503 | artist_tracks |
| original_sound | Need it Back / Johnny Balik | Need It Back / Johnny Balik | 171525137 | artist_tracks |

## All 36 campaigns

| # | Campaign | Campaign song / artist | Resolver outcome | Track ID / explanation |
|---:|---|---|---|---|
| 1 | wynne_hold_my_purse | Hold My Purse / Wynne | linked_auto | 173088069 |
| 2 | topic_follow_you_down | Follow You Down / Topic | not_released | Artist found; title absent from artist catalogue |
| 3 | akira_velez_i_don_t_wanna_wait | I don't wanna wait / Akira Velez | not_released | Artist found; title absent from artist catalogue |
| 4 | dexter_and_the_moonrocks_why_don_t_you_say_so | Why Don’t You Say So / Dexter and The Moonrocks | not_released | Artist found; title absent from artist catalogue |
| 5 | britney_spears_i_m_a_slave_4_u_thunderpuss_club_mix | I'm a Slave 4 U (Thunderpuss Club Mix) / Britney Spears | linked_auto | 15445278 |
| 6 | dolly_babe_pink_blush_remix | Pink Blush (Remix) / Dolly Babe | linked_auto | 171358572 |
| 7 | denise_julia_changes_round_2 | Changes (Round 2) / Denise Julia | linked_auto | 166667682 |
| 8 | britney_spears_i_m_a_slave_4_u | I'm a Slave 4 U / Britney Spears | linked_auto | 15445265 |
| 9 | quail_p_what_you_got_round_2 | What You Got (Round 2) / Quail P | linked_auto | 33746211 |
| 10 | sombr_my_body_isn_t_ready_string_section | My Body Isn't Ready (String Section) / Sombr | ambiguous | version not found in Chartmetric catalogue |
| 11 | madonna_x_charli_xcx_danceteria_afterhours | Danceteria Afterhours / Madonna x Charli xcx | linked_auto | 173110867 |
| 12 | matroda_nights_with_you | Nights With You / Matroda | linked_auto | 173119382 |
| 13 | victor_victor_presents_a_boogie_wit_da_hoodie |  /  | no_song_info | Song title is missing |
| 14 | pøpa_blk_mdna | BLK MDNA / PØPA | not_released | Artist found; title absent from artist catalogue |
| 15 | limage_unforgettable_feat_malikaa | Unforgettable (feat. Malikaa) / Limage | linked_auto | 172761361 |
| 16 | bushbaby_danny_p_back_to_funk_round_3 | Back To Funk (Round 3) / Bushbaby & Danny P | linked_auto | 170988722 |
| 17 | armen_paul_hangman | Hangman / Armen Paul | linked_auto | 161168357 |
| 18 | disco_dom_there_is_life | There Is Life / Disco Dom | linked_auto | 172702784 |
| 19 | bebe_rexha_new_religion_r3 | New Religion R3 / Bebe Rexha | linked_auto | 161194443 |
| 20 | azkal_friend_of_a_friend | Friend of a Friend / AZKAL | linked_auto | 171120247 |
| 21 | gregory_alan_isakov_sweet_heat_lightning_september | Sweet Heat Lightning (September) / Gregory Alan Isakov | ambiguous | version not found in Chartmetric catalogue |
| 22 | depeche_mode_people_are_people | People Are People / Depeche Mode | linked_auto | 12475859 |
| 23 | gregory_alan_isakov_time_will_tell | Time Will Tell / Gregory Alan Isakov | linked_auto | 15184769 |
| 24 | karol_g_drake_ahi_round_2 | Ahi (Round 2) / Karol G & Drake | linked_auto | 171142088 |
| 25 | denise_julia_changes | Changes / Denise Julia | linked_auto | 166667682 |
| 26 | julian_fijma_broken_love | Broken Love / Julian Fijma | linked_auto | 171834684 |
| 27 | bollywoodro_dnd | DND / bollywoodro | linked_auto | 165361141 |
| 28 | ag_club_baby_boy_sum1else_mp3 | SUM1ELSE.MP3 / AG Club & Baby Boy | linked_auto | 171275808 |
| 29 | monic_gone_astray_meant_to_be | Meant To Be / Monic, GONE ASTRAY | linked_auto | 172233045 |
| 30 | faouzia_unethical_round_2 | Unethical (Round 2) / Faouzia | linked_auto | 150902255 |
| 31 | overtonight_coffin_rock | Coffin Rock / Overtonight | linked_auto | 171955526 |
| 32 | romans_singularity_ballon | Singularity / Ballon / ROMANS | ambiguous | campaign lists more than one song |
| 33 | omar_apollo_evergreen_round_2 | Evergreen (Round 2) / Omar Apollo | linked_auto | 79459861; Evergreen (You Didn't Deserve Me At All) |
| 34 | yakiyn_talkin_fye | Talkin Fye / Yakiyn | linked_auto | 171261120 |
| 35 | johnny_balik_favorite_ghost | Favorite Ghost / Johnny Balik | linked_auto | 172764503 |
| 36 | original_sound | Need it Back / Johnny Balik | linked_auto | 171525137 |

The `/api/artist/<id>/tracks` catalogue reads and artist searches were performed without any campaign writes. Exact credited artist matching remains mandatory. Explicit campaign versions that cannot be found stay ambiguous; multi-song campaign titles remain ambiguous. The read-only resolver selected one track only when exactly one distinct song remained after grouping catalogue versions.
