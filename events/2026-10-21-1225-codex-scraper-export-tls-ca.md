_________________________________________________________________________________
time: [12:25pm] [10-21-26] EDT UTC-04:00
agent: [Codex desktop] [gpt-6.1-sol] [release owner]
worktree: [codex/scraper-export-tls-ca-20261021] [/Users/risingtidesdev/dev/hub-scraper-export-tls-ca-20261021]
type: [bug report]: Repair verified local scraper queue-export TLS trust failure
area: [backend], [testing], [review]

Five natural Mac mini scraper runs from Oct 19 21:00 through Oct 21 09:00 EDT completed core scraping but failed queue export with rc 77. The installed Python 3.14.8 runtime reproduced SSLCertVerificationError for the canonical Campaign Hub HTTPS queue while curl returned HTTP 200; the same Python with its installed certifi bundle verified the endpoint and returned HTTP 200. The focused source repair uses the requests CA bundle for HTTPS urllib calls and preserves certificate and hostname verification, response bounds, and failure without a success receipt. Synthetic focused tests passed 16 cases, existing production venv compiled the exporter, and git diff --check passed. No manual scrape/export, provider action, production install, push, merge, or deployment occurred. Independent exact-head review, hosted checks, canonical Mac install, and a later natural-run export receipt remain required. Roll back source through the previous revision and reinstall via the established launcher workflow, preserving run reports and receipts.
_________________________________________________________________________________
