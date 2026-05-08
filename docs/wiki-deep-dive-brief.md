# Build the Campaign Hub Wiki — Brief

> **Read this if you've been asked to "do the deep dive on the project."**
> No coding required. You'll be working with an AI assistant to explore the app and write everything down in plain English.

## What we're asking you to do

Produce a **wiki** — a set of plain-English pages — that explains every part of Campaign Hub. When you're finished, a brand-new hire should be able to read your wiki and understand the whole system without ever opening a code file or asking Jake a question.

Submit the finished wiki as a **pull request** (instructions at the bottom of this document).

## Who this wiki is for

- New hires on day one
- Account managers who need to look up "wait, what does this button do?"
- Jake, when he comes back from vacation and forgets how the Slack inbox works
- Anyone on the team who uses Campaign Hub but doesn't write code

If your reader has to Google a word, you've used too much jargon. Rewrite it.

## How to do this (using AI)

You don't need to read code. You'll let an AI do that for you. Here's the loop:

1. **Open the project in your AI tool** (Claude Code, ChatGPT with the repo loaded, Cursor, whatever you use).
2. **Pick one section from the list below.** Ask the AI: *"Explain [section] to me like I've never seen this app before. No code. No jargon. If you have to use a technical word, define it."*
3. **Push back.** If anything is unclear, ask "what does that mean?" or "can you give me an example?" Keep going until you actually understand it.
4. **Write it up.** Save your plain-English explanation as a markdown page inside `docs/wiki/` (one page per section).
5. **Take a screenshot** of any screen you're describing and add it to the page.
6. **Move to the next section.** Repeat until every section below has its own page.
7. **Build an index.** Create `docs/wiki/index.md` that links to every page so people can navigate the wiki.
8. **Open a pull request** (steps below).

> **Rule of thumb:** if a sentence has the words *endpoint*, *API*, *blueprint*, *ORM*, *schema*, *deploy*, *backend*, *frontend*, or anything ending in `.py` or `.ts`, rewrite it without those words. The reader does not care how the sausage is made — they care what it does for them.

## What the wiki must cover

Each of the sections below should become its own page in `docs/wiki/`.

### 1. The big picture
- What is Campaign Hub, in one paragraph?
- What problem does it solve for Rising Tides?
- Who pays for the service Rising Tides offers, and what do they get?
- Where does Campaign Hub fit in the bigger picture (Notion, Slack, Cobrand, the labels, the creators)?

### 2. Who does what
- Who is Jake? Who is on the team?
- Who are "creators" and what do they do for us?
- Who are the "labels" / clients?
- What is "UGC"? Why do labels pay for it?

### 3. How a campaign moves through the system (the lifecycle)
Walk through a campaign from start to finish in story form:
1. A label books a campaign — where does that show up?
2. The campaign appears in Campaign Hub — how?
3. Creators get added to the campaign — through Slack, by hand, or both?
4. Creators post their videos — how do we find those videos?
5. Performance tracking starts — what does Cobrand do?
6. The campaign finishes — what gets marked, what gets archived?

Use the data flow diagram in `CLAUDE.md` as a starting point but **rewrite it in plain words**. No arrows full of technical terms.

### 4. The screens (one section per page in the app)
For **each** of these screens, write: what you see, what it's for, who uses it, what every button/column does, and a screenshot.

- Campaigns list (the homepage table)
- Campaign detail page (the full view of a single campaign)
- Active vs. Finished tabs
- Creator database (cross-campaign roster)
- Creator profile page
- Slack inbox
- Internal TikTok tool (and the per-creator detail page inside it)
- Sidebar / navigation / hamburger menu on mobile

### 5. The outside connections
For each of these, explain in plain English: what it is, what it gives us, and what would break if it stopped working.

- **Notion** — where client bookings come from
- **Slack** — where new creator bookings get sent for Jake to approve
- **Cobrand** — where live performance numbers come from
- **TikTok / Instagram** — where the actual posts and sounds live

### 6. The money trail
Where does each piece of money information live?
- Creator rates — here, in Campaign Hub
- Campaign budgets — here
- Payments to creators — here
- Client billing (what the label pays Rising Tides) — **not** here, that's in Notion
- Performance numbers (views, comments) — **not** here, that's pulled from Cobrand

Make this very clear. The big rule of Campaign Hub: **money lives here, performance lives in Cobrand, client info lives in Notion.** Don't mix them up.

### 7. The scrapers (in plain English)
- What is "scraping"? (Pretend the reader has never heard the word.)
- Why do we scrape? What problem would we have without it?
- When does it run? (When someone clicks the button, automatically, etc.)
- What can go wrong? (TikTok blocks us, sound IDs don't match, etc.)
- What should you do when scraping seems broken?

### 8. What's currently broken or in progress
Check `docs/handoff.md` and `CLAUDE.md` (the "Pending Work" sections) and translate them into a simple list:
- "We're still working on…"
- "This is known to be flaky…"
- "Coming soon…"

### 9. Glossary
A simple A–Z list of every term that someone outside the team would not know. At minimum:
- UGC
- Creator
- Sound / Sound ID
- Cobrand
- Cobrand share page
- Scraping
- Slug
- Booking
- Campaign
- Active vs. Finished
- Notion CRM
- Slack inbox

### 10. "If something looks weird"
A short, friendly troubleshooting page:
- The campaign isn't showing up after a Notion booking — what to check
- Cobrand stats look stale — what to check
- The Slack inbox has duplicates — what to do
- A scrape says it finished but found 0 videos — what to do
- "When in doubt, ask Jake" — and how to reach him

## Definition of done

Before you open the pull request, check:

- [ ] Every section above has its own page inside `docs/wiki/`
- [ ] `docs/wiki/index.md` links to every page in order
- [ ] Each "screen" page has a screenshot
- [ ] No code snippets unless absolutely necessary, and if there is one, you explained what it does in plain English
- [ ] You read the whole thing top to bottom and didn't have to look anything up
- [ ] You can hand this to a brand-new hire and they could give you a five-minute summary of the app

## How to submit (no command line needed)

1. Make sure all your wiki files are saved inside the `docs/wiki/` folder.
2. Go to the repository on GitHub: <https://github.com/Risingtides-dev/risingtides-campaign-hub>
3. Click **Add file → Upload files** at the top right of the file list. Drag your new `docs/wiki/` folder in.
4. At the bottom of the upload page, choose **"Create a new branch for this commit and start a pull request."** Name the branch something like `wiki-first-pass` (or just leave the default).
5. Click **Propose changes**, then **Create pull request**.
6. Title the PR: **"Campaign Hub Wiki — first pass by [your name]"**
7. In the description, list which sections you finished and any sections you skipped or have questions about.
8. Hit **Create pull request**.

That's it. Someone on the team will review and either merge it or leave comments asking for clarifications.

## Reference docs to start from (do **not** copy verbatim)

These exist already and can give you a head start, but they are written in technical language. **Rewrite, don't copy.**

- `CLAUDE.md` — top-level project overview (technical)
- `docs/handoff.md` — current state and pending work (technical)
- `docs/architecture-evolution.md` — narrative of how the project got here (closest to plain English)

If something in those files contradicts what's actually in the app today, **trust the app, not the doc**, and flag the contradiction in your PR description.

---

**Questions? Ping Jake on Slack before you start so he can clarify scope.**
