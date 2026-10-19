time:  [5:13pm] [10-19-26]
agent: [codex desktop] [gpt-6.1-sol]
worktree: [codex/scraper-runtime-selfheal]
type:  [bug report]: Campaign Hub unattended Python drift recovery
area:  [backend]: prior distribution integrity

Independent exact-head review found that same-source Python drift could follow a syntactically valid but altered stored freeze and install different packages. Held-lock recovery now compares the prior venv's actual pip freeze byte-for-byte with its stored exact-version freeze before using it; an uninspectable or mismatched prior runtime stops for manual reconciliation. A synthetic altered exact-version freeze is refused with the active symlink unchanged. Mac mini focused tests: 15 passed; syntax and diff checks passed. Draft PR #277 still awaits independent review of this integrated head, hosted CI, controlled deployment, and natural scheduled delivery evidence. No real scrape, merge, or deployment occurred.
