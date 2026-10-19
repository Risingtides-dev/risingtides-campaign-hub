# Event log

## Purpose

Append-only chronological record of meaningful Campaign Hub repository work.

## Ownership

- Each work branch owns its newly created event file; the root AGENTS.md owns current contracts.

## Local Contracts

- Create one new `YYYY-MM-DD-HHMM-<branch-slug>.md` per event, with time, agent, worktree, type, area, outcome, verification, and release limitations.
- Never modify or remove an existing event file. Read history as frozen root `events.md` followed by `events/*.md` in filename order.

## Work Guidance

- Describe observed work and evidence; do not call a candidate merged, deployed, or live verified before those gates occur.

## Verification

- Check that the new filename is unique and `git diff --check` passes.

## Child devlog Index
