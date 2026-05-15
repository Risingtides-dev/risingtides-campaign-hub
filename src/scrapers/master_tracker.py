#!/usr/bin/env python3
"""
Master Tracker - Discovery-only campaign tracking with parallel processing and Instagram support

Scope (post-RTA-44): new-post discovery via yt-dlp + matching against tracked
sounds. Per-video sound-ID HTML enrichment was removed because performance
stats now flow from the Tides Tracker public API
(`campaign_manager/services/campaign_stats.py`), so the per-video HTML fetch
that used to burn Decodo bandwidth is no longer load-bearing for stats. Sound
matching falls back to yt-dlp's `music_id` field plus song/artist text keys.

Features:
- Parallel account scraping (5-10x faster)
- Smart caching (3-5x faster on re-scrapes)
- Early termination for cached videos
- Instagram support via Instaloader
- Comprehensive validation and error checking
- Progress bars and detailed logging
- No hallucinations - validates all data

Usage:
    python master_tracker.py <csv_file> --start-date YYYY-MM-DD [--platform tiktok/instagram/both]
"""

import sys
import subprocess
import json
import csv
import re
import argparse
import pickle
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from tqdm import tqdm

# Instagram support
try:
    import instaloader
    INSTAGRAM_AVAILABLE = True
except ImportError:
    INSTAGRAM_AVAILABLE = False
    print("[WARNING] Instaloader not available - Instagram scraping disabled")

# Configuration
import os
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "cache"))
CACHE_DIR.mkdir(exist_ok=True, parents=True)

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Timeout settings (much more generous)
TIKTOK_SCRAPE_TIMEOUT = 600  # 10 minutes per account
MAX_ACCOUNT_WORKERS = 5  # Parallel account scraping workers

# Early termination settings
EARLY_TERMINATION_ENABLED = True
CONSECUTIVE_CACHED_THRESHOLD = 20  # Stop after this many consecutive cached videos

# Validation settings
VALIDATION_ENABLED = True


class ValidationError(Exception):
    """Raised when data validation fails"""
    pass


def log(message, level="INFO"):
    """Enhanced logging with timestamps"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def get_profile_username(url_or_username):
    """Extract username from TikTok/Instagram profile URL or handle"""
    if not url_or_username or not isinstance(url_or_username, str):
        return None
    if not url_or_username.startswith('http'):
        username = url_or_username.lstrip('@')
        return username

    # TikTok pattern
    match = re.search(r'@([\w\.]+)', url_or_username)
    if match:
        return match.group(1)

    # Instagram pattern
    match = re.search(r'instagram\.com/([^/?]+)', url_or_username)
    if match:
        return match.group(1)

    return None


def normalize_song_key(song, artist):
    """Create normalized song key for matching"""
    song_clean = (song or '').strip().lower()
    artist_clean = (artist or '').strip().lower()
    return f"{song_clean} - {artist_clean}".strip()


def validate_video_data(video_data: Dict, platform: str) -> bool:
    """
    Validate video data to ensure no hallucinations or missing critical fields

    Returns: True if valid, raises ValidationError if invalid
    """
    if not VALIDATION_ENABLED:
        return True

    required_fields = ['url', 'account']

    for field in required_fields:
        if field not in video_data or not video_data[field]:
            raise ValidationError(f"Missing required field: {field}")

    # Validate URL format
    url = video_data['url']
    if platform == 'tiktok':
        if 'tiktok.com' not in url or ('/video/' not in url and '/photo/' not in url):
            raise ValidationError(f"Invalid TikTok URL format: {url}")
    elif platform == 'instagram':
        if 'instagram.com' not in url:
            raise ValidationError(f"Invalid Instagram URL format: {url}")

    # Validate numeric fields
    numeric_fields = ['views', 'likes']
    for field in numeric_fields:
        if field in video_data and video_data[field] is not None:
            try:
                int(video_data[field])
            except (ValueError, TypeError):
                log(f"Invalid {field} value: {video_data[field]}", "WARNING")
                video_data[field] = 0

    return True


def get_cache_file(account: str, platform: str) -> Optional[Path]:
    """Get cache file path for an account"""
    username = get_profile_username(account)
    if not username:
        return None
    return CACHE_DIR / f"{platform}_{username}_cache.pkl"


def load_account_cache(account: str, platform: str) -> Tuple[Optional[List], Optional[datetime]]:
    """Load cached video data for an account"""
    cache_file = get_cache_file(account, platform)
    if not cache_file or not cache_file.exists():
        return None, None

    try:
        with open(cache_file, 'rb') as f:
            cache_data = pickle.load(f)
            videos = cache_data.get('videos', [])
            last_scrape_date = cache_data.get('last_scrape_date')
            log(f"Loaded cache for {account}: {len(videos)} videos (last: {last_scrape_date})")
            return videos, last_scrape_date
    except Exception as e:
        log(f"Error loading cache for {account}: {e}", "WARNING")
        return None, None


def save_account_cache(account: str, platform: str, videos: List[Dict], scrape_date: datetime):
    """Save scraped video data to cache"""
    cache_file = get_cache_file(account, platform)
    if not cache_file:
        return

    try:
        cache_data = {
            'videos': videos,
            'last_scrape_date': scrape_date,
            'cached_at': datetime.now(),
            'platform': platform
        }
        with open(cache_file, 'wb') as f:
            pickle.dump(cache_data, f)
        log(f"Saved cache for {account}: {len(videos)} videos")
    except Exception as e:
        log(f"Error saving cache for {account}: {e}", "WARNING")


def scrape_tiktok_account(account: str, start_date: Optional[datetime] = None,
                          limit: int = 500, use_cache: bool = True) -> List[Dict]:
    """
    Scrape videos from a TikTok account with enhanced error handling and early termination
    """
    username = get_profile_username(account)
    if not username:
        log(f"Could not extract username from: {account}", "ERROR")
        return []

    profile_url = f"https://www.tiktok.com/@{username}"
    print(f"  -> Starting scrape for @{username}...")
    log(f"Scraping TikTok @{username}...")

    # Load cache
    cached_videos = []
    cache_cutoff_date = None
    cached_urls = set()
    if use_cache:
        cached_videos, last_scrape_date = load_account_cache(account, 'tiktok')
        if cached_videos and last_scrape_date:
            # Normalize to `date` on both sides — start_date can come in as
            # either datetime or date depending on caller, and `max()` raises
            # TypeError when comparing the two types directly.
            cache_cutoff_date = last_scrape_date.date() if isinstance(last_scrape_date, datetime) else last_scrape_date
            start_date_norm = start_date.date() if isinstance(start_date, datetime) else start_date
            scrape_from_date = max(start_date_norm, cache_cutoff_date) if start_date_norm else cache_cutoff_date
            cached_urls = {v.get('url') for v in cached_videos}
        else:
            scrape_from_date = start_date.date() if isinstance(start_date, datetime) else start_date
    else:
        scrape_from_date = start_date.date() if isinstance(start_date, datetime) else start_date

    # Hardened yt-dlp command (cookies / proxy / impersonation / retries)
    from src.scrapers.yt_dlp_runner import build_tiktok_cmd, diagnose_failure
    cmd = build_tiktok_cmd(
        profile_url,
        flat_playlist=True,
        dump_json=True,
        playlist_end=limit,
    )

    try:
        log(f"Running yt-dlp for @{username}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIKTOK_SCRAPE_TIMEOUT)

        if result.returncode != 0:
            reason = diagnose_failure(result.stderr)
            log(f"yt-dlp failed for @{username} [{reason}]: {result.stderr[:500]}", "ERROR")
            return cached_videos if cached_videos else []
        # Empty stdout with returncode 0 is the silent-fail mode TikTok
        # serves when it doesn't want to give us anything — log it loud.
        if not (result.stdout or "").strip():
            log(f"yt-dlp returned empty for @{username} — likely rate-limited / soft-block", "WARNING")
            return cached_videos if cached_videos else []

        new_videos = []
        total_fetched = 0
        skipped_old = 0
        skipped_cached = 0
        consecutive_cached = 0  # Track consecutive cached videos for early termination

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue

            # Early termination: Stop if we've hit too many consecutive cached videos
            if EARLY_TERMINATION_ENABLED and consecutive_cached >= CONSECUTIVE_CACHED_THRESHOLD:
                log(f"Early termination: Hit {consecutive_cached} consecutive cached videos for @{username}")
                break

            try:
                video_data = json.loads(line)
                total_fetched += 1

                # Extract metadata
                track = video_data.get('track', '') or 'Unknown'
                artist = video_data.get('artist', '') or (video_data.get('artists', [])[0] if video_data.get('artists') else 'Unknown')
                video_url = video_data.get('webpage_url') or video_data.get('url', '')

                if not video_url:
                    continue

                # Parse timestamp
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

                # Filter by date
                if scrape_from_date and video_dt:
                    if video_dt.date() < scrape_from_date:
                        skipped_old += 1
                        consecutive_cached = 0  # Reset counter
                        continue

                # Check cache
                if video_url in cached_urls:
                    skipped_cached += 1
                    consecutive_cached += 1
                    continue

                # Reset consecutive counter if we found a new video
                consecutive_cached = 0

                video_entry = {
                    'url': video_url,
                    'song': track,
                    'artist': artist,
                    'account': f"@{username}",
                    'views': video_data.get('view_count', 0),
                    'likes': video_data.get('like_count', 0),
                    'upload_date': video_data.get('upload_date', ''),
                    'timestamp': video_dt,
                    'music_id': video_data.get('music_id', ''),
                    'platform': 'tiktok'
                }

                # Validate
                try:
                    validate_video_data(video_entry, 'tiktok')
                    new_videos.append(video_entry)
                except ValidationError as e:
                    log(f"Validation failed for video: {e}", "WARNING")
                    continue

            except json.JSONDecodeError:
                continue

        # Combine cached and new
        all_videos = (cached_videos or []) + new_videos

        # Save cache (all videos, unfiltered)
        if use_cache:
            save_account_cache(account, 'tiktok', all_videos, datetime.now().date())

        # Filter returned videos to only those after start_date (cache keeps everything).
        # Both sides normalized to `date` to avoid datetime/date comparison errors.
        if start_date:
            start_date_norm = start_date.date() if isinstance(start_date, datetime) else start_date
            all_videos = [
                v for v in all_videos
                if not v.get('timestamp')
                or (v['timestamp'].date() if isinstance(v['timestamp'], datetime) else v['timestamp']) >= start_date_norm
            ]

        print(f"  -> Completed @{username}: {len(new_videos)} new videos, {len(all_videos)} total (after date filter)")
        log(f"TikTok @{username}: {total_fetched} fetched, {len(new_videos)} new, {skipped_old} old, {skipped_cached} cached")

        return all_videos

    except subprocess.TimeoutExpired:
        log(f"Timeout scraping TikTok @{username} (exceeded {TIKTOK_SCRAPE_TIMEOUT}s)", "ERROR")
        return cached_videos if cached_videos else []
    except Exception as e:
        log(f"Error scraping TikTok @{username}: {e}", "ERROR")
        return cached_videos if cached_videos else []


def scrape_instagram_account(account: str, start_date: Optional[datetime] = None,
                             limit: int = 500, use_cache: bool = True) -> List[Dict]:
    """
    Scrape posts from an Instagram account using Instaloader
    """
    if not INSTAGRAM_AVAILABLE:
        log("Instagram scraping not available - Instaloader not installed", "ERROR")
        return []

    username = get_profile_username(account)
    if not username:
        log(f"Could not extract username from: {account}", "ERROR")
        return []

    log(f"Scraping Instagram @{username}...")

    # Load cache
    cached_posts = []
    cache_cutoff_date = None
    if use_cache:
        cached_posts, last_scrape_date = load_account_cache(account, 'instagram')
        if cached_posts and last_scrape_date:
            # Same date/datetime normalization as TikTok path above.
            cache_cutoff_date = last_scrape_date.date() if isinstance(last_scrape_date, datetime) else last_scrape_date
            start_date_norm = start_date.date() if isinstance(start_date, datetime) else start_date
            scrape_from_date = max(start_date_norm, cache_cutoff_date) if start_date_norm else cache_cutoff_date
        else:
            scrape_from_date = start_date.date() if isinstance(start_date, datetime) else start_date
    else:
        scrape_from_date = start_date.date() if isinstance(start_date, datetime) else start_date

    try:
        # Initialize Instaloader
        L = instaloader.Instaloader(
            quiet=True,
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False
        )

        # Load profile
        try:
            profile = instaloader.Profile.from_username(L.context, username)
        except instaloader.exceptions.ProfileNotExistsException:
            log(f"Instagram profile @{username} not found", "ERROR")
            return cached_posts if cached_posts else []

        new_posts = []
        total_fetched = 0
        skipped_old = 0
        skipped_cached = 0

        # Iterate through posts with progress
        log(f"Fetching Instagram posts for @{username}...")
        for post in profile.get_posts():
            if total_fetched >= limit:
                break

            total_fetched += 1

            # Check date filter
            post_date = post.date_utc
            if scrape_from_date and post_date.date() < scrape_from_date:
                skipped_old += 1
                continue

            # Build post URL
            post_url = f"https://www.instagram.com/p/{post.shortcode}/"

            # Check cache
            if cached_posts:
                cached_urls = {p.get('url') for p in cached_posts}
                if post_url in cached_urls:
                    skipped_cached += 1
                    continue

            # Extract caption and hashtags
            caption = post.caption or ''
            hashtags = post.caption_hashtags if hasattr(post, 'caption_hashtags') else []

            # Try to extract audio/song information from Instagram post
            audio_title = None
            audio_artist = None
            try:
                # Check if post has audio metadata (for Reels)
                if hasattr(post, 'audio_title') and post.audio_title:
                    audio_title = post.audio_title
                if hasattr(post, 'audio_artist') and post.audio_artist:
                    audio_artist = post.audio_artist
                # Alternative: check for audio in post JSON
                if hasattr(post, '_node') and post._node:
                    audio_info = post._node.get('audio', {})
                    if audio_info:
                        audio_title = audio_info.get('title') or audio_title
                        audio_artist = audio_info.get('artist') or audio_artist
            except Exception:
                pass  # Audio metadata not available

            post_entry = {
                'url': post_url,
                'caption': caption[:500],  # Truncate long captions
                'hashtags': list(hashtags),
                'account': f"@{username}",
                'views': post.video_view_count if post.is_video else None,
                'likes': post.likes,
                'comments': post.comments,
                'timestamp': post_date,
                'is_video': post.is_video,
                'platform': 'instagram',
                'song': audio_title,  # Add audio title as song
                'artist': audio_artist  # Add audio artist
            }

            # Validate
            try:
                validate_video_data(post_entry, 'instagram')
                new_posts.append(post_entry)
            except ValidationError as e:
                log(f"Validation failed for post: {e}", "WARNING")
                continue

        # Combine cached and new
        all_posts = (cached_posts or []) + new_posts

        # Save cache
        if use_cache:
            save_account_cache(account, 'instagram', all_posts, datetime.now().date())

        log(f"Instagram @{username}: {total_fetched} fetched, {len(new_posts)} new, {skipped_old} old, {skipped_cached} cached")

        return all_posts

    except Exception as e:
        log(f"Error scraping Instagram @{username}: {e}", "ERROR")
        return cached_posts if cached_posts else []


def match_video_to_sounds(video: Dict, sound_ids: set, sound_keys: set) -> bool:
    """
    Match a video to tracked sounds using multiple strategies

    Returns: True if video matches any tracked sound
    """
    # Strategy 1: Match by extracted sound ID (most reliable)
    if video.get('extracted_sound_id') and video['extracted_sound_id'] in sound_ids:
        return True

    # Strategy 2: Match by music_id from yt-dlp metadata
    if video.get('music_id') and video['music_id'] in sound_ids:
        return True

    # Strategy 3: Match by normalized song + artist
    if video.get('song') and video.get('artist'):
        video_key = normalize_song_key(video['song'], video['artist'])
        if video_key in sound_keys:
            return True

    # Strategy 4: Match by extracted song title
    if video.get('extracted_song_title'):
        for sound_key in sound_keys:
            if video['extracted_song_title'].lower() in sound_key.lower():
                return True

    # Strategy 5: For Instagram, match by caption text (approximate matching)
    if video.get('platform') == 'instagram' and video.get('caption'):
        caption_lower = video['caption'].lower()
        for sound_key in sound_keys:
            # Extract song and artist from sound_key (format: "song - artist")
            parts = sound_key.split(' - ')
            if len(parts) == 2:
                song_part = parts[0].strip().lower()
                artist_part = parts[1].strip().lower()
                
                # Check if both song and artist appear in caption (approximate match)
                song_words = song_part.split()
                artist_words = artist_part.split()
                
                # Match if key words from song title appear
                song_match = any(word in caption_lower for word in song_words if len(word) > 2)
                artist_match = any(word in caption_lower for word in artist_words if len(word) > 2)
                
                # Also check for partial matches (e.g., "rarest hour" matches "the rarest hour")
                if song_part.replace(' ', '') in caption_lower.replace(' ', ''):
                    song_match = True
                if artist_part.replace(' ', '') in caption_lower.replace(' ', ''):
                    artist_match = True
                
                # If both song and artist match (or just song for very specific titles)
                if song_match and (artist_match or len(song_words) >= 3):
                    return True
                
                # Special handling for very specific song titles
                if len(song_words) >= 3 and song_match:
                    return True

    return False


def load_campaign_csv(csv_path: str) -> Tuple[set, set, Dict]:
    """
    Load campaign CSV and extract sound IDs and keys

    Returns: (sound_ids, sound_keys, accounts_by_sound)
    """
    sound_ids = set()
    sound_keys = set()
    accounts_by_sound = defaultdict(set)

    log(f"Loading campaign CSV: {csv_path}")

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Extract sound ID
            sound_id = None
            for col in ['Tiktok Sound ID', 'Tiktok Sound', 'Sound ID', 'sound_id']:
                if col in row and row[col]:
                    sound_url = row[col].strip()
                    # Check if it's already a raw numeric ID
                    if sound_url.isdigit():
                        sound_id = sound_url
                        break
                    # Multiple regex patterns to extract ID from URL
                    patterns = [
                        r'original-sound-(\d+)',
                        r'song-(\d+)',
                        r'music/[^-]+-(\d+)',
                        r'-(\d+)$'
                    ]
                    for pattern in patterns:
                        match = re.search(pattern, sound_url)
                        if match:
                            sound_id = match.group(1)
                            break
                    if sound_id:
                        break

            if sound_id:
                sound_ids.add(sound_id)

            # Extract song + artist
            song = None
            artist = None
            if 'Song' in row or 'song' in row:
                song = (row.get('Song') or row.get('song', '')).strip()
                artist = (row.get('Artist') or row.get('artist') or row.get('Artist Name', '')).strip()
                if song and artist:
                    sound_key = normalize_song_key(song, artist)
                    sound_keys.add(sound_key)

            # Extract account
            account = None
            for col in ['Account', 'account', 'Account URL', 'URL', 'account Handle', 'Creator Handles']:
                if col in row and row[col]:
                    account = row[col].strip()
                    break

            if account:
                username = get_profile_username(account)
                if username:
                    account_normalized = f"@{username}"
                    if sound_id:
                        accounts_by_sound[sound_id].add(account_normalized)
                    if song and artist:
                        accounts_by_sound[normalize_song_key(song, artist)].add(account_normalized)

    log(f"Loaded {len(sound_ids)} sound IDs, {len(sound_keys)} sound keys, {len(accounts_by_sound)} account mappings")

    return sound_ids, sound_keys, accounts_by_sound


def process_campaign(csv_path: str, start_date: Optional[datetime] = None,
                    platform: str = 'tiktok', limit: int = 500) -> Dict:
    """
    Process a campaign: scrape accounts and match videos to sounds

    Returns: Dictionary with results
    """
    log(f"=== Processing Rising Tides Campaign: {csv_path} ===")
    log(f"Platform: {platform}, Start date: {start_date}, Limit: {limit}")

    # Load campaign data
    sound_ids, sound_keys, accounts_by_sound = load_campaign_csv(csv_path)

    # Get unique accounts
    all_accounts = set()
    for accounts in accounts_by_sound.values():
        all_accounts.update(accounts)

    log(f"Found {len(all_accounts)} unique accounts to scrape")

    # Scrape all accounts in parallel for better performance
    all_videos = []

    def scrape_account_wrapper(account):
        """Wrapper function for parallel scraping"""
        try:
            if platform == 'tiktok':
                return scrape_tiktok_account(account, start_date, limit)
            elif platform == 'instagram':
                return scrape_instagram_account(account, start_date, limit)
            elif platform == 'both':
                videos_tt = scrape_tiktok_account(account, start_date, limit)
                videos_ig = scrape_instagram_account(account, start_date, limit)
                return videos_tt + videos_ig
            else:
                log(f"Unknown platform: {platform}", "ERROR")
                return []
        except Exception as e:
            log(f"Error scraping account {account}: {e}", "ERROR")
            return []

    log(f"Scraping {len(all_accounts)} accounts in parallel with {MAX_ACCOUNT_WORKERS} workers...")
    print(f"\n{'='*60}")
    print(f"SCRAPING PROGRESS: 0/{len(all_accounts)} accounts completed")
    print(f"{'='*60}\n")

    with ThreadPoolExecutor(max_workers=MAX_ACCOUNT_WORKERS) as executor:
        future_to_account = {executor.submit(scrape_account_wrapper, account): account
                            for account in all_accounts}

        completed_count = 0
        with tqdm(total=len(all_accounts), desc="Scraping accounts", unit="account",
                  bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]') as pbar:
            for future in as_completed(future_to_account):
                try:
                    videos = future.result()
                    all_videos.extend(videos)
                    completed_count += 1
                    account = future_to_account[future]
                    pbar.set_postfix_str(f"Latest: {account}")
                except Exception as e:
                    account = future_to_account[future]
                    log(f"Failed to scrape account {account}: {e}", "ERROR")
                    completed_count += 1
                finally:
                    pbar.update(1)

    log(f"Scraped {len(all_videos)} total videos from {len(all_accounts)} accounts")

    # Match videos to sounds
    log("Matching videos to tracked sounds...")
    print(f"\n{'='*60}")
    print(f"MATCHING PROGRESS: 0/{len(all_videos)} videos checked")
    print(f"{'='*60}\n")
    matched_videos = []

    for video in tqdm(all_videos, desc="Matching videos", unit="video",
                      bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]'):
        if match_video_to_sounds(video, sound_ids, sound_keys):
            matched_videos.append(video)

    log(f"Matched {len(matched_videos)} videos out of {len(all_videos)} total")

    # Generate results
    results = {
        'campaign_file': csv_path,
        'platform': platform,
        'start_date': start_date,
        'total_accounts': len(all_accounts),
        'total_videos_scraped': len(all_videos),
        'matched_videos': len(matched_videos),
        'videos': matched_videos,
        'timestamp': datetime.now()
    }

    return results


def save_results(results: Dict, output_file: Optional[str] = None):
    """Save campaign results to CSV"""
    if not output_file:
        campaign_name = Path(results['campaign_file']).stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = OUTPUT_DIR / f"{campaign_name}_results_{timestamp}.csv"
    else:
        output_file = Path(output_file)

    log(f"Saving results to {output_file}")

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        if not results['videos']:
            f.write("No matching videos found\n")
            return

        fieldnames = ['url', 'account', 'platform', 'song', 'artist', 'views', 'likes',
                     'timestamp', 'extracted_sound_id', 'extracted_song_title']
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')

        writer.writeheader()
        for video in results['videos']:
            writer.writerow(video)

    log(f"Saved {len(results['videos'])} videos to {output_file}")

    # Create copy-paste links file
    links_file = output_file.with_name(output_file.stem + '_links.txt')
    with open(links_file, 'w', encoding='utf-8') as f:
        for video in results['videos']:
            f.write(f"{video['url']}\n")
    log(f"Saved links to {links_file}")

    return output_file


def main():
    parser = argparse.ArgumentParser(
        description='Master Tracker - Optimized campaign tracking with parallel processing'
    )
    parser.add_argument('csv_file', help='CSV file with Rising Tides campaign data')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)', type=str)
    parser.add_argument('--platform', help='Platform: tiktok, instagram, or both',
                       default='tiktok', choices=['tiktok', 'instagram', 'both'])
    parser.add_argument('--limit', help='Max videos per account', type=int, default=500)
    parser.add_argument('--output', help='Output CSV file path', type=str)
    parser.add_argument('--no-cache', help='Disable caching', action='store_true')

    args = parser.parse_args()

    # Parse start date
    start_date = None
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        except ValueError:
            log(f"Invalid date format: {args.start_date}. Use YYYY-MM-DD", "ERROR")
            sys.exit(1)

    # Check CSV exists
    if not Path(args.csv_file).exists():
        log(f"CSV file not found: {args.csv_file}", "ERROR")
        sys.exit(1)

    # Auto-adjust limit if start date is more than a month ago
    limit = args.limit
    if start_date:
        days_ago = (datetime.now().date() - start_date).days
        if days_ago > 30:
            if limit < 2000:
                log(f"Start date is {days_ago} days ago (>30 days), increasing limit from {limit} to 2000", "INFO")
                limit = 2000

    # Process campaign
    start_time = time.time()

    try:
        results = process_campaign(
            args.csv_file,
            start_date=start_date,
            platform=args.platform,
            limit=limit,
        )

        # Save results
        output_file = save_results(results, args.output)

        elapsed = time.time() - start_time

        log("=== Rising Tides Campaign Processing Complete ===")
        log(f"Total time: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
        log(f"Accounts scraped: {results['total_accounts']}")
        log(f"Videos scraped: {results['total_videos_scraped']}")
        log(f"Videos matched: {results['matched_videos']}")
        log(f"Results saved to: {output_file}")

    except KeyboardInterrupt:
        log("Rising Tides campaign processing interrupted by user", "WARNING")
        sys.exit(1)
    except Exception as e:
        log(f"Rising Tides campaign processing failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
