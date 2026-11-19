# Event log

## Purpose

Preserved historical dated Campaign Hub work receipts.

## Ownership

- The root AGENTS.md owns current contracts and canonical root `events.md` owns new chronological entries.

## Local Contracts

- Preserve existing dated receipts unchanged. Do not create new dated event files.
- New work appends only to canonical repository-root `events.md`, with 24-hour time and branch attribution; preserve existing locks and hold pending receipts in task scratch when ledger ownership is unavailable.

## Work Guidance

- Describe observed work and evidence; do not call a candidate merged, deployed, or live verified before those gates occur.

## Verification

- `git diff --check`; verify existing dated receipt files remain unchanged.

## Child devlog Index
