_________________________________________________________________________________
time: [15:31] [11-13-26] EST UTC-05:00
agent: [claude] [opus 5.5]
worktree: [codex/hub-cron-write-gate-20261013]
type: [merge]: current main into the manual cron trigger gate
area: [backend], [testing]

Merged main ecab1f3 into this draft as 874822f with no conflicts: AGENTS.md auto-merged, and main does not touch cron.py or its lease tests. The full Python suite on that tree ran under heavy host load (load average above 130): 1,198 passed, 9 skipped, 5 failed. The five are subprocess-timeout tests (tests/test_scheduler_job_lease.py::test_local_file_lock_rejects_second_process and four in tests/test_scraper_runtime_lock.py); they fail the same way on main ecab1f3 in the same environment (main: 1,189 passed, 6 failed, 9 skipped) and again when rerun alone (32 passed, 5 failed, 4 skipped), so hosted CI on the pushed head is the clean signal. The frontend tree is byte-identical to main's (tree 6407baa): on main it builds with tsc and vite, and its vitest files pass 98/98 alone with a 30-second test timeout after timing out at 5 seconds under load. Release holds are unchanged: keep draft. The browser cron button still has no credential path; the shared operator session in its own draft PR provides one, after which this route can take require_operator_or_service_key instead of the key-only check. No merge, deployment or production request was made.
_________________________________________________________________________________
