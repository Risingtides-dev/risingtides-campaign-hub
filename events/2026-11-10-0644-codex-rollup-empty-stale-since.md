_________________________________________________________________________________
time: [06:44am] [11-10-26] EST UTC-05:00
agent: [Codex desktop] [GPT-6]
worktree: [codex/rollup-empty-stale-since-20261110]
type: [bug report]: PR #109 empty-rollup stale_since contract
area: [writing], [review]

PR #109 was already merged, and current main still required a non-null stale_since for empty rollups despite there being no contributing timestamp. The contract now returns null for api or empty sources, excludes empty campaigns from fallback timestamp aggregation, and states the rule in shared conventions, creator/team/RT edge cases, and implementation acceptance criteria. Cached and scraper fallback rollups retain the earliest contributing fallback timestamp. No runtime code changed.

Verification: reviewed all stale_since references for consistency, parsed both fenced JSON examples with Python's json module, and passed git diff --check. The existing command python3 -m pytest -q tests/backend/test_campaign_stats.py could not collect because the local Python 3.14 environment has no pytest module. No new documentation-string tests or dependency installation. Hosted checks remain pending publication; this entry claims no merge, deployment, or live endpoint verification.

Devlog: updated the root AGENTS.md with ownership of the response contract and the corrected empty-source rule. events/AGENTS.md and the Child devlog Index remain unchanged because the log workflow and directory ownership did not change. Existing history and unrelated dirty checkouts were preserved.
_________________________________________________________________________________
