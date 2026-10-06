# Railway watchdog

## Purpose

Bounded optional recovery of stopped Railway services, outside Railway.

## Ownership

- `src/core.rs` owns pure inventory, billing and recovery decisions.
- `src/lib.rs` owns Railway, KV, Durable Object lease/state and alert integration.
- `tests/` owns local mock smoke checks.

## Local Contracts

- An unreadable maintenance-pause value suppresses Railway recovery without spending attempts; successful absent/blank values permit existing recovery and nonblank values pause it. Preserve existing alert delivery and lease release.
- A truncated inventory suppresses recovery before attempt/health accounting because an omitted database may precede a visible application. Retain incidents and bounded blindness alerts. Missing another watched environment alone remains distinct; complete inventories retain database-first recovery.
- Preserve fail-closed billing, saved decisions before mutations, action/attempt limits and existing incident history.
- PR #255 remains a draft under Eric's source-merge/Campaign Hub redeployment hold. Railway token provisioning and watchdog deployment/enablement require their separate authorization. Tests and source publication grant no runtime authority.

## Work Guidance

- Use existing stores, lease endpoints and recovery paths. Keep fake fixture actions separate from real Railway, KV and GitHub effects.

## Verification

- `.github/workflows/railway-watchdog.yml` runs `cargo fmt --check`, `cargo test --locked`, host Clippy with all targets, and wasm32 compile/Clippy with warnings denied.
- `tests/smoke.sh` exercises local Wrangler and fake Railway/health/GitHub fixtures; it does not authorize real recovery.
- A direct-rustc host result does not establish Cargo, Worker-glue, wasm32, smoke or hosted verification.

## Child devlog Index
