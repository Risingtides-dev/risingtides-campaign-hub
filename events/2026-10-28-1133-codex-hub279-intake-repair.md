_________________________________________________________________________________
time: [11:33am] [10-28-26] EDT
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/hub279-intake-repair]
type: [bug report]: draft PR #279 concurrent CRM intake and undated sound reuse
area: [backend], [testing]

Moved CRM page identity lookup, round slug selection, sound validation, and insertion into one serialized transaction. A repeated CRM page now returns the existing slug without overwriting budget or operator edits; a distinct page gets its own row. Shared-sound round reuse now requires distinct valid start dates so undated or same-day rounds cannot silently share post attribution. Added concurrent SQLite file-database and missing-date regressions. Focused repeat-booking tests passed 17 on the Mac mini's existing test environment. This is an isolated candidate only; no PR push, merge, deployment, provider action, or live verification occurred. John review, independent review, hosted checks, and production parity remain required.
_________________________________________________________________________________
