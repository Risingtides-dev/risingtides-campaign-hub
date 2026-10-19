_________________________________________________________________________________
time: [4:59pm] [10-19-26] EDT
agent: [codex desktop] [gpt-6.1-sol] [builder and release owner]
worktree: [codex/scraper-runtime-selfheal] /Users/risingtidesdev/dev/rt-scraper-selfheal
type: [bug report]: constrain unattended scraper runtime recovery after adversarial review
area: [backend], [testing], [review]

Independent review held the first candidate because automatic loose-range pip resolution could activate unreviewed dependencies, the wrapper build/failure path lacked synthetic coverage, and the preceding fetch had no deadline. The revised candidate uses the prior exact freeze with parity checks, bounds fetch and provisioning, and tests one synthetic scrape on success with no scrape and old-link retention on failed build or timeout. Twelve focused tests passed. This remains an unpushed source candidate; fresh exact-head review, hosted checks, merge, installed-launcher deployment, and natural-run evidence remain required.
_________________________________________________________________________________
