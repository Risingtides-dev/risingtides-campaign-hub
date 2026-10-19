_________________________________________________________________________________
time: [5:03pm] [10-19-26] EDT
agent: [codex desktop] [gpt-6.1-sol] [builder and release owner]
worktree: [codex/scraper-runtime-selfheal] /Users/risingtidesdev/dev/rt-scraper-selfheal
type: [bug report]: hold source and child-process integrity through scraper recovery
area: [backend], [testing], [review]

Independent review of the bounded candidate found that tracked source could change without HEAD moving during a long build, and that a TERM-ignoring child could outlive a timed-out provisioner after the runner lock was released. The candidate now rechecks tracked source before activation and scraping, kills remaining process-group members after timeout, and retains a lock tombstone if quiescence cannot be proven. Synthetic mutation and orphan-child regressions bring focused tests to fourteen passed without running a real scrape. Full-suite and final exact-head review, hosted checks, merge, installed-launcher deployment, and natural-run proof remain separate gates.
_________________________________________________________________________________
