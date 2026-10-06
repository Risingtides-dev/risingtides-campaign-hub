# railway-watchdog

Brings stopped Railway services back on its own.

On 2026-10-06 at 7:43 AM ET, Railway stopped **every** service in the risingtides-dev workspace
at once (24 services across 10 projects, including Campaign Hub and Content Lab). Railway had
no incident that day, so the stop came from the account itself (most likely the workspace's
$100 hard spending cap, or billing). Nothing restarted them, so the sites stayed down for hours.

This is a tiny Cloudflare Worker (Rust, workers-rs). It runs **outside** Railway on purpose:
anything inside Railway is stopped along with everything else.

## What it does, every minute

1. Asks Railway (one API call) for the state of every service in the watched environments.
2. Checks the health URLs it was given (Campaign Hub: `/health`).
3. If something is down:
   - **Spending cap first.** If Railway says the workspace is over its cap, it restarts
     **nothing** and opens one alert with the numbers (used $X of a $Y limit). Restarting
     would only be stopped again or run up the bill. Once the cap is raised, it carries on.
   - **Databases first.** Code services wait until the databases (image-based services such
     as Postgres) in their environment are up.
   - **First try: restore.** It redeploys the exact deployment that was running, from the
     already-built image (no rebuild, no surprise code change). Failed builds are skipped.
   - **Next tries: fresh build** of the service's latest code.
   - **A running service that fails its health check 3 times in a row** is restarted.
4. Limits so it can never loop or run up a bill: 10 minutes between tries on one service,
   3 tries per service in 2 hours (then it pages a person and stops), and at most 10 actions
   a minute and 40 an hour across everything.
5. Alerts: one GitHub issue per incident in `ecfromthedc/fleet-alerts` (the repo Instinct
   watches to text Eric), updated as it works, then closed with "Everything is running again"
   and how long it took. Without `GITHUB_TOKEN`, alerts are only written to the Worker log.

It never deletes, scales, or changes settings. The only Railway calls that change anything
are: redeploy a past deployment, deploy a service, restart a deployment.

## What it watches

The `WATCH` var in `wrangler.toml`: every production environment that was running on
2026-10-06. Per environment you can add `health` (service name -> URL) and `skip` (service
names never to touch). A new project is not watched until you add its environment id.

## Install

```sh
cd tools/railway-watchdog
wrangler kv namespace create WATCHDOG          # put the printed id into wrangler.toml
wrangler deploy
wrangler secret put RAILWAY_TOKEN              # see below
wrangler secret put GITHUB_TOKEN               # optional: the token fleet-deadman uses for fleet-alerts
```

`RAILWAY_TOKEN` must be a **workspace token** for risingtides-dev, or an account token of a
member (Railway: Account settings, Tokens). A project token cannot see other projects. A
member's token can read the spending cap (checked 2026-10-06). If a token ever cannot, the
watchdog still restores services; it just cannot tell a cap from other stops, and the
3-try limit is the backstop.

## Pause it (planned maintenance)

If you stop a service on purpose, the watchdog will bring it back. Pause it first:

```sh
wrangler kv key put paused 1 --binding WATCHDOG --remote      # pause
wrangler kv key delete paused --binding WATCHDOG --remote     # resume
```

Or add the service to `skip` in `WATCH` for good.

## Watch it

```sh
wrangler tail railway-watchdog
wrangler kv key get state --binding WATCHDOG --remote         # tries, open incident, unsent alerts
```

## Layout and tests

- `src/core.rs`: every decision (pure, no I/O). `src/lib.rs`: Worker glue (Railway, KV, GitHub).
- `cargo test`: unit tests, including a replay of the 2026-10-06 outage.
- `bash tests/smoke.sh`: end-to-end against `wrangler dev` and `tests/mock.mjs` (a fake Railway,
  health URL and GitHub). Fake secrets only. Needs wrangler, node, jq, worker-build. ~2.5 min.
- Dry run against the real Railway (read-only): save the Worker's `projects` query answer to a
  file, then `SNAPSHOT=file.json WATCH="..." cargo test dry_run -- --ignored --nocapture`.
