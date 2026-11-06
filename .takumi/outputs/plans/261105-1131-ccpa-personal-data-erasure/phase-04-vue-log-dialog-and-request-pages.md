# Phase 04 — Vue UI: log dialog on Lead/Deal/Contact, request list and detail

## Context Links
- Consultation §1 R1, §4.1/4.3/4.4; Slack 09:20 ("log it right from her lead")
- API contracts: phase 02 F5, phase 03 F1–F3 (`crm/api/erasure.py`)
- Code: `frontend/src/pages/Lead.vue:177` (header action buttons, `canDelete`), `:451` (command palette
  commands), `Deal.vue`, `Contact.vue:103`; `frontend/src/router.js:33-148`; `frontend/src/utils/navigation.js:27`;
  `frontend/src/stores/users.js:134` (`getUser().roles`); `frontend/src/components/Modals/GlobalModals.vue`
- Test rules: `.pi/SPEC.md` → Testing (pure utils in `src/utils`, vitest, `@/` alias)

## Overview
- Priority: P1 · Status: in-progress · Effort: 10h · Depends on: phase 02 (log/preview API); phase 03 for the
  approve/reject wiring. May run in parallel with phase 03 once phase 02's API signatures are merged
  (frontend files only; no shared files with phase 03).
- The rep logs the request from the person's page; reps and Privacy Officers track it on a list page;
  the Privacy Officer approves on the detail page with a typed confirmation.

## Key Insights
- `Lead.vue` (723 lines) and `Deal.vue` (1068) are already large: add only a button, a command entry and
  the dialog mount; all logic goes into new components and pure utils.
- Logic that can break (deadline highlight, exclusion state, confirmation match, grouping) lives in pure
  utils with vitest unit tests; components stay thin. No component/browser tests (repo has none; logic
  is unit-proven).
- Server is the authority: UI hides PO actions for non-PO / requester, but every rule is enforced in Python.
- New frontend files use kebab-case per the caller's rule, although existing components are PascalCase;
  imports name them explicitly.

## Requirements
Functional
- F1 "Log erasure request" action (button + command palette) on Lead, Deal, Contact pages for users with
  create permission on `CRM Erasure Request`.
- F2 Dialog step 1: subject name (prefilled), received on (date, required, ≤ today), emails/phones
  (prefilled from the record, add/remove). Step 2: "Find matches" → grouped list (doctype, title, reason)
  with per-row exclude checkbox, hidden-copy counts, then "Submit for approval". Shows computed ack/response
  due dates.
- F3 List page `/erasure-requests`: number, subject, status, received on, ack due, response due, highlight
  overdue (red) / due within 3 calendar days (amber); acknowledged requests drop the ack highlight; Executed/
  Closed/Rejected drop all highlights. Sidebar entry for users with read permission.
- F4 Detail page `/erasure-requests/:name`: dates + `acknowledged_on` editor (requester or PO), hold reason
  with deal links, matches (new items badge), outcome (counts, known limitations) after execution,
  `last_error` + "Retry" for PO when Approved and failed.
- F5 PO actions (shown when PO and not requester): Approve → preview dialog (new items flagged and
  pre-selected for review, exclusions) → typed confirmation input; button enabled only on exact match;
  sends `preview_hash`. Reject → reason required. Close (Executed only).
- F6 Server errors (stale preview, On Hold, guard) shown as toasts; preview reloads on stale.
Non-functional
- No PII in browser storage or console logs. Each file < 200 lines. Uses frappe-ui `Dialog`, `Button`,
  `createResource`, `call` like existing pages.

## Architecture
```
frontend/src/utils/erasure-deadlines.js     deadlineState(dueDate, today, doneFlag) -> 'overdue'|'due-soon'|'ok'|'done'
frontend/src/utils/erasure-matches.js       groupMatches(rows), toggleExclusion(set, key), isConfirmationValid(typed, name),
                                            prefillIdentifiers(doc, doctype)
frontend/src/components/Erasure/log-erasure-request-dialog.vue
frontend/src/components/Erasure/erasure-matches-list.vue      (shared by log dialog and approve dialog)
frontend/src/components/Erasure/approve-erasure-dialog.vue
frontend/src/pages/erasure-requests.vue
frontend/src/pages/erasure-request.vue
```
Data flow: page action → dialog → `crm.api.erasure.log_request` → `get_preview` → `set_exclusions` →
`submit_for_approval` → route to detail. Detail (PO) → `get_approval_preview` → `approve(name, typed,
excluded, preview_hash)` → status Approved → poll doc until Executed (realtime `doc_update` or reload).

## Related Code Files
- Create: files above; tests `frontend/tests/unit/erasure-deadlines.test.js`, `erasure-matches.test.js`
- Modify: `frontend/src/pages/Lead.vue`, `Deal.vue`, `Contact.vue` (button, command, dialog mount),
  `frontend/src/router.js` (2 routes), `frontend/src/utils/navigation.js` (sidebar item)
- Delete: none

## Implementation Steps
1. Unit tests for both utils first (RED: functions return neutral wrong values).
2. Implement utils → GREEN.
3. `erasure-matches-list.vue`, `log-erasure-request-dialog.vue`; wire into Lead/Deal/Contact.
4. List + detail pages, routes, navigation item; approve dialog.
5. Manual smoke in the dev server as rep then PO (two browsers) — not a test gate, a wiring check.
6. `yarn test:run`, build (`yarn build`) to catch compile errors.

## Todo List
- [x] Util tests RED  - [x] utils GREEN  - [x] dialog + list component  - [x] page actions
- [x] list/detail pages + routes + nav  - [x] approve dialog  - [ ] build + tests GREEN

## Test plan
- Changed: 2 utils, 5 components/pages, 3 page edits, router, navigation. Impacted: `navigation.test.js`
  (item list), Lead/Deal/Contact pages (existing actions must still work).
- Will verify: unit tests for utils; existing `navigation.test.js`; build. Deliberately skipped: browser
  tests — layout-only wiring, logic proven at unit level and rules enforced server-side (phase 03 tests).

| AC / risk | Test | Level | Why | Est. |
|---|---|---|---|---|
| F3 overdue / due-soon / ok boundaries (due today, due in 3 days, 4 days, past); done flags clear it | `erasure-deadlines.test.js` table | Unit | Pure | ms |
| F5 confirmation exact (case, whitespace trimmed only at ends, partial, empty) | `erasure-matches.test.js` | Unit | Pure | ms |
| F2 grouping by doctype, exclusion toggle twice = included, prefill from Lead/Deal/Contact shapes (empty phones skipped) | `erasure-matches.test.js` | Unit | Pure | ms |
| F3 nav item present only when route exists | existing `navigation.test.js` extended | Unit | Pure | ms |
| F1/F4/F5 wiring | `yarn build` + manual smoke | Build | No logic in components | ~1 min |
- Plausible bugs: "due today" shown as ok; timezone shifts date (use date strings, inject `today`);
  confirmation accepts lower-case; exclusion state lost on regroup; prefill puts lead `phone` twice.
- TDD: RED on util skeletons. While coding: `cd frontend && yarn vitest run tests/unit/erasure-*.test.js`
- Final gate: `cd frontend && yarn test:run` (phase 05).  Coverage: `yarn test:coverage` on the 2 utils, 90/80.

## Success Criteria
Util tests GREEN; existing 118+ frontend tests GREEN; build passes; smoke: rep logs from each of the
three pages, PO approves with typed number, non-PO sees no approve button.

## Risk Assessment
- Large page files grow (High/Low) → only mount + action entries added; logic in new files.
- UI shows approve to requester who is also PO (Med/Low) → hidden in UI, rejected by server anyway.

## Security Considerations
No identifiers in URLs or query strings (POST bodies only); no `localStorage`; titles shown only as returned
by permission-checked API.

## Next Steps
Phase 05 smoke + E2E gate; open item 2 (PO page location) defaults to this CRM page.
