# railway-watchdog

Brings stopped Railway services back on its own.

On 2026-10-06 at 7:43 AM ET, Railway stopped **every** service in the risingtides-dev workspace
at once (24 services across 10 projects, including Campaign Hub and Content Lab). Railway had
no incident that day; the cause was the workspace's $100 hard spending cap (it stopped
everything again at 10:24 AM ET while Railway reported the workspace over the limit). Nothing
restarted the services, so the sites stayed down until someone redeployed them by hand.

This is a tiny Cloudflare Worker (Rust, workers-rs). It runs **outside** Railway on purpose:
anything inside Railway is stopped along with everything else.

## What it does, every minute

1. Takes a lease so only one run works at a time (a second, overlapping run stands down).
2. Asks Railway for the state of every service in the watched environments (paged).
3. Checks the health URLs it was given (Campaign Hub: `/health`).
4. If something is down:
   - **Spending cap first, and it fails closed.** If Railway says the workspace is over its
     cap, it restarts **nothing** and opens one alert with the numbers (used $X of a $Y
     limit). If Railway will **not say** (an error, a token without billing access, a
     half-answer), it also restarts nothing, and alerts after 3 such runs in a row.
     Restarting into a cap would only be stopped again or run up the bill.
   - **Databases first.** Code services wait until the databases (image-based services such
     as Postgres) in their environment are up.
   - **First try: restore.** It redeploys the exact deployment that was running, from the
     already-built image (no rebuild, no surprise code change). Failed builds are skipped.
   - **Next tries: fresh build** of the service's latest code.
   - **A running service that fails its health check 3 times in a row** is restarted.
5. It saves what it decided **before** it acts, so a later or overlapping run always sees
   the tries already made.
6. It never says "everything is fine" unless it can see every watched environment. If it sees
   no services, misses a watched environment, or gets a cut-off list, an open incident stays
   open and it alerts after 3 runs. If it cannot read Railway at all, it alerts after 5 runs.
7. Limits so it can never loop or run up a bill: 10 minutes between tries on one service,
   3 tries per service in 2 hours (then it pages a person and stops), and at most 10 actions
   a minute and 40 an hour across everything.
8. Alerts: one GitHub issue per incident in `ecfromthedc/fleet-alerts` (the repo Instinct
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
wrangler deploy                                # also creates the BRAIN Durable Object
wrangler secret put RAILWAY_TOKEN              # see below
wrangler secret put GITHUB_TOKEN               # optional: the token fleet-deadman uses for fleet-alerts
```

`RAILWAY_TOKEN` must be a **workspace token** for risingtides-dev, or an account token of a
member (Railway: Account settings, Tokens). A project token cannot see other projects. The
token **must be able to read the spending cap** (a member's token can, checked 2026-10-06):
without that, the watchdog restarts nothing, by design.

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
wrangler kv key get state --binding WATCHDOG --remote         # read-only copy: tries, incident, alerts
```

## Where the state lives

The saved state (tries, open incident, unsent alerts) and the one-run-at-a-time lease live in
a Durable Object (`BRAIN`). Its storage is strongly consistent; KV is not (a KV write can take
up to a minute to show up elsewhere, which would let the next run miss a try). KV holds only
the `paused` switch and a read-only copy of the state for people.

## Layout and tests

- `src/core.rs`: every decision (pure, no I/O). `src/lib.rs`: Worker glue (Railway, the
  Durable Object, KV, GitHub).
- `cargo test`: unit tests, including a replay of the 2026-10-06 outage, an unreadable cap,
  an empty view, read failures, two overlapping runs, and pagination. CI runs these plus a
  wasm32 compile on every change (`.github/workflows/railway-watchdog.yml`).
- `bash tests/smoke.sh`: end-to-end against `wrangler dev` and `tests/mock.mjs` (a fake Railway,
  health URL and GitHub). Fake secrets only. Needs wrangler, node, jq, worker-build. ~3 min.
- Dry run against the real Railway (read-only): save the Worker's `projects` query answer to a
  file, then `SNAPSHOT=file.json WATCH="..." cargo test dry_run -- --ignored --nocapture`.
