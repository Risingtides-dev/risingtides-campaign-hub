# Campaign Hub

## Purpose

Campaign CRM integration, campaign delivery reporting, and creator operations.

## Ownership

- `campaign_manager/` owns the API and scheduled backend work.
- `frontend/` owns the web interface.
- `tests/backend/` owns backend verification.

## Local Contracts

- CRM `Content Niche Targets` supplies the declared campaign niches consumed by ShipStream's D1 playlist flow.
- Campaign reads request a background refresh at most every 15 minutes, independent of the scraping scheduler. The refresh reads exact stored Notion page links for existing active campaigns, updates only `content_types` and `internal_captions`, and neither creates campaigns nor sends notifications.
- An unreadable or missing CRM property preserves stored categories; an explicitly empty multi-select clears them.
- CRM `Internal Captions` holds a campaign's text-on-screen lines, typed by staff or submitted on an intake form. The same refresh keeps each active campaign's copy current, verbatim, under the same preserve-or-clear rule; a value too long to read whole counts as unreadable, never as a shorter list. Saving a whole campaign never changes its captions once it exists.
- `GET /api/campaigns/captions` lists every active campaign whose CRM captions have been read, with its sound, for the posting control plane. Finished campaigns and campaigns never read are left out, and the campaign list itself carries no caption text.

## Work Guidance

## Verification

- Backend checks run with `pytest tests/backend`.

## Child devlog Index
