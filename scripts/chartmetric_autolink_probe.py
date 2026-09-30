"""Live acceptance probe for Chartmetric's artist-track auto-link resolver."""
from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campaign_manager.services.chartmetric import ChartmetricClient

CASES = [
    ("Espresso", "Sabrina Carpenter", 118981138, "2qSkIjg1o9h3YT9RAgYN75"),
    ("Blinding Lights", "The Weeknd", 27552418, "0VjIjW4GlUZAMYd2vXMi3b"),
]


def norm(value):
    value = unicodedata.normalize("NFKD", value or "").casefold()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in value).split())


def inspect(client, song, artist):
    artists = client._get("/search", {"q": artist, "type": "artists", "limit": 10}) or {}
    exact = [row for row in artists.get("artists", []) if norm(row.get("name")) == norm(artist)]
    found = {}
    for row in exact:
        for page in range(15):
            tracks = client._get(f"/artist/{int(row['id'])}/tracks", {"limit": 100, "offset": page * 100}) or []
            for track in tracks:
                if norm(track.get("name")) == norm(song) and norm(artist) in {norm(n) for n in track.get("artist_names", [])}:
                    stats = track.get("cm_statistics") or {}
                    found[int(track["id"])] = (stats.get("sp_streams"), stats.get("sp_popularity"), track.get("spotify_id"))
            if len(tracks) < 100:
                break
    return found


def main():
    if not os.environ.get("CHARTMETRIC_REFRESH_TOKEN"):
        raise SystemExit("CHARTMETRIC_REFRESH_TOKEN is required")
    client = ChartmetricClient(os.environ["CHARTMETRIC_REFRESH_TOKEN"])
    for song, artist, expected_id, spotify_id in CASES:
        found = inspect(client, song, artist)
        selected = client.search_track(song, artist)
        main_track_ids = client._get(f"/track/spotify/{spotify_id}/get-ids") or []
        resolved = [int(i) for row in main_track_ids for i in row.get("chartmetric_ids", [])]
        print(f"{song} / {artist}: candidates={found}; selected={selected}; expected={expected_id}; main_spotify_resolves={resolved}")
        if selected != expected_id or expected_id not in resolved:
            raise SystemExit(f"Acceptance failed for {song}: expected {expected_id}, got {selected}")


if __name__ == "__main__":
    main()
