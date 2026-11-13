_________________________________________________________________________________
time: [15:00] [11-13-26]
agent: [claude] [opus 5.5]
worktree: claude/issue-257-crm-sync-scheduler
type: [review]
area: [backend], [testing]

Merged current main ecab1f3 (20 commits, no conflicts) into PR #258 and traced how its two additive tables reach PostgreSQL. crm_scan_state and crm_page_queue are SQLAlchemy models, so the app creates them at boot through the existing Base.metadata.create_all call in db.init, the same path that created model-only tables such as tides_tracker_stats_cache (June), creator_profiles (August) and creator_payout_events, booking_payment_marks, payout_batches and payout_items (October), none of which has a migration script or explicit CREATE TABLE. A create_all error other than the tolerated concurrent "already exists" race propagates out of create_app, so a missing CREATE privilege would fail the boot and the /health check rather than run without the queue. The full Python suite on merged head 99282d2 against a disposable local PostgreSQL 16 database gave 1,260 passed and 6 failed: four are the same wall-clock and runtime-reprovision timeouts that current main also fails on this host (load average 60 to 150), and the other two are #258's trickling-deadline tests, which fail only their sub-second timing bounds here and fail the same way on the unmerged PR head 9fbd83d; main changed none of the queue, Notion or test files. No production database, Railway, CRM or live Hub endpoint was touched, and nothing is merged or deployed.
_________________________________________________________________________________
