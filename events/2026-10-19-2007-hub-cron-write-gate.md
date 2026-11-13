_________________________________________________________________________________
time: [8:07pm] [10-19-26]
agent: [codex desktop] [gpt-6.1-sol]
worktree: [codex/hub-cron-write-gate-20261013]
type: [bug report]: protect manual cron trigger before dispatch
area: [backend], [testing], [review], [writing]

The isolated manual-cron gate requires the existing server-only HUB_WRITE_KEY before request parsing, receipt creation, or dispatch. Unset configuration returns 503 and a missing or incorrect X-Hub-Write-Key returns 401; scheduled jobs are independent. I reconciled this branch with main 5545ac904990e1b9dcedd5a3d3f3ef0d4fd134db, preserved the main scraper-runtime changes and root devlog, and moved the branch's proposed history out of the frozen legacy events.md into this unique entry. Focused cron tests passed 52 with three opt-in PostgreSQL cases skipped. The full Python suite passed 1079 with eight opt-in PostgreSQL cases skipped on the AC-powered Mac mini with sufficient free space; local capacity was below the scraper runtime's 8 GiB floor. Independent pre-commit review found no P1/P2 in the merged auth and cron-recovery paths. This is not merged, deployed, or live verified. Production HUB_WRITE_KEY and a trusted manual-trigger caller remain unverified, so the draft release hold remains.
_________________________________________________________________________________
