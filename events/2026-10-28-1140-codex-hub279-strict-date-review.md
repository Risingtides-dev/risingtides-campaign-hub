_________________________________________________________________________________
time: [11:40am] [10-28-26] EDT
agent: [codex] [gpt-6.1-sol] [focused builder]
worktree: [codex/hub279-intake-repair]
type: [bug report]: address independent review of draft PR #279 repair
area: [backend], [testing], [review]

Independent review found that Python accepts compact YYYYMMDD in date.fromisoformat, while downstream round attribution requires YYYY-MM-DD. Intake now requires the exact date format and real calendar dates before allowing shared-sound rounds. Trimmed CRM page IDs are persisted and matched against older untrimmed rows so whitespace does not split identity. Added compact-date and page-ID regressions. The focused repeat-booking, DB and campaign blueprint tests passed 126 on the Mac mini. This remains an isolated candidate with no push, merge, deployment, provider action, or live verification. John review, fresh independent review, hosted checks, and production parity remain required.
_________________________________________________________________________________
