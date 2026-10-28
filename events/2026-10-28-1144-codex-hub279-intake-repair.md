_________________________________________________________________________________
time: [11:44am] [10-28-26] EDT
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/hub279-intake-repair]
type: [bug report]: repair full-suite test doubles for draft PR #280
area: [testing], [backend]

The full Hub suite exposed three old webhook tests whose save_campaign doubles returned scalar status strings. The Notion intake database API now returns (status, slug) so it can report the transaction-selected round slug. Updated only the three doubles to return that contract, preserving conflict and unexpected-result assertions. No production behavior or current AGENTS.md contract changed. This remains a draft candidate; parent PR #279 needs owner integration, final review, hosted checks, deployment, and live evidence.
_________________________________________________________________________________
