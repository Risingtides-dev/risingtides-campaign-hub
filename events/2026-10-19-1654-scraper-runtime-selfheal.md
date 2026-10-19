_________________________________________________________________________________
time: [4:54pm] [10-19-26] EDT
agent: [codex desktop] [gpt-6.1-sol] [builder and release owner]
worktree: [codex/scraper-runtime-selfheal] /Users/risingtidesdev/dev/rt-scraper-selfheal
type: [bug report]: recover local scraper runtime after base Python drift
area: [backend], [testing], [review]

Six natural Mac mini launchd runs exited before scraping after Homebrew Python changed the immutable runtime fingerprint. The canonical provisioner restored the runtime manually; the next natural scrape remains unverified. This source candidate adds one bounded, locked provision attempt for exact-source Python drift and refuses unsafe stale-lock takeover. Nine focused synthetic runtime/lock tests, zsh syntax checks, and diff checks passed without a real scrape. Independent final-head review, hosted checks, merge, installed-launcher deployment, and a natural-run outcome are still required.
_________________________________________________________________________________
