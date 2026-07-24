#!/usr/bin/env python3
"""
Scrape external accounts for specific sounds from a CSV file with caching.
Only scrapes new videos since the last scrape to save time.

Usage:
    python scrape_external_accounts_cached.py <csv_file> --start-date YYYY-MM-DD [--limit N]
"""

import sys
import subprocess
import json
import csv
import re
import argparse
import pickle
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

def get_profile_username(url_or_username):
    """Extract username from TikTok profile URL or handle"""
    if not url_or_username or not isinstance(url_or_username, str):
        return None
    if not url_or_username.startswith('http'):
        username = url_or_username.lstrip('@')
        return username
    match = re.search(r'@([\w\.]+)', url_or_username)
    if match:
        return match.group(1)
    return None


def build_profile_url(username):
    """Build TikTok profile URL from username"""
    return f"https://www.tiktok.com/@{username}"


def normalize_song_key(song, artist):
    """Create normalized song key for matching"""
    song_clean = (song or '').strip()
    artist_clean = (artist or '').strip()
    return f"{song_clean} - {artist_clean}".strip()


def normalize_whitespace_text(value):
    """Normalize unicode/irregular whitespace to single spaces for robust matching."""
    return re.sub(r'\s+', ' ', (value or '')).strip()


def get_cache_file(account):
    """Get cache file path for an account"""
    username = get_profile_username(account)
    if not username:
        return None
    return CACHE_DIR / f"{username}_cache.pkl"


def load_account_cache(account):
    """Load cached video data for an account"""
    cache_file = get_cache_file(account)
    if not cache_file or not cache_file.exists():
        return None, None
    
    try:
        with open(cache_file, 'rb') as f:
            cache_data = pickle.load(f)
            videos = cache_data.get('videos', [])
            last_scrape_date = cache_data.get('last_scrape_date')
            return videos, last_scrape_date
    except Exception as e:
        print(f"    [WARNING] Error loading cache: {e}")
        return None, None


def save_account_cache(account, videos, scrape_date):
    """Save scraped video data to cache"""
    cache_file = get_cache_file(account)
    if not cache_file:
        return
    
    try:
        cache_data = {
            'videos': videos,
            'last_scrape_date': scrape_date,
            'cached_at': datetime.now()
        }
        with open(cache_file, 'wb') as f:
            pickle.dump(cache_data, f)
    except Exception as e:
        print(f"    [WARNING] Error saving cache: {e}")


def scrape_account_videos(account, start_date=None, limit=500, use_cache=True):
    """Scrape videos from a TikTok account, using cache to avoid re-scraping old videos"""
    username = get_profile_username(account)
    if not username:
        print(f"  [ERROR] Could not extract username from: {account}")
        return []
    
    profile_url = build_profile_url(username)
    print(f"  Scraping @{username}...")
    
    # Load cache if available
    cached_videos = []
    cache_cutoff_date = None
    if use_cache:
        cached_videos, last_scrape_date = load_account_cache(account)
        if cached_videos and last_scrape_date:
            cache_cutoff_date = last_scrape_date
            print(f"    Found {len(cached_videos)} cached videos (last scraped: {last_scrape_date})")
            # Only scrape videos newer than cache cutoff
            if start_date and cache_cutoff_date:
                # Use the later of the two dates
                scrape_from_date = max(start_date, cache_cutoff_date)
            elif cache_cutoff_date:
                scrape_from_date = cache_cutoff_date
            else:
                scrape_from_date = start_date
        else:
            scrape_from_date = start_date
    else:
        scrape_from_date = start_date
    
    # Hardened yt-dlp command (cookies / proxy / impersonation / retries)
    from src.scrapers.yt_dlp_runner import (
        NativeSubprocessCrash,
        build_tiktok_cmd,
        diagnose_failure,
        raise_for_native_crash,
    )
    cmd = build_tiktok_cmd(
        profile_url,
        flat_playlist=True,
        dump_json=True,
        playlist_end=limit,
    )

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        raise_for_native_crash(result, context=f"yt-dlp for @{username}")

        if result.returncode != 0:
            reason = diagnose_failure(result.stderr)
            print(f"    [ERROR] Failed to scrape [{reason}]: {result.stderr[:200]}")
            return cached_videos if cached_videos else []
        if not (result.stdout or "").strip():
            print(f"    [WARN] yt-dlp returned empty for {profile_url} — likely rate-limited / soft-block")
            return cached_videos if cached_videos else []
        
        new_videos = []
        total_fetched = 0
        skipped_old = 0
        skipped_cached = 0
        
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            try:
                video_data = json.loads(line)
                total_fetched += 1
                
                # Extract song info
                track = video_data.get('track', '') or 'Unknown'
                artist = video_data.get('artist', '') or (video_data.get('artists', [])[0] if video_data.get('artists') else 'Unknown')
                
                # Get video URL
                video_url = video_data.get('webpage_url') or video_data.get('url', '')
                
                if not video_url:
                    continue
                
                # Determine posted datetime
                video_dt = None
                timestamp = video_data.get('timestamp')
                if timestamp:
                    try:
                        video_dt = datetime.fromtimestamp(timestamp)
                    except (ValueError, OSError):
                        pass
                
                if not video_dt:
                    upload_date = video_data.get('upload_date')
                    if upload_date:
                        try:
                            video_dt = datetime.strptime(upload_date, '%Y%m%d')
                        except ValueError:
                            pass
                
                # Filter by start date if provided
                if scrape_from_date and video_dt:
                    if video_dt.date() < scrape_from_date:
                        skipped_old += 1
                        continue
                
                # Check if this video is already in cache (by URL)
                if cached_videos:
                    video_urls_cached = {v.get('url') for v in cached_videos}
                    if video_url in video_urls_cached:
                        skipped_cached += 1
                        continue
                
                new_videos.append({
                    'url': video_url,
                    'song': track,
                    'artist': artist,
                    'account': f"@{username}",
                    'views': video_data.get('view_count', 0),
                    'likes': video_data.get('like_count', 0),
                    'upload_date': video_data.get('upload_date', ''),
                    'timestamp': video_dt,
                    'music_id': video_data.get('music_id', '')  # Add music ID for matching
                })
            except json.JSONDecodeError:
                continue
        
        # Combine cached and new videos
        all_videos = (cached_videos or []) + new_videos
        
        # Save updated cache
        if use_cache:
            save_account_cache(account, all_videos, datetime.now().date())
        
        cache_info = f" | {len(cached_videos)} cached" if cached_videos else ""
        date_info = f" (after {scrape_from_date})" if scrape_from_date else ""
        print(f"    Fetched {total_fetched} posts | {len(new_videos)} new{date_info} | {skipped_old} too old | {skipped_cached} already cached{cache_info}")
        
        return all_videos
        
    except NativeSubprocessCrash as e:
        print(f"    [ERROR] Native crash scraping @{username}: {e}")
        raise
    except subprocess.TimeoutExpired:
        print(f"    [ERROR] Timeout scraping @{username}")
        return cached_videos if cached_videos else []
    except Exception as e:
        print(f"    [ERROR] {e}")
        return cached_videos if cached_videos else []


def load_external_accounts_csv(csv_path):
    """Load sounds and accounts from CSV file, including sound IDs"""
    sounds_to_track = defaultdict(set)
    sound_ids_to_track = defaultdict(set)  # Track by sound ID
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            sound_key = None
            song = None
            artist = None
            sound_id = None
            
            # Extract sound ID from "Tiktok Sound ID" column if present
            for col in ['Tiktok Sound ID', 'Tiktok Sound', 'Sound ID', 'sound_id']:
                if col in row and row[col]:
                    sound_url = row[col].strip()
                    # Extract ID from URL like https://www.tiktok.com/music/original-sound-7548164346728254239
                    match = re.search(r'original-sound-(\d+)', sound_url)
                    if match:
                        sound_id = match.group(1)
                    # Also try pattern like music/song-1234567890
                    if not sound_id:
                        match = re.search(r'song-(\d+)', sound_url)
                        if match:
                            sound_id = match.group(1)
                    # Also try pattern like music/The-Chariot-1234567890
                    if not sound_id:
                        match = re.search(r'music/[^-]+-(\d+)', sound_url)
                        if match:
                            sound_id = match.group(1)
                    # Fallback: try to find any sequence of digits at the end
                    if not sound_id:
                        match = re.search(r'-(\d+)$', sound_url)
                        if match:
                            sound_id = match.group(1)
                    break
            
            if 'sound_key' in row and row['sound_key']:
                sound_key = row['sound_key'].strip()
            elif 'Song' in row or 'song' in row:
                song = (row.get('Song') or row.get('song', '')).strip()
                artist = (row.get('Artist') or row.get('artist') or row.get('Artist Name', '')).strip()
                if song and artist:
                    sound_key = normalize_song_key(song, artist)
            
            if not sound_key and not sound_id:
                continue
            
            account = None
            for col in ['Account', 'account', 'Account URL', 'URL', 'account Handle', 'Creator Handles']:
                if col in row and row[col]:
                    account = row[col].strip()
                    break
            
            if not account:
                continue
            
            # Normalize account to @username format
            account_normalized = get_profile_username(account)
            if account_normalized:
                account_normalized = f"@{account_normalized}"
            else:
                account_normalized = account
            
            if sound_key:
                sounds_to_track[sound_key].add(account_normalized)
            if sound_id:
                sound_ids_to_track[sound_id].add(account_normalized)
    
    return sounds_to_track, sound_ids_to_track


def match_video_to_sounds(video, tracked_sounds, tracked_sound_ids=None):
    """Check if a video matches any of the tracked sounds, by sound ID first, then by song/artist"""
    # First, try matching by sound ID (most reliable)
    if tracked_sound_ids and video.get('music_id'):
        video_music_id = str(video['music_id']).strip()
        if video_music_id in tracked_sound_ids:
            # Return the first matching sound key for this sound ID
            for sound_key, accounts in tracked_sounds.items():
                if accounts & tracked_sound_ids[video_music_id]:
                    return sound_key
    
    # Fall back to song/artist matching
    video_song_key = normalize_song_key(video['song'], video['artist'])
    
    if video_song_key in tracked_sounds:
        return video_song_key
    
    video_song_key_lower = video_song_key.lower()
    for sound_key in tracked_sounds.keys():
        if sound_key.lower() == video_song_key_lower:
            return sound_key
    
    video_song = (video['song'] or '').strip().lower()
    video_artist_lower = (video['artist'] or '').strip().lower()
    video_song_norm = normalize_whitespace_text(video_song)
    video_artist_norm = normalize_whitespace_text(video_artist_lower)
    
    # For regular "What You Got" campaign: ONLY match "What You Got" by "Quail P" (not "original sound")
    # For LIVE version: handled separately below, should NOT match here
    for sound_key in tracked_sounds.keys():
        sound_key_lower = sound_key.lower()
        # Skip LIVE version in this generic matching - it's handled separately
        if 'live' in sound_key_lower:
            continue
        sound_parts = sound_key.lower().split(' - ')
        if len(sound_parts) > 0 and sound_parts[0] == video_song:
            # Also verify artist matches for "What You Got" to avoid matching LIVE version
            if len(sound_parts) > 1:
                expected_artist = sound_parts[1].strip().lower()
                expected_artist_norm = normalize_whitespace_text(expected_artist)
                if (
                    expected_artist in video_artist_lower or
                    video_artist_lower in expected_artist or
                    expected_artist_norm in video_artist_norm or
                    video_artist_norm in expected_artist_norm
                ):
                    return sound_key
            else:
                return sound_key
    
    # For Dominique campaign: match any video with "dominique" or "seitenamekeek" in song/artist
    # For Shades of Blue campaign: match "Shades of Blue" or "All Shades of Blue"
    video_song_lower = (video['song'] or '').lower()
    video_artist_lower = (video['artist'] or '').lower()
    video_combined = f"{video_song_lower} {video_artist_lower}"
    
    for sound_key in tracked_sounds.keys():
        sound_key_lower = sound_key.lower()
        # Check if this is a Shades of Blue campaign
        if 'shades of blue' in sound_key_lower:
            # Match "Shades of Blue" or "All Shades of Blue" variations
            if ('shades of blue' in video_combined or 
                'all shades of blue' in video_combined):
                # Check if this account is tracked for this sound
                if video.get('account') in tracked_sounds[sound_key]:
                    return sound_key
        # Check if this is a Dominique campaign
        elif 'dominique' in sound_key_lower:
            # Match any video containing "dominique" or "seitenamekeek" (case-insensitive, handle variations)
            # Also check for common misspellings and partial matches
            if ('dominique' in video_combined or 
                'seitenamekeek' in video_combined or 
                'seitename' in video_combined or
                'seite name' in video_combined or
                'seitenameke' in video_combined):
                # Check if this account is tracked for this sound
                if video.get('account') in tracked_sounds[sound_key]:
                    return sound_key
            # Also check if the video URL contains the specific video ID we're looking for
            # This is a workaround for videos that might not be in the normal scrape
            video_url = video.get('url', '')
            if '7565984721801399607' in video_url and video.get('account') in tracked_sounds[sound_key]:
                return sound_key
    
    # Check for Spanish "original sound" variations
    spanish_original_sound_variations = [
        'sonido original', 'audio original', 'sonido original -', 'audio original -'
    ]
    video_song_lower = (video['song'] or '').lower()
    video_artist_lower = (video['artist'] or '').lower()
    video_combined = f"{video_song_lower} {video_artist_lower}"
    
    # Check if video has Spanish "original sound" and matches our tracked accounts
    for spanish_var in spanish_original_sound_variations:
        if spanish_var in video_song_lower:
            # If we're tracking this account and looking for Focus/AP, match it
            for sound_key in tracked_sounds.keys():
                sound_key_lower = sound_key.lower()
                if 'focus' in sound_key_lower and ('ap' in sound_key_lower or 'takeoff' in sound_key_lower):
                    # Check if this account is tracked for this sound
                    if video.get('account') in tracked_sounds[sound_key]:
                        return sound_key
    
    # Additional matching: check for partial matches (e.g., "AP x Focus" in song/artist)
    for sound_key in tracked_sounds.keys():
        sound_key_lower = sound_key.lower()
        # Check if sound key contains "focus" and "ap" (or variations)
        if 'focus' in sound_key_lower and ('ap' in sound_key_lower or 'takeoff' in sound_key_lower):
            # Check if video contains these keywords
            if ('focus' in video_combined and ('ap' in video_combined or 'takeoff' in video_combined)):
                return sound_key
            # Also check for "original sound" with AP/Focus context
            if 'original sound' in video_song_lower and ('ap' in video_artist_lower or 'takeoff' in video_artist_lower):
                return sound_key
    
    # For Attack Attack / ONE HIT WONDER: match any video with "one hit wonder" or "attack attack" in song/artist
    for sound_key in tracked_sounds.keys():
        sound_key_lower = sound_key.lower()
        if 'one hit wonder' in sound_key_lower or 'attack attack' in sound_key_lower:
            # Match any video containing "one hit wonder" or "attack attack" (case-insensitive)
            if ('one hit wonder' in video_combined or 
                'attack attack' in video_combined or
                'onehitwonder' in video_combined.replace(' ', '')):
                # Check if this account is tracked for this sound
                if video.get('account') in tracked_sounds[sound_key]:
                    return sound_key
    
    # For Blake Whiten / Night N Day: match "original sound - blake whiten" variations
    for sound_key in tracked_sounds.keys():
        sound_key_lower = sound_key.lower()
        if 'night n day' in sound_key_lower and 'blake whiten' in sound_key_lower:
            # Match "original sound - blake whiten" or variations
            if ('original sound' in video_song_lower and 'blake whiten' in video_artist_lower):
                # Check if this account is tracked for this sound
                if video.get('account') in tracked_sounds[sound_key]:
                    return sound_key
            # Also match "Night N Day" or "Night and Day" variations
            if ('night n day' in video_combined or 
                'night and day' in video_combined or
                'nightnday' in video_combined.replace(' ', '')):
                # Check if this account is tracked for this sound
                if video.get('account') in tracked_sounds[sound_key]:
                    return sound_key
    
    # For Cam Whitcomb / At the End of the Day: match "original sound" + "cam whitcomb" variants
    for sound_key in tracked_sounds.keys():
        sound_key_lower = sound_key.lower()
        if sound_key_lower == 'at the end of the day - cam whitcomb':
            if 'original sound' in video_song_lower and 'cam whitcomb' in video_artist_lower:
                if video.get('account') in tracked_sounds[sound_key]:
                    return sound_key

    # For Raise / Black Gummy: match "Raise" with "BlackGummy" or "Black Gummy" variations
    for sound_key in tracked_sounds.keys():
        sound_key_lower = sound_key.lower()
        if 'raise' in sound_key_lower and ('blackgummy' in sound_key_lower or 'black gummy' in sound_key_lower):
            # Match "Raise" in song and "BlackGummy" or "Black Gummy" or "BlackGummy, Oliver Rio" in artist
            if ('raise' in video_song_lower and 
                ('blackgummy' in video_artist_lower or 'black gummy' in video_artist_lower or 'oliver rio' in video_artist_lower)):
                # Check if this account is tracked for this sound
                if video.get('account') in tracked_sounds[sound_key]:
                    return sound_key
    
    # For Quail P / What You Got (LIVE): match "original sound" (English or Italian) with quail/quailclips
    # IMPORTANT: Only match by sound ID or "original sound" format, NOT by "What You Got" song name (that's the regular version)
    for sound_key in tracked_sounds.keys():
        sound_key_lower = sound_key.lower()
        if 'what you got' in sound_key_lower and 'live' in sound_key_lower and 'quail' in sound_key_lower:
            # Match "original sound" (English or Italian) with quail/quailclips
            original_sound_variations = ['original sound', 'suono originale', 'audio originale']
            for original_var in original_sound_variations:
                if original_var in video_song_lower:
                    # Check if video has quail/quailclips in artist (case-insensitive, handle spacing)
                    artist_normalized = video_artist_lower.replace(' ', '').replace('_', '').replace('-', '')
                    if ('quail' in video_artist_lower or 'quailclips' in artist_normalized or 'quail clips' in video_artist_lower):
                        # Check if this account is tracked for this sound
                        if video.get('account') in tracked_sounds[sound_key]:
                            return sound_key
            # DO NOT match by "What You Got" song name - that's the regular version, not LIVE
    
    # For Kami Kehoe / Fade Out: match "original sound - kami kehoe" variations (in any language)
    for sound_key in tracked_sounds.keys():
        sound_key_lower = sound_key.lower()
        if 'fade out' in sound_key_lower and 'kami kehoe' in sound_key_lower:
            # Match "original sound" variations (English, Spanish, Italian, etc.) with "kami kehoe" in artist
            original_sound_variations = [
                'original sound', 'sonido original', 'suono originale', 
                'audio original', 'audio originale', 'som original',
                'origineel geluid', 'son original'
            ]
            for original_var in original_sound_variations:
                if original_var in video_song_lower:
                    # Check if video has "kami kehoe" in artist (case-insensitive)
                    if 'kami kehoe' in video_artist_lower:
                        # Check if this account is tracked for this sound
                        if video.get('account') in tracked_sounds[sound_key]:
                            return sound_key
            # Also match "Fade Out" directly if found
            if 'fade out' in video_combined and 'kami kehoe' in video_combined:
                if video.get('account') in tracked_sounds[sound_key]:
                    return sound_key
    
    return None


def main():
    parser = argparse.ArgumentParser(
        description='Scrape external accounts for specific sounds from CSV (with caching)',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('csv_file', help='Path to CSV file with sounds and accounts')
    parser.add_argument('--start-date', type=str, help='Campaign start date (YYYY-MM-DD)')
    parser.add_argument('--limit', type=int, default=500, help='Maximum videos to scrape per account (default: 500)')
    parser.add_argument('--output', type=str, help='Output file path')
    parser.add_argument('--no-cache', action='store_true', help='Disable caching and scrape everything')
    
    args = parser.parse_args()
    
    start_date = None
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        except ValueError:
            print(f"[ERROR] Invalid date format: {args.start_date}. Use YYYY-MM-DD")
            sys.exit(1)
    
    # Automatically increase limit to 2000 if start date is about a month old (25+ days)
    limit = args.limit
    if start_date:
        days_ago = (datetime.now().date() - start_date).days
        if days_ago >= 25:  # About a month old
            if limit < 2000:
                limit = 2000
                print(f"[INFO] Start date is {days_ago} days old, automatically increasing limit to 2000")
    
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"[ERROR] CSV file not found: {csv_path}")
        sys.exit(1)
    
    print("=" * 80)
    print("EXTERNAL ACCOUNTS SCRAPER (WITH CACHING)")
    print("=" * 80)
    print(f"\nLoading sounds and accounts from: {csv_path}")
    
    sounds_to_track, sound_ids_to_track = load_external_accounts_csv(csv_path)
    
    if not sounds_to_track and not sound_ids_to_track:
        print("[ERROR] No sounds/accounts found in CSV file")
        sys.exit(1)
    
    print(f"\nFound {len(sounds_to_track)} unique sounds to track")
    if sound_ids_to_track:
        print(f"Found {len(sound_ids_to_track)} unique sound IDs to track")
    total_accounts = sum(len(accounts) for accounts in sounds_to_track.values())
    print(f"Total account-sound combinations: {total_accounts}")
    
    if start_date:
        print(f"Campaign start date: {start_date}")
    if not args.no_cache:
        print("Using cache: Only scraping new videos since last scrape")
    else:
        print("Cache disabled: Scraping all videos")
    print(f"Scrape limit: {limit} videos per account")
    print()
    
    all_accounts = set()
    for accounts in sounds_to_track.values():
        all_accounts.update(accounts)
    
    print(f"Scraping {len(all_accounts)} unique accounts...\n")
    
    all_videos = []
    account_videos = {}
    
    for account in all_accounts:
        videos = scrape_account_videos(
            account, 
            start_date=start_date, 
            limit=limit,
            use_cache=not args.no_cache
        )
        account_videos[account] = videos
        all_videos.extend(videos)
    
    print(f"\nTotal videos available: {len(all_videos)}")
    
    # Filter by start date if provided (for final results)
    if start_date:
        filtered_videos = []
        for video in all_videos:
            if video.get('timestamp'):
                if video['timestamp'].date() >= start_date:
                    filtered_videos.append(video)
            else:
                # Include videos without timestamp if we can't verify
                filtered_videos.append(video)
        all_videos = filtered_videos
        print(f"Videos after filtering by start date: {len(all_videos)}")
    
    # Match videos to tracked sounds
    matched_videos = defaultdict(lambda: {
        'song': '',
        'artist': '',
        'videos': [],
        'accounts': set(),
        'total_views': 0,
        'total_likes': 0
    })
    
    matched_count = 0
    for video in all_videos:
        matched_sound = match_video_to_sounds(video, sounds_to_track, sound_ids_to_track)
        if matched_sound:
            account = video['account']
            if account in sounds_to_track[matched_sound]:
                matched_videos[matched_sound]['song'] = video['song']
                matched_videos[matched_sound]['artist'] = video['artist']
                matched_videos[matched_sound]['videos'].append(video)
                matched_videos[matched_sound]['accounts'].add(account)
                matched_videos[matched_sound]['total_views'] += video['views']
                matched_videos[matched_sound]['total_likes'] += video['likes']
                matched_count += 1
    
    print(f"Matched {matched_count} videos to tracked sounds\n")
    
    # Debug: Show sounds found for specific accounts if requested
    debug_accounts = ['@onlyupset_', '@niccolocosci', '@eeryyxx', '@somethingicouldntsay']  # Add accounts to debug here
    if any(video.get('account') in debug_accounts for video in all_videos):
        print("\nDebug: Checking sounds for @onlyupset_ videos:")
        onlyupset_videos = [v for v in all_videos if v.get('account') == '@onlyupset_']
        
        # Check for the specific missed video
        missed_video_id = '7565984721801399607'
        missed_video = [v for v in onlyupset_videos if missed_video_id in v.get('url', '')]
        if missed_video:
            v = missed_video[0]
            print(f"  Found missed video: {v['url']}")
            print(f"    Song: {v['song']}, Artist: {v['artist']}, Music ID: {v.get('music_id', 'N/A')}")
            print(f"    Upload Date: {v.get('upload_date', 'N/A')}, Timestamp: {v.get('timestamp', 'N/A')}")
            song_key = normalize_song_key(v['song'], v['artist'])
            print(f"    Song Key: {song_key}")
            print(f"    Matched sound: {match_video_to_sounds(v, sounds_to_track, sound_ids_to_track)}")
        else:
            print(f"  Missed video {missed_video_id} NOT found in scraped videos")
            # Check all video IDs to see what we have
            video_ids = [v.get('url', '').split('/video/')[-1].split('?')[0] for v in onlyupset_videos if '/video/' in v.get('url', '')]
            print(f"  Scraped {len(video_ids)} videos from @onlyupset_")
            # Check if there are videos with similar IDs
            similar_ids = [vid for vid in video_ids if vid.startswith('75659')]
            if similar_ids:
                print(f"  Found {len(similar_ids)} videos with IDs starting with 75659 (similar to missed video)")
        
        # Find ALL videos with dominique or seitenamekeek in any form
        dominique_sounds = []
        for video in onlyupset_videos:
            song_key = normalize_song_key(video['song'], video['artist'])
            music_id = video.get('music_id', 'N/A')
            video_combined = f"{(video.get('song') or '').lower()} {(video.get('artist') or '').lower()}"
            if ('dominique' in song_key.lower() or 
                'dominique' in video_combined or
                'seitenamekeek' in video_combined or
                'seitename' in video_combined or
                str(music_id) == '7512574437779867664'):
                dominique_sounds.append({
                    'url': video['url'],
                    'song': video['song'],
                    'artist': video['artist'],
                    'music_id': music_id,
                    'song_key': song_key
                })
        if dominique_sounds:
            print(f"  Found {len(dominique_sounds)} potential Dominique videos:")
            for v in dominique_sounds:
                print(f"    - {v['url']}")
                print(f"      Song: {v['song']}, Artist: {v['artist']}, Music ID: {v['music_id']}")
        else:
            print("  No Dominique sounds found in @onlyupset_ videos")
    
    # Debug for Attack Attack accounts
    attack_accounts = ['@niccolocosci', '@eeryyxx', '@somethingicouldntsay']
    if any(video.get('account') in attack_accounts for video in all_videos):
        print("\nDebug: Checking sounds for Attack Attack accounts:")
        for account in attack_accounts:
            account_videos = [v for v in all_videos if v.get('account') == account]
            if not account_videos:
                continue
            print(f"\n  @{account.replace('@', '')}: {len(account_videos)} videos scraped")
            # Find videos with "one hit wonder" or "attack attack"
            one_hit_videos = []
            for video in account_videos:
                video_combined = f"{(video.get('song') or '').lower()} {(video.get('artist') or '').lower()}"
                if ('one hit wonder' in video_combined or 
                    'attack attack' in video_combined or
                    'onehitwonder' in video_combined.replace(' ', '')):
                    one_hit_videos.append(video)
            if one_hit_videos:
                print(f"    Found {len(one_hit_videos)} potential ONE HIT WONDER videos:")
                for v in one_hit_videos[:5]:  # Show first 5
                    print(f"      - {v['url']}")
                    print(f"        Song: {v['song']}, Artist: {v['artist']}, Music ID: {v.get('music_id', 'N/A')}")
            else:
                print(f"    No ONE HIT WONDER sounds found")
                # Show top sounds
                found_songs = defaultdict(int)
                for video in account_videos:
                    song_key = normalize_song_key(video['song'], video['artist'])
                    found_songs[song_key] += 1
                print(f"    Top 5 sounds found:")
                for song_key, count in sorted(found_songs.items(), key=lambda x: x[1], reverse=True)[:5]:
                    try:
                        print(f"      - {song_key} ({count} videos)")
                    except UnicodeEncodeError:
                        # Handle encoding errors for Windows console
                        safe_key = song_key.encode('ascii', errors='replace').decode('ascii')
                        print(f"      - {safe_key} ({count} videos)")
    
    if not matched_videos:
        print("No videos matched the tracked sounds.")
        print("\nDebug: Showing unique songs found in scraped videos:")
        found_songs = defaultdict(int)
        for video in all_videos:
            song_key = normalize_song_key(video['song'], video['artist'])
            found_songs[song_key] += 1
        
        print(f"Found {len(found_songs)} unique songs:")
        for song_key, count in sorted(found_songs.items(), key=lambda x: x[1], reverse=True)[:20]:
            try:
                print(f"  - {song_key} ({count} videos)")
            except UnicodeEncodeError:
                # Handle encoding errors for Windows console
                safe_key = song_key.encode('ascii', errors='replace').decode('ascii')
                print(f"  - {safe_key} ({count} videos)")
        
        print(f"\nLooking for: {', '.join(sounds_to_track.keys())}")
        print("\nExiting.")
        return
    
    sorted_songs = sorted(matched_videos.items(), key=lambda x: x[1]['total_views'], reverse=True)
    
    # Calculate 24-hour cutoff
    now = datetime.now()
    last_24h_cutoff = now - timedelta(hours=24)
    
    print("=" * 80)
    print("RESULTS GROUPED BY SONG")
    print("=" * 80)
    
    for sound_key, data in sorted_songs:
        print(f"\n{'=' * 80}")
        print(f"SONG: {data['song']}")
        print(f"ARTIST: {data['artist']}")
        
        # Separate videos by recency
        recent_videos = []
        older_videos = []
        
        for video in data['videos']:
            if video.get('timestamp'):
                if video['timestamp'] >= last_24h_cutoff:
                    recent_videos.append(video)
                else:
                    older_videos.append(video)
            else:
                older_videos.append(video)
        
        print(f"Total Uses: {len(data['videos'])} ({len(recent_videos)} in last 24h, {len(older_videos)} older)")
        print(f"Accounts: {', '.join(sorted(data['accounts']))}")
        print(f"Total Views: {data['total_views']:,}")
        print(f"Total Likes: {data['total_likes']:,}")
        
        # Write recent videos first
        if recent_videos:
            print(f"\n--- NEW IN LAST 24 HOURS ({len(recent_videos)} videos) ---")
            print("-" * 80)
            sorted_recent = sorted(recent_videos, key=lambda x: x.get('timestamp', datetime.min) if x.get('timestamp') else datetime.min, reverse=True)
            for i, video in enumerate(sorted_recent, 1):
                print(f"  {i}. {video['url']}")
                print(f"     Account: {video['account']} | Views: {video['views']:,} | Likes: {video['likes']:,}")
        
        # Then older videos
        if older_videos:
            print(f"\n--- OLDER VIDEOS ({len(older_videos)} videos) ---")
            print("-" * 80)
            sorted_older = sorted(older_videos, key=lambda x: x['views'], reverse=True)
            for i, video in enumerate(sorted_older, 1):
                print(f"  {i}. {video['url']}")
                print(f"     Account: {video['account']} | Views: {video['views']:,} | Likes: {video['likes']:,}")
    
    output_file = Path(args.output) if args.output else Path('output') / 'external_accounts_by_song.txt'
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("EXTERNAL ACCOUNTS - POST LINKS GROUPED BY SONG\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        if start_date:
            f.write(f"Campaign Start Date: {start_date}\n")
        f.write(f"CSV Source: {csv_path}\n")
        f.write(f"Accounts processed: {len(all_accounts)}\n")
        f.write(f"Total videos available: {len(all_videos)}\n")
        f.write(f"Matched videos: {matched_count}\n")
        f.write(f"Unique songs matched: {len(matched_videos)}\n")
        if not args.no_cache:
            f.write("Cache: Enabled (only new videos scraped)\n")
        f.write("\n")
        
        for sound_key, data in sorted_songs:
            f.write(f"\n{'=' * 80}\n")
            song_safe = data['song'].encode('utf-8', errors='replace').decode('utf-8')
            artist_safe = data['artist'].encode('utf-8', errors='replace').decode('utf-8')
            
            # Separate videos by recency
            recent_videos = []
            older_videos = []
            
            for video in data['videos']:
                if video.get('timestamp'):
                    if video['timestamp'] >= last_24h_cutoff:
                        recent_videos.append(video)
                    else:
                        older_videos.append(video)
                else:
                    older_videos.append(video)
            
            f.write(f"SONG: {song_safe}\n")
            f.write(f"ARTIST: {artist_safe}\n")
            f.write(f"Total Uses: {len(data['videos'])} ({len(recent_videos)} in last 24h, {len(older_videos)} older)\n")
            f.write(f"Accounts: {', '.join(sorted(data['accounts']))}\n")
            f.write(f"Total Views: {data['total_views']:,}\n")
            f.write(f"Total Likes: {data['total_likes']:,}\n")
            
            # Write recent videos first
            if recent_videos:
                f.write(f"\n--- NEW IN LAST 24 HOURS ({len(recent_videos)} videos) ---\n")
                f.write("-" * 80 + "\n")
                sorted_recent = sorted(recent_videos, key=lambda x: x.get('timestamp', datetime.min) if x.get('timestamp') else datetime.min, reverse=True)
                for i, video in enumerate(sorted_recent, 1):
                    f.write(f"  {i}. {video['url']}\n")
                    f.write(f"     Account: {video['account']} | Views: {video['views']:,} | Likes: {video['likes']:,}\n")
            
            # Then older videos
            if older_videos:
                f.write(f"\n--- OLDER VIDEOS ({len(older_videos)} videos) ---\n")
                f.write("-" * 80 + "\n")
                sorted_older = sorted(older_videos, key=lambda x: x['views'], reverse=True)
                for i, video in enumerate(sorted_older, 1):
                    f.write(f"  {i}. {video['url']}\n")
                    f.write(f"     Account: {video['account']} | Views: {video['views']:,} | Likes: {video['likes']:,}\n")
    
    copy_paste_file = output_file.parent / 'external_accounts_copy_paste.txt'
    
    # Create campaign-specific copy/paste file
    campaign_copy_paste_file = output_file.parent / f"{output_file.stem.replace('_results', '_copy_paste')}.txt"
    
    # Calculate 24-hour cutoff
    now = datetime.now()
    last_24h_cutoff = now - timedelta(hours=24)
    
    def write_copy_paste_file(file_path):
        """Helper function to write copy/paste format to a file"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("EXTERNAL ACCOUNTS - COPY/PASTE FORMAT\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            if start_date:
                f.write(f"Campaign Start Date: {start_date}\n")
            f.write(f"CSV Source: {csv_path}\n")
            f.write(f"Accounts processed: {len(all_accounts)}\n")
            f.write(f"Total videos available: {len(all_videos)}\n")
            f.write(f"Matched videos: {matched_count}\n")
            f.write(f"Unique songs matched: {len(matched_videos)}\n")
            f.write(f"Last 24 hours cutoff: {last_24h_cutoff.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("=" * 80 + "\n\n")
            
            for sound_key, data in sorted_songs:
                song_safe = data['song'].encode('utf-8', errors='replace').decode('utf-8')
                artist_safe = data['artist'].encode('utf-8', errors='replace').decode('utf-8')
                
                # Separate videos by recency
                recent_videos = []
                older_videos = []
                
                for video in data['videos']:
                    if video.get('timestamp'):
                        if video['timestamp'] >= last_24h_cutoff:
                            recent_videos.append(video)
                        else:
                            older_videos.append(video)
                    else:
                        older_videos.append(video)
                
                f.write(f"SONG: {song_safe} - {artist_safe}\n")
                f.write(f"Total Uses: {len(data['videos'])} ({len(recent_videos)} in last 24h, {len(older_videos)} older) | Total Views: {data['total_views']:,}\n")
                f.write("=" * 80 + "\n\n")
                
                # Write recent videos first
                if recent_videos:
                    f.write(f"--- NEW IN LAST 24 HOURS ({len(recent_videos)} videos) ---\n\n")
                    sorted_recent = sorted(recent_videos, key=lambda x: x.get('timestamp', datetime.min) if x.get('timestamp') else datetime.min, reverse=True)
                    for video in sorted_recent:
                        f.write(f"{video['url']}\n")
                    f.write("\n")
                
                # Then older videos
                if older_videos:
                    f.write(f"--- OLDER VIDEOS ({len(older_videos)} videos) ---\n\n")
                    sorted_older = sorted(older_videos, key=lambda x: x['views'], reverse=True)
                    for video in sorted_older:
                        f.write(f"{video['url']}\n")
                    f.write("\n")
    
    # Write to both the shared file and campaign-specific file
    write_copy_paste_file(copy_paste_file)
    write_copy_paste_file(campaign_copy_paste_file)
    
    print(f"\n{'=' * 80}")
    print(f"[SUCCESS] Results saved to:")
    print(f"  Detailed: {output_file}")
    print(f"  Copy/Paste (shared): {copy_paste_file}")
    print(f"  Copy/Paste (campaign): {campaign_copy_paste_file}")
    print(f"{'=' * 80}\n")


if __name__ == '__main__':
    main()

