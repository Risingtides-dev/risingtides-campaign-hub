# 2026-11-12 14:36 PST — CH-F3 Slack signature fix

- Agent: Codex
- Worktree: isolated candidate on the named CH-F3 stack
- Type: security fix
- Area: Slack Events API exemption from the Hub write gate
- Outcome: The route checks the Slack v0 signature, raw body, and five-minute timestamp before parsing events or answering URL verification. Missing configuration fails closed.
- Verification: The unsigned challenge fails on the prior candidate; focused tests and two assertion-killed mutants verify the fix. Full-suite results are recorded in the external candidate report.
- Release limitations: Candidate only. The Hub owner must arrange the dashboard key sender before any gate deployment.
