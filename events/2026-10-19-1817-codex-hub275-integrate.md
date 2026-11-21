_________________________________________________________________________________
time: [06:17pm] [10-19-26] EDT
agent: [codex] [gpt-6.1-sol] [release owner]
worktree: [codex/hub275-integrate-20261019]
type: [bug report]: Campaign Hub PR #275 tracker rename identity repair
area: [backend], [testing], [review]

An uppercase tracker UUID was canonicalized for the privileged TidesTracker PATCH but written verbatim to Hub tracker_names. This could create a second local cache row, duplicate cron pulls, and leave the lowercase row after a clear. The route now uses the confirmed canonical UUID for local writes and its response. Focused rename/name tests passed 31; the integrated current-main Python suite passed 1088 with 10 optional PostgreSQL/runtime tests skipped. Four branch-only historical entries were moved from frozen events.md to unique events/ files; root devlog records the canonical identity contract. This is an isolated PR candidate only: no production tracker write, remote PR update, merge, deployment, or live readback occurred. PR #275 remains draft until independent exact-tree review, hosted checks, upstream TidesTracker API/schema parity, and browser operator authentication/CSRF are verified. Existing case-variant cache rows, if any, require separately reconciled cleanup.
_________________________________________________________________________________
