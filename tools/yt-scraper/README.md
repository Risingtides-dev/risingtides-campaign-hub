# Rising Tides Local yt-dlp Scraper

Standalone Rust CLI for running local TikTok account scrapes through `yt-dlp`.
It is intentionally a wrapper around `yt-dlp`, not a replacement extractor.

Use this when you need a local pull of post links from a known account list:

- paid creator handles for a campaign
- internal Rising Tides page handles
- a combined list filtered to one or more campaign sound IDs

For already-submitted paid posts, prefer the existing Tides Tracker/Cobrand
path in the Flask app. That source already returns submitted links and stats
for linked trackers. This tool is for discovery gaps: posts that have not
landed in Cobrand yet, internal pages, and debugging scrape failures.

## Build

```bash
cargo build --release --manifest-path tools/yt-scraper/Cargo.toml
```

## Basic Usage

Start the GUI:

```bash
cargo run --manifest-path tools/yt-scraper/Cargo.toml -- --gui
```

The default local URL is:

```text
http://127.0.0.1:8787
```

The GUI is a standalone two-pane workbench:

- left pane: Pi Agent chat / command entry
- right pane: live scrape context, run draft, run history, and results

Use a different port:

```bash
cargo run --manifest-path tools/yt-scraper/Cargo.toml -- --gui --port 8790
```

### Real Campaign Hub Data

The right panel hydrates from real Campaign Hub API endpoints through the Rust
server's same-origin proxy. By default it expects the Flask app at:

```text
http://localhost:5055
```

Start Campaign Hub separately, then click **Load Hub Data** in the workbench.
The GUI will load:

- `/api/campaigns`
- `/api/internal/groups`
- `/api/internal/creators`
- `/api/scrape-tasks/queue`

When you click a campaign, the workbench fetches `/api/campaign/<slug>` and
fills the run draft with that campaign's creator accounts, primary sound ID,
additional sounds, and start date. When you click an internal group, it fetches
`/api/internal/groups/<slug>` and fills the account list from real members.

If your Campaign Hub API is not on port 5055:

```bash
CAMPAIGN_HUB_API_URL=http://localhost:8080 \
  cargo run --manifest-path tools/yt-scraper/Cargo.toml -- --gui
```

Run from the CLI:

```bash
cargo run --manifest-path tools/yt-scraper/Cargo.toml -- \
  --account @creator_one \
  --account @creator_two \
  --hours 36 \
  --limit 50
```

With an account file:

```bash
cargo run --manifest-path tools/yt-scraper/Cargo.toml -- \
  --accounts-file accounts.txt \
  --start "2026-05-24 00:00" \
  --end "2026-05-25 23:59" \
  --limit 50
```

Filter to campaign songs by TikTok music/sound ID:

```bash
cargo run --manifest-path tools/yt-scraper/Cargo.toml -- \
  --accounts-file campaign-and-internal-accounts.txt \
  --sound-id 7340478123456789012 \
  --sound-id 7359999999999999999 \
  --hours 72
```

`--sound-id` accepts a raw numeric ID or a TikTok music URL containing the ID.

## Outputs

Default output directory: `output/local-scraper/`

- `scrape_report.json` - structured report with per-account status and grouped songs
- `post_links_by_song.txt` - detailed human-readable report
- `post_links_copy_paste.txt` - links grouped under song headers

## Shared yt-dlp Behavior

The Rust wrapper mirrors the app's shared Python `yt_dlp_runner.py` hardening:

- `--flat-playlist`
- `--dump-json`
- `--playlist-end <limit>`
- Chrome user-agent
- retries and socket timeout
- optional cookies, proxy, and impersonation through env vars

Supported env vars:

```bash
TIKTOK_COOKIES_FILE=/path/to/cookies.txt
TIKTOK_PROXY=http://user:pass@host:port
TIKTOK_USER_AGENT="Mozilla/5.0 ..."
TIKTOK_IMPERSONATE=1
TIKTOK_IMPERSONATE_TARGET=chrome-110
YT_DLP_BIN=/custom/path/to/yt-dlp
```

Keep `--workers` low. The default is `2`, matching the production scraper's
current conservative posture.

## GUI Tool API

The GUI mode exposes a small local API so the embedded Pi Agent, scripts, or a
future MCP client can drive the scraper.

The chat pane launches the local `pi` CLI by default (`/Users/risingtidesdev/bin/pi`
or `PI_AGENT_COMMAND`). Pi receives live Campaign Hub context plus these local
HTTP tool endpoints, and can use bash/curl to inspect Hub data, scan failed
runs, check the untracked queue, and start scrapes when explicitly asked.

Optional Pi env vars:

```bash
PI_AGENT_COMMAND=/Users/risingtidesdev/bin/pi
PI_AGENT_PROVIDER=google
PI_AGENT_MODEL=...
PI_AGENT_THINKING=low
PI_AGENT_TIMEOUT_SECONDS=120
```

Set `PI_AGENT_BACKEND=openai` to bypass the local Pi CLI and use the built-in
OpenAI Chat Completions fallback with `OPENAI_API_KEY`.

```bash
curl http://127.0.0.1:8787/api/tools
```

Start a run through the tool endpoint:

```bash
curl -X POST http://127.0.0.1:8787/api/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "name": "scrape.start",
    "arguments": {
      "accounts_text": "@creator_one\n@creator_two",
      "sound_ids_text": "7340478123456789012",
      "hours": 72,
      "limit": 50,
      "workers": 2
    }
  }'
```

MCP-like JSON-RPC endpoint:

```bash
curl -X POST http://127.0.0.1:8787/api/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Supported tools:

- `scrape.start`
- `scrape.list_runs`
- `scrape.get_run`
- `scrape.copy_links`

## Recommended Link Workflow

1. Paid posts already in Cobrand/Tides Tracker: use Campaign Hub's tracker
   integration and Scrape Tasks queue. That is the cleaner source because it
   reflects what is already submitted.
2. Paid posts not yet submitted: scrape booked creator accounts with this tool,
   filtering by the campaign `sound_id` and `additional_sounds`.
3. Internal posts: scrape internal handles with this tool or the Internal TikTok
   screen. Sound-ID matches can be attached into `matched_videos` by the app's
   internal scrape job.
4. Avoid broad "search TikTok by song" scraping when you already know the paid
   and internal accounts. Account-scoped pulls are cheaper, easier to audit,
   and less likely to trip rate limits.
