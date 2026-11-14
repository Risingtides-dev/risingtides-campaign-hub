time: [21:23] [13-11-26] America/New_York
agent: [Codex desktop] [GPT-6] [root with booking_efficiency agent]
worktree: [codex/creator-tools-repair-20261113] creator-tools-repair/risingtides-campaign-hub
type: [bug report]: GitHub issue #286
area: [backend] [frontend] [testing] [review]

Correct Booking Efficiency to use one normalized platform-specific paid cohort and canonical round-qualified outcomes. Remove ingestion timestamps from outcome eligibility while retaining the campaign-created period. Keep report, leaderboard, detail and insights consistent; correct median, signed price opportunities, undefined paid-cohort unit costs and unsupported forecasts. Clarify period/tier labels and error/empty states in the interface. Add cohort query-count and attribution regressions.

Verification before publication: 30 efficiency/platform cases and 27 round regressions passed; independent reviewer passed 18 attribution/JSON cases with no blocking findings. Full frontend 215/215 passed with maxWorkers=2, and production build passed. First unbounded frontend run hit three wall-clock timeouts on this heavily loaded host; bounded rerun passed. Nine targeted regressions failed against original efficiency source, including 60,600 versus 600 eligible views. Root devlog updated; existing child index and events/AGENTS.md unchanged because ownership is unchanged. Hosted exact-PR backend gate and merge are pending; no production writes or manual deployment.
