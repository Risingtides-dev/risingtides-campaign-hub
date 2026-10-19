time:  [5:11pm] [10-19-26]
agent: [codex desktop] [gpt-6.1-sol]
worktree: [codex/scraper-runtime-selfheal]
type:  [bug report]: Campaign Hub local scraper runtime recovery
area:  [backend]: source attestation and hosted test portability

After independent review found that a source-only release would leave the prior runtime marker stale and block the next Python-drift repair, the branch now attests validated reuse under the normal runner lock without rewriting immutable provision provenance. Held recovery checks the exact current-source attestation and prior freeze hash; absent, corrupt, or failed validation evidence stops recovery. A synthetic test covers source-only advancement, bad attestation, future fingerprint drift, and missing impersonation capability. macOS zsh execution tests now skip on Ubuntu without zsh while portable runtime guard tests remain active. Mac mini focused suite: 15 passed; zsh syntax and diff checks passed. Draft PR #277 remains held for independent review of this integrated head, a passing hosted backend check, deployment parity, and a natural scheduled scrape. No real scrape, merge, or deployment occurred.
