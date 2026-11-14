time: [21:28] [13-11-26] America/New_York
agent: [Codex desktop] [GPT-6] [root with creator_intelligence and booking_efficiency agents]
worktree: [codex/creator-tools-repair-20261113] creator-tools-repair/risingtides-campaign-hub
type: [bug report]: GitHub issues #285 and #289
area: [backend] [frontend] [testing] [review]

Normalize TikTok creator identities and share round-qualified, deduplicated post evidence across intelligence reads. Preserve campaign-round identity and disambiguate identical artist/song labels, validate optional campaign_slug, bound fit expansion, and distinguish query failures from empty results. Scope Creator Library rate memory and cached performance to one platform; unscoped reads choose a deterministic platform while historical counters remain person-level. Add backward-compatible frontend parameter/cache support and synthetic regressions. No data rewrite, migration, provider request or production booking.

Verification: 11 intelligence backend cases and 8 intelligence/label frontend cases passed. Platform-rate repair passed 93 relevant library cases; independent reviewer passed 57 related cases with no blocking finding. Bounded query checks cover intelligence and rate reads. Root full shared backend run had 1217 passes, 10 unavailable-fixture skips and one unrelated runtime timeout; that isolated case passed on rerun. Exact PR hosted gate remains pending. PR #290 (efficiency, source55e14dc) already merged as5c846718 after its hosted backend gate passed. Root devlog updated; child index and events guidance intentionally unchanged because no ownership boundary changed.
