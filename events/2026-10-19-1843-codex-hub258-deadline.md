time: [06:43pm] [10-19-26]
agent: [codex desktop] [gpt-6.1-sol]
worktree: [codex/hub258-deadline-20261019]
type: [bug report]: Campaign Hub PR #258 CRM queue source deadline
area: [backend]: CRM edit and exact-page request budget

Bound queued CRM source-ID lookup, edit-window scan and exact-page HTTP request timeouts by the tick's remaining monotonic deadline. A successful response that arrives after the deadline cannot advance a scan cursor or acknowledge a queued page; original queue state remains available for bounded retry. Preserve rate-limit Retry-After handling.

Verification: 102 focused Python tests passed; two PostgreSQL integration cases skipped without TEST_POSTGRES_DATABASE_URL. Slow-source tests exercise scan cursor preservation and exact-page retry. This is a local candidate only: no push, merge, deployment or live proof. Requests' socket inactivity timeout does not provide a strict whole-exchange bound for a progressing body.
