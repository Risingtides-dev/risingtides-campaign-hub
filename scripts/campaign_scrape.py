#!/usr/bin/env python3
"""Per-campaign delta scrape.

Workflow:
  1. Pull campaign + creators from Hub Postgres (via railway run).
  2. Find the linked TidesTracker UUID and pull the live submission list from
     https://risingtides-tracker.com/api/public/<uuid> — that is the source of
     truth for "what's already uploaded."
  3. Compute per-creator deficit (posts_owed - posts_in_tidestracker).
  4. For creators with deficit (or in ALWAYS_INCLUDE), scrape their TikTok
     account back to the campaign start_date, verify each post uses the
     campaign sound_id, and filter out URLs already in TidesTracker.
  5. Output a brief summary + copy-paste link block of NEW URLs only.

Run via:
    cd ~/Projects/risingtides-campaign-hub && \
        railway run --service Postgres python3 scripts/campaign_scrape.py <slug>

ALWAYS_INCLUDE: creators paid on a per-view basis (not per-post), so we
always scrape them regardless of deficit. Per Jake.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

# Per-view creators that should always be scraped
ALWAYS_INCLUDE: dict[str, set[str]] = {
    "emei_night_at_the_opera": {"amardubaii"},
}

PLAYLIST_END = 250         # how many recent posts per account to inspect
                            # (prolific creators can post 60+ in a single week)
META_WORKERS = 5
META_TIMEOUT = 45
PLAYLIST_TIMEOUT = 120


def _db():
    return psycopg2.connect(os.environ["DATABASE_PUBLIC_URL"], connect_timeout=15)


def _http_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e:
        print(f"  ! HTTP {url} → {e}", file=sys.stderr)
        return None


def normalize_url(u: str) -> str:
    """Canonicalize a TikTok URL so we can dedupe across www/no-www and trailing slashes."""
    if not u:
        return ""
    u = u.split("?")[0].rstrip("/")
    u = u.replace("https://www.tiktok.com", "https://tiktok.com")
    return u


def get_campaign(slug: str) -> dict | None:
    with _db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM campaigns WHERE slug=%s", (slug,))
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            "SELECT username, posts_owed, posts_done, posts_matched, status, paid, platform "
            "FROM creators WHERE campaign_id=%s AND (status IS NULL OR status NOT IN ('removed','deleted')) "
            "ORDER BY username",
            (row["id"],),
        )
        creators = [dict(r) for r in cur.fetchall()]
    out = dict(row)
    out["creators"] = creators
    return out


def get_tracker_uuid(slug: str) -> str | None:
    """Find the TidesTracker UUID linked to this campaign."""
    with _db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT tracker_id, created_at FROM tracker_campaign_links "
            "WHERE campaign_slug=%s ORDER BY created_at DESC",
            (slug,),
        )
        rows = cur.fetchall()
    if not rows:
        return None
    return rows[0]["tracker_id"]


def get_tidestracker_videos(tracker_uuid: str) -> list[dict]:
    data = _http_json(f"https://risingtides-tracker.com/api/public/{tracker_uuid}") or {}
    return data.get("videos") or []


def scrape_account_recent(username: str, start_date: str) -> list[dict]:
    """yt-dlp --flat-playlist for one account, filtered to posts on/after start_date.
    Returns entries with id, url, ts (Unix from TikTok video id)."""
    url = f"https://www.tiktok.com/@{username}"
    try:
        proc = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", "--playlist-end", str(PLAYLIST_END),
             "--no-warnings", url],
            capture_output=True, text=True, timeout=PLAYLIST_TIMEOUT,
        )
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout or "{}")
    except Exception:
        return []
    entries = data.get("entries") or []
    cutoff_ts = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    out: list[dict] = []
    for e in entries:
        vid = e.get("id") or ""
        try:
            ts = int(vid) >> 32
        except ValueError:
            continue
        if ts < cutoff_ts:
            continue
        out.append({
            "id": vid,
            "url": f"https://tiktok.com/@{username}/video/{vid}",
            "ts": ts,
        })
    return out


def fetch_sound_meta(video_url: str) -> dict:
    try:
        proc = subprocess.run(
            ["yt-dlp", "--no-warnings", "--skip-download", "-J", video_url],
            capture_output=True, text=True, timeout=META_TIMEOUT,
        )
        if proc.returncode != 0:
            return {"url": video_url, "error": "yt-dlp non-zero"}
        d = json.loads(proc.stdout or "{}")
        # The TikTok extractor populates `track` and sometimes a music id under
        # `music_track_id` or in the raw `aweme_detail.music.id`. We rely on the
        # title because there isn't a stable ID field across yt-dlp versions.
        return {
            "url": video_url,
            "track": (d.get("track") or "").strip(),
            "artist": (d.get("artist") or "").strip(),
        }
    except Exception as e:
        return {"url": video_url, "error": str(e)[:120]}


def _log(*a, **kw):
    """Progress messages go to stderr so the final report on stdout is clean markdown."""
    print(*a, **kw, file=sys.stderr, flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: campaign_scrape.py <slug>")
        return 2
    slug = sys.argv[1]

    _log(f"# Campaign: {slug}")
    camp = get_campaign(slug)
    if not camp:
        print(f"⚠️  No campaign with slug {slug}")
        return 1

    title = camp.get("title") or slug
    sound_id = camp.get("sound_id") or ""
    start_date = camp.get("start_date") or ""
    _log(f"# {title}")
    _log(f"# sound_id={sound_id}  start={start_date}  status={camp.get('status')}")

    tracker_uuid = get_tracker_uuid(slug)
    if not tracker_uuid:
        _log("⚠️  No TidesTracker link found — falling back to matched_videos only.")
        tracker_videos = []
    else:
        _log(f"# tracker uuid={tracker_uuid}")
        tracker_videos = get_tidestracker_videos(tracker_uuid)
    _log(f"# TidesTracker has {len(tracker_videos)} live submissions")

    # Build the set of normalized URLs already in TidesTracker
    tracker_urls_norm = {normalize_url(v.get("video_url", "")) for v in tracker_videos}
    tracker_urls_norm.discard("")

    # Count tracker submissions per username
    tracker_by_user: dict[str, int] = defaultdict(int)
    for v in tracker_videos:
        u = (v.get("username") or "").lower()
        if u:
            tracker_by_user[u] += 1

    # Build creator-by-creator picture
    creators = camp.get("creators") or []
    always = {u.lower() for u in ALWAYS_INCLUDE.get(slug, set())}
    rows: list[dict] = []
    for c in creators:
        u = (c.get("username") or "").lower()
        owed = int(c.get("posts_owed") or 0)
        in_tracker = tracker_by_user.get(u, 0)
        deficit = owed - in_tracker
        should_scrape = (deficit > 0) or (u in always)
        rows.append({
            "username": u, "owed": owed,
            "tracker": in_tracker, "deficit": deficit,
            "always": u in always, "should_scrape": should_scrape,
        })
    # Any TidesTracker users not in the creator list (likely internal accounts)
    booked = {r["username"] for r in rows}
    for u in tracker_by_user:
        if u not in booked:
            rows.append({
                "username": u, "owed": 0,
                "tracker": tracker_by_user[u], "deficit": 0,
                "always": False, "should_scrape": False,
            })

    to_scrape = [r["username"] for r in rows if r["should_scrape"]]
    confirmed: list[dict] = []
    rejected: list[dict] = []

    if to_scrape:
        _log(f"### Scraping {len(to_scrape)} creator(s) back to {start_date}")
        # Gather candidate URLs from each account
        candidates: list[tuple[str, str]] = []
        for u in to_scrape:
            entries = scrape_account_recent(u, start_date)
            kept = [e for e in entries if normalize_url(e["url"]) not in tracker_urls_norm]
            _log(f"  @{u:<28}  window: {len(entries)}  not-in-tracker: {len(kept)}")
            for e in kept:
                candidates.append((u, e["url"]))

        if candidates:
            expected_song = re.sub(r"\s+", " ", (camp.get("song") or camp.get("name") or "").strip().lower())
            # Normalize campaign artist to a TikTok-handle shape: lowercase, no spaces/punct
            raw_artist = (camp.get("artist") or "").strip().lower()
            expected_artist_handle = re.sub(r"[^a-z0-9]+", "", raw_artist)
            # Generic platform labels TikTok uses for creator-uploaded audio.
            # If yt-dlp's `track` is one of these, it carries no song-identity
            # information — we MUST verify via artist handle instead.
            GENERIC_TRACK = {
                "original sound", "original audio", "originalton",
                "sonido original", "audio originale", "som original",
                "오리지널 사운드", "オリジナル楽曲",
            }
            song_is_generic = expected_song in GENERIC_TRACK
            _log(f"### Verifying {len(candidates)} candidate(s) vs song={expected_song!r} / artist_handle={expected_artist_handle!r}{' [song is generic — require artist match]' if song_is_generic else ''}")
            started = time.time()
            with ThreadPoolExecutor(max_workers=META_WORKERS) as ex:
                futs = {ex.submit(fetch_sound_meta, u): (acct, u) for acct, u in candidates}
                for fut in as_completed(futs):
                    acct, url = futs[fut]
                    r = fut.result()
                    track = (r.get("track") or "").strip().lower()
                    artist = (r.get("artist") or "").strip().lower()
                    artist_handle = re.sub(r"[^a-z0-9]+", "", artist)
                    # Match if either:
                    #  (a) track matches the campaign song name (official-sound posts), OR
                    #  (b) the audio uploader's handle matches the campaign artist (original-sound posts)
                    # When yt-dlp's `track` is a generic platform label (e.g. "original sound"),
                    # treat it as carrying no song identity — REQUIRE artist match.
                    track_is_generic = track in GENERIC_TRACK
                    if song_is_generic or track_is_generic:
                        song_match = False
                    else:
                        song_match = bool(track and expected_song and (
                            track == expected_song or expected_song in track or track in expected_song
                        ))
                    # Require both sides to be ≥4 chars after normalization so that
                    # Unicode/punctuation handles that collapse to 1–2 ascii chars
                    # (e.g. "𝓋ie⁸¹⭑.ᐟ" → "ie") can't substring-match a real artist.
                    artist_match = bool(
                        expected_artist_handle and artist_handle
                        and len(expected_artist_handle) >= 4
                        and len(artist_handle) >= 4
                        and (artist_handle == expected_artist_handle
                             or expected_artist_handle in artist_handle
                             or artist_handle in expected_artist_handle)
                    )
                    ok = song_match or artist_match
                    (confirmed if ok else rejected).append({
                        "username": acct, "url": url,
                        "track": r.get("track"), "artist": r.get("artist"),
                        "match_via": "song" if song_match else ("artist" if artist_match else None),
                        "error": r.get("error"),
                    })
            _log(f"  done in {time.time()-started:.0f}s  confirmed={len(confirmed)}  rejected={len(rejected)}")

    # Confirmed count per user (used by both the report and the followup file)
    confirmed_by_user: dict[str, int] = defaultdict(int)
    for v in confirmed:
        confirmed_by_user[v["username"]] += 1

    # ---------- FINAL REPORT (stdout, in display order) ----------
    print(f"## {title}")
    print(f"_slug `{slug}` · sound `{sound_id}` · started {start_date} · {len(tracker_videos)} in tracker_")
    print()

    # 1. NEW LINKS — flat copy-paste block at the top
    print(f"### 🆕 New posts not yet in TidesTracker ({len(confirmed)})")
    print()
    if confirmed:
        print("```")
        # sort by username then by URL for stable ordering
        for v in sorted(confirmed, key=lambda x: (x["username"], x["url"])):
            print(v["url"])
        print("```")
    else:
        print("_None — see follow-up list below._")
    print()

    # 1b. Sound diversity flag — if any matches came via the artist-handle path
    # (rather than the registered song title), surface them as potential alternate
    # sounds that aren't in campaign.sound_id / campaign.additional_sounds.
    via_artist = [v for v in confirmed if v.get("match_via") == "artist"]
    if via_artist:
        from collections import Counter
        alt_counts = Counter((v.get("track") or "?", v.get("artist") or "?") for v in via_artist)
        print(f"⚠️ **Alternate sound(s) detected** — {len(via_artist)} of {len(confirmed)} confirmed posts matched via the campaign artist's handle, not the registered sound:")
        print()
        for (track, artist), n in alt_counts.most_common():
            print(f"- `{track}` by `{artist}` — {n} post(s)")
        print()
        print(f"_The campaign's registered sound_id is `{sound_id}`. These posts use a different sound but were attributed to the campaign artist. Consider adding to `additional_sounds`._")
        print()

    # 2. Creator status table
    print("### Creator status")
    print()
    print("| Creator | Owed | In tracker | New found | Still owes | Status |")
    print("|---|---:|---:|---:|---:|---|")
    for r in sorted(rows, key=lambda x: (-x["deficit"], x["username"])):
        new_found = confirmed_by_user.get(r["username"], 0)
        if r["always"]:
            still = max(0, r["deficit"] - new_found) if r["deficit"] > 0 else 0
            status = "always scrape (per-view)"
        elif r["deficit"] > 0:
            still = max(0, r["deficit"] - new_found)
            status = "complete" if still == 0 else f"still owes {still}"
        elif r["owed"] == 0:
            still = 0
            status = "internal/bonus"
        else:
            still = 0
            status = "complete"
        print(f"| @{r['username']} | {r['owed']} | {r['tracker']} | {new_found} | {still} | {status} |")
    print()

    # 3. Skipped / no scrape needed note
    if not to_scrape:
        print("_All booked creators already complete in TidesTracker._")

    # Append to follow-up file: creators who still owe after this scrape
    confirmed_by_user: dict[str, int] = defaultdict(int)
    for v in confirmed:
        confirmed_by_user[v["username"]] += 1
    still_owes: list[tuple[str, int, bool]] = []
    for r in rows:
        if r["always"]:
            continue
        if r["deficit"] <= 0:
            continue
        remaining = r["deficit"] - confirmed_by_user.get(r["username"], 0)
        if remaining > 0:
            never_started = (r["tracker"] == 0)
            still_owes.append((r["username"], remaining, never_started))

    followup_path = os.path.expanduser(
        f"~/Documents/Obsidian Vault/Campaigns/follow_ups_"
        f"{datetime.now().strftime('%Y-%m-%d')}.md"
    )
    try:
        with open(followup_path, "a") as f:
            f.write(f"\n## {title}\n")
            f.write(f"_slug: `{slug}` · started {start_date} · {len(tracker_videos)} in tracker_\n\n")
            new_total = sum(confirmed_by_user.values())
            if still_owes:
                f.write("| Creator | Still owes |\n|---|---:|\n")
                for user, n, never in still_owes:
                    note = " (hasn't started)" if never else ""
                    f.write(f"| @{user} | {n}{note} |\n")
            else:
                f.write("_All booked creators complete._\n")
            if new_total:
                top = sorted(confirmed_by_user.items(), key=lambda kv: -kv[1])
                breakdown = ", ".join(f"@{u} ({n})" for u, n in top)
                f.write(f"\n_{new_total} new posts surfaced for upload: {breakdown}_\n")
            f.write("\n---\n")
        print(f"\n_Follow-up appended to: {followup_path}_")
    except OSError as e:
        print(f"\n⚠️ could not append follow-up file: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
