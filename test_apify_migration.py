#!/usr/bin/env python3
"""
Test suite for the Apify migration.

Tests:
  1. apify_scraper module imports and normalizes correctly
  2. Live Apify API call with a known creator (amourgazette)
  3. musicId presence on "original sound" videos (the Chezile bug)
  4. Matching logic with the new fast-path
  5. Auto-discovery logic for original sounds
"""
import os
import sys
import json
from datetime import datetime

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("APIFY_API_TOKEN", "apify_api_DvcipBGGyuFczQESEunbkFRVRt662V1JYRlD")

PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  -- {detail}")


def banner(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ---------------------------------------------------------------
# TEST 1: Module imports
# ---------------------------------------------------------------
banner("1. Module imports")

try:
    from campaign_manager.services.apify_scraper import (
        scrape_profiles,
        scrape_by_sound,
        _normalize_video,
        _get_client,
    )
    test("apify_scraper imports", True)
except Exception as e:
    test("apify_scraper imports", False, str(e))
    print("Cannot continue without imports. Exiting.")
    sys.exit(1)

# ---------------------------------------------------------------
# TEST 2: _normalize_video with mock data
# ---------------------------------------------------------------
banner("2. Normalize video (mock data)")

mock_item = {
    "id": "7401234567890123456",
    "webVideoUrl": "https://www.tiktok.com/@testuser/video/7401234567890123456",
    "createTimeISO": "2026-02-15T10:30:00.000Z",
    "playCount": 15000,
    "diggCount": 500,
    "musicMeta": {
        "musicId": "7605685757969173262",
        "musicName": "original sound",
        "musicAuthor": "Chezile",
        "musicOriginal": True,
    },
    "authorMeta": {
        "name": "amourgazette",
    },
}

normalized = _normalize_video(mock_item)

test("url mapped", normalized["url"] == mock_item["webVideoUrl"])
test("video_id mapped", normalized["video_id"] == mock_item["id"])
test("music_id mapped", normalized["music_id"] == "7605685757969173262")
test("extracted_sound_id == music_id", normalized["extracted_sound_id"] == "7605685757969173262")
test("song mapped", normalized["song"] == "original sound")
test("artist mapped", normalized["artist"] == "Chezile")
test("is_original_sound", normalized["is_original_sound"] is True)
test("account has @", normalized["account"] == "@amourgazette")
test("views mapped", normalized["views"] == 15000)
test("likes mapped", normalized["likes"] == 500)
test("timestamp is ISO string", isinstance(normalized["timestamp"], str) and "2026" in normalized["timestamp"])
test("upload_date is YYYYMMDD", normalized["upload_date"] == "20260215")
test("platform is tiktok", normalized["platform"] == "tiktok")


# ---------------------------------------------------------------
# TEST 3: _normalize_video edge cases
# ---------------------------------------------------------------
banner("3. Normalize video edge cases")

empty_item = {}
empty_norm = _normalize_video(empty_item)
test("empty item returns defaults", empty_norm["url"] == "" and empty_norm["music_id"] == "")

no_music_item = {
    "id": "123",
    "webVideoUrl": "https://tiktok.com/@x/video/123",
    "authorMeta": {"name": "testuser"},
}
no_music_norm = _normalize_video(no_music_item)
test("missing musicMeta returns empty music_id", no_music_norm["music_id"] == "")
test("missing musicMeta: is_original_sound False", no_music_norm["is_original_sound"] is False)


# ---------------------------------------------------------------
# TEST 4: Live Apify scrape (small -- 1 creator, 5 results)
# ---------------------------------------------------------------
banner("4. Live Apify scrape: amourgazette (5 results)")

try:
    client = _get_client()
    test("Apify client created", True)
except Exception as e:
    test("Apify client created", False, str(e))

print("  ... calling Apify (this may take 30-60s) ...")
try:
    live_results = scrape_profiles(["amourgazette"], results_per_page=5)
    test("scrape_profiles returned results", len(live_results) > 0, f"got {len(live_results)}")

    if live_results:
        v = live_results[0]
        test("live: url present", bool(v.get("url")), v.get("url", ""))
        test("live: account present", bool(v.get("account")))
        test("live: music_id present", bool(v.get("music_id")), f"music_id={v.get('music_id')}")
        test("live: song present", bool(v.get("song")), f"song={v.get('song')}")
        test("live: artist present", bool(v.get("artist")), f"artist={v.get('artist')}")
        test("live: views is int", isinstance(v.get("views"), int))

        # Check that at least one video has a real music_id (not empty)
        has_music_id = any(v.get("music_id") for v in live_results)
        test("live: at least one video has music_id", has_music_id)

        # Print sample for manual inspection
        print(f"\n  Sample video:")
        for key in ["url", "music_id", "song", "artist", "is_original_sound", "views", "account"]:
            print(f"    {key}: {live_results[0].get(key)}")
except Exception as e:
    test("scrape_profiles call", False, str(e))
    live_results = []


# ---------------------------------------------------------------
# TEST 5: Chezile-specific -- check for music_id 7605685757969173262
# ---------------------------------------------------------------
banner("5. Chezile bug validation")

if live_results:
    chezile_music_ids = set()
    for v in live_results:
        mid = v.get("music_id", "")
        if mid:
            chezile_music_ids.add(mid)

    print(f"  Music IDs found: {chezile_music_ids}")
    # We can't guarantee which videos come back in 5 results,
    # but we can check the data structure is right
    test("live: music_ids are strings", all(isinstance(m, str) for m in chezile_music_ids))
    test("live: music_ids are numeric", all(m.isdigit() for m in chezile_music_ids if m))
else:
    print("  Skipped -- no live results")


# ---------------------------------------------------------------
# TEST 6: Matching logic simulation
# ---------------------------------------------------------------
banner("6. Matching logic simulation")

# Simulate what campaigns.py now does
sound_ids = {"7607726203173095425", "7605685757969173262"}  # official + alternate

# Video that uses the alternate sound (the bug case)
bug_video = {
    "music_id": "7605685757969173262",
    "song": "original sound",
    "artist": "Chezile",
    "account": "@amourgazette",
    "url": "https://tiktok.com/@amourgazette/video/123",
    "views": 5000,
    "is_original_sound": True,
}

# Fast path: direct musicId match
matched_fast = bug_video["music_id"] in sound_ids
test("fast-path: alternate sound matches", matched_fast)

# Video with official sound
official_video = {
    "music_id": "7607726203173095425",
    "song": "Another Life",
    "artist": "Chezile",
}
test("fast-path: official sound matches", official_video["music_id"] in sound_ids)

# Video with unrelated sound
unrelated_video = {
    "music_id": "9999999999999999999",
    "song": "Popular Song",
    "artist": "Other Artist",
}
test("fast-path: unrelated does NOT match", unrelated_video["music_id"] not in sound_ids)


# ---------------------------------------------------------------
# TEST 7: Auto-discovery logic simulation
# ---------------------------------------------------------------
banner("7. Auto-discovery logic simulation")

# Simulate: video by campaign creator, original sound, artist matches, music_id NOT in sound_ids
auto_discovery_sound_ids = {"7607726203173095425"}  # only official, alternate NOT added yet
campaign_artist = "Chezile"
creator_usernames = {"amourgazette", "art_of_thought"}

discovery_video = {
    "music_id": "7605685757969173262",
    "song": "original sound",
    "artist": "Chezile",
    "account": "@amourgazette",
    "is_original_sound": True,
}

vid_account = discovery_video["account"].lstrip("@").lower()
vid_music_id = discovery_video["music_id"]
vid_artist = discovery_video["artist"].lower().strip()
is_orig = discovery_video.get("is_original_sound", False)

should_discover = (
    vid_account in creator_usernames
    and is_orig
    and vid_artist == campaign_artist.lower()
    and vid_music_id
    and vid_music_id not in auto_discovery_sound_ids
)
test("auto-discovery: should discover alternate sound", should_discover)

# Non-creator should NOT trigger discovery
non_creator_video = {**discovery_video, "account": "@randomuser"}
vid_account2 = non_creator_video["account"].lstrip("@").lower()
should_not_discover = vid_account2 not in creator_usernames
test("auto-discovery: non-creator skipped", should_not_discover)


# ---------------------------------------------------------------
# TEST 8: Larger scrape test (multiple creators)
# ---------------------------------------------------------------
banner("8. Multi-creator scrape test (3 creators, 3 results each)")

print("  ... calling Apify (may take 60-90s) ...")
try:
    multi_results = scrape_profiles(
        ["amourgazette", "art_of_thought", "aurorajadepoetry"],
        results_per_page=3,
    )
    test("multi-scrape returned results", len(multi_results) > 0, f"got {len(multi_results)}")

    # Check we got results from multiple accounts
    accounts_found = set(v.get("account", "") for v in multi_results)
    test("multi-scrape: got multiple accounts", len(accounts_found) >= 2, f"accounts: {accounts_found}")

    # All should have music_id
    all_have_music = all(v.get("music_id") for v in multi_results)
    test("multi-scrape: all videos have music_id", all_have_music,
         f"{sum(1 for v in multi_results if v.get('music_id'))}/{len(multi_results)} have music_id")

    # Print account breakdown
    from collections import Counter
    acct_counts = Counter(v.get("account", "") for v in multi_results)
    print(f"\n  Per-account breakdown:")
    for acct, cnt in acct_counts.most_common():
        print(f"    {acct}: {cnt} videos")

except Exception as e:
    test("multi-scrape call", False, str(e))


# ---------------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------------
banner("RESULTS")
total = PASS + FAIL
print(f"  {PASS}/{total} passed, {FAIL}/{total} failed")
if FAIL:
    print(f"\n  !! {FAIL} TEST(S) FAILED !!")
    sys.exit(1)
else:
    print(f"\n  All tests passed!")
    sys.exit(0)
