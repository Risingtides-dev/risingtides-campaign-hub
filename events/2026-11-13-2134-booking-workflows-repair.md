time: [21:34] [13-11-26] America/New_York
agent: [Codex desktop] [GPT-6] [root with booking_wizard, creator_intelligence and booking_efficiency agents]
worktree: [codex/creator-tools-repair-20261113] creator-tools-repair/risingtides-campaign-hub
type: [bug report]: GitHub issues #284 and #292
area: [frontend] [backend] [testing] [review]

Repair Booking Wizard to use platform-scoped library rates with validated network fallback, reach paid recommendations before display truncation, bind the exact campaign round and expose honest loading/error/empty states. Preserve library per-post prices and network total quotes so budget and outreach agree; keep invalid selections removable and confirmed counts truthful. Protect manual creator-form analysis/rate/contact reads from stale identities, platform changes and manual edits. Only404means no history; transient failures remain unavailable. Add platform-safe last-rate filtering without changing unscoped callers.

Verification: all237 frontend tests passed with maxWorkers=2, production build passed,115 focused quote/last-rate/database/campaign route tests passed. Independent reviewer passed41 frontend cases and2 backend quote cases after fixing four concrete findings. Disposable local browser verification saved reviewalice to review-round-2 at total300 for3posts, matching the100-per-post library rate; direct SQLite readback confirmed the exact campaign, amount, count and draft status. No production booking or message sent. Root docs updated; existing child index and events guidance remain unchanged because ownership is unchanged. PR290 merged5c846718 andPR293 mergedf4d7e55e after their exact-head hosted backend gates passed. Final booking PR hosted gate/merge remains pending; no manual deployment performed.
