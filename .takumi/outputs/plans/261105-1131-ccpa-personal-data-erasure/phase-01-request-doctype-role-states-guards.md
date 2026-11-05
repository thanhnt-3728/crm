# Phase 01 — Request doctype, Privacy Officer role, states, deadlines, delete guard

## Context Links
- Consultation (approved): `.takumi/outputs/reports/261105-1111-personal-data-erasure-consultation.md` §1 R1–R6, §4.1/4.2/4.4/4.6
- Raw sources: `04-emails.txt` (Oct 26 → ack Nov 9, response Dec 10), `03-slack-thread.txt` 09:20–09:28
- Code: `crm/hooks.py:256` (doc_events), `crm/install.py:18` (after_install), `crm/patches.txt`, `crm/api/session.py:4`, `crm/fcrm/doctype/crm_holiday_list/`, `crm/fcrm/doctype/fcrm_settings/fcrm_settings.json`, `crm/fcrm/doctype/crm_deal_status/crm_deal_status.json:47` (`type` Open/Ongoing/On Hold/Won/Lost)
- Test pattern: `crm/fcrm/doctype/crm_lead/test_crm_lead.py` (`IntegrationTestCase`, rollback in tearDown)

## Overview
- Priority: P1 · Status: pending · Effort: 7h · Depends on: none
- The record of a request and every rule that does not need the erasure engine: who may move it, its
  dates, the On Hold rule, and the block on deleting a Lead/Deal/Contact tied to an open request.

## Key Insights
- Dana's real dates are the test oracle: received Mon 2026-10-26 → ack due Mon 2026-11-09 (+10 business
  days, day 0 excluded) → response due Thu 2026-12-10 (+45 calendar days).
- No site-wide holiday list exists; `CRM Holiday List` is only referenced by SLA. Add an optional
  `FCRM Settings.erasure_holiday_list`; empty → Mon–Fri only.
- "Open deal" = the deal's `CRM Deal Status.type` not in (Won, Lost). The hold rule lives here as a pure
  predicate + one query, so phase 03 and the deal hook reuse it.
- `Approved/Executed` from the design is kept as two stored states because execution runs as a job:
  `Approved` = approver confirmed, job queued/running/failed; `Executed` = job finished. No other state.
- CI runs server tests on Frappe version-15 and version-16 lanes; use only APIs present in both.
- Privacy Officer is additive: holders must also have a CRM role (`CRM_ALLOWED_ROLES`); no CRM access change.

## Requirements
Functional
- F1 Doctype `CRM Erasure Request` (module FCRM, naming `CRM-ERQ-.YYYY.-.#####`): `status`, `subject_name`,
  `source_doctype` (CRM Lead/CRM Deal/Contact) + `source_docname`, child `identifiers`
  (`CRM Erasure Identifier`: `kind` Email|Phone, `value`, `normalized`), `requested_by` (User, set on insert,
  read-only), `received_on` (Date, reqd, ≤ today), `ack_due`, `response_due` (read-only, computed),
  `acknowledged_on` (Date, manual), `hold_reason` (Small Text: deal names only), `approver`, `approved_on`,
  `rejection_reason`, `executed_on`, `last_error`, child `matches` (`CRM Erasure Match`: `ref_doctype`,
  `ref_name`, `reason`, `action`, `excluded`, `new_since_logging`), `outcome` (JSON, no PII),
  `known_limitations` (Small Text). Matches/outcome are filled by phases 02/03.
- F2 States: Draft → Pending Approval ⇄ On Hold → Approved → Executed → Closed; Draft/Pending/On Hold →
  Rejected. Transition table is pure data in `erasure_states.py`; controller rejects anything else.
- F3 Server guards: approve/reject only by a user with `Privacy Officer` and `!= requested_by`
  (and `!= owner`); requester edits only in Draft; `status` is never writable via form save.
- F4 `ack_due`/`response_due` recomputed on every save from `received_on` (+ holiday list).
- F5 Role `Privacy Officer` created by `after_install` and by a patch (existing sites).
- F6 `on_trash` on CRM Lead, CRM Deal, Contact throws if the doc is the source or a non-excluded match of a
  request in Draft/Pending Approval/On Hold/Approved.
- F7 Hold: on submit, on `CRM Deal.on_update`, and on approve attempt, a request whose subject sits on an
  open deal (as `CRM Deal.contact`, a `CRM Contacts` row, or via her lead) goes On Hold with
  `hold_reason` = deal names; when none remain it returns to Pending Approval. Deadlines are not paused.
Non-functional
- Permissions: Sales User create/read/write `if_owner`; Sales Manager read; Privacy Officer read/write;
  System Manager full. Delete: nobody but System Manager (24-month record keeping, open item 1).
- Every module < 200 lines.

## Architecture
```
crm/fcrm/doctype/crm_erasure_request/
  crm_erasure_request.json/.py     controller: validate → deadlines, transition guard, edit guard
  erasure_states.py                TRANSITIONS = {(from,to): actor}; can_transition(user_roles, user, req, to)
  erasure_deadlines.py             add_business_days(start, n, holidays), compute_due_dates(received_on, holidays)
  erasure_hold.py                  blocking_open_deals(req) ; refresh_hold(req) ; on_deal_update(doc, method)
  erasure_guards.py                block_delete_for_open_request(doc, method)  (on_trash)
crm/fcrm/doctype/crm_erasure_identifier/, crm_erasure_match/   (istable)
```
Data flow: rep save → `validate` (deadlines, edit guard) → `submit_for_approval` (phase 02 API) →
`refresh_hold` → Pending Approval | On Hold. Deal save → `on_deal_update` → `refresh_hold` for requests
whose matches include that deal. Lead/Deal/Contact delete → `on_trash` guard → throw `frappe.ValidationError`
naming the request.

## Related Code Files
- Create: the doctype folders above, `crm/patches/v1_0/add_privacy_officer_role.py`, tests
  `crm/fcrm/doctype/crm_erasure_request/test_crm_erasure_request.py`, `test_erasure_deadlines.py`
- Modify: `crm/hooks.py` (doc_events: `on_trash` for CRM Lead/CRM Deal/Contact; `CRM Deal.on_update`
  append `on_deal_update`), `crm/install.py` (`add_privacy_officer_role`), `crm/patches.txt`,
  `crm/fcrm/doctype/fcrm_settings/fcrm_settings.json` (`erasure_holiday_list`). No session change: the
  UI reads `roles` already returned by `crm/api/session.py:get_users` (line ~119).
- Delete: none

## Implementation Steps
1. Write the tests in the plan below first; run them, record RED (assertion failures on a skeleton doctype).
2. Child doctypes `CRM Erasure Identifier`, `CRM Erasure Match`; parent JSON with fields/permissions above.
3. `erasure_deadlines.py`: pure; holidays = set of dates from the configured list (weekends always off).
4. `erasure_states.py` + controller `validate`: compare `doc_before_save.status`; block form-save status
   changes (only whitelisted methods set `flags.erasure_transition`).
5. `erasure_hold.py`: one query joining `CRM Deal`/`CRM Contacts`/`CRM Deal Status`; `on_deal_update`
   looks up requests via `CRM Erasure Match` (`ref_doctype='CRM Deal'`, `ref_name=doc.name`).
6. `erasure_guards.py` + hooks; role helper in `install.py` reused by the patch.
7. Run module tests → GREEN; refactor.

## Todo List
- [ ] Tests written and RED recorded
- [ ] Child + parent doctypes, permissions
- [ ] Deadlines, states, hold, delete guard modules
- [ ] hooks / install / patch / settings field
- [ ] Module tests GREEN

## Test plan
- Changed: new doctype + 4 modules; hooks `on_trash`, `CRM Deal.on_update`; role install; settings field.
- Impacted / risk level: **safety-critical** (permissions, data deletion guard). Deal `on_update` now runs
  extra code on every deal save → existing `test_crm_deal.py` and `test_crm_lead.py` (deletes) re-run.
- Will verify: new unit tests for pure modules, new integration tests for guards/permissions/hooks.
- Deliberately skipped: UI (phase 04).

| AC / risk | Test | Level | Why enough / not cheaper | Scope / est. |
|---|---|---|---|---|
| F4 ack/response dates | `test_erasure_deadlines` table: Oct 26→Nov 9/Dec 10; received Fri, Sat, Sun; holiday inside window; holiday on day 10; month/year rollover | Unit | Pure date math | <1s |
| F2 legal/illegal transitions | `test_erasure_states` table over all (from,to) pairs | Unit | Pure table | <1s |
| F3 self-approval rejected; non-PO rejected; PO ≠ requester accepted (positive control) | `test_crm_erasure_request::test_approval_guards` | Integration | Real roles + session user boundary | ~2s |
| F3 status not settable via `doc.save()`; requester can't edit after Draft | same file | Integration | Controller validate path | ~1s |
| F1 Sales User sees only own requests; can't delete | `frappe.has_permission` checks | Integration | DocPerm wiring | ~1s |
| F6 delete Lead/Deal/Contact linked to open request → blocked; after Executed/Rejected → allowed | `test_delete_guard` | Integration | Real `on_trash` dispatch | ~2s |
| F7 open deal → On Hold; deal set Lost → back to Pending; Won also releases; deal without her → no hold | `test_hold_rule` | Integration | Real deal save fires hook | ~2s |
| F5 role exists after patch; patch idempotent (run twice) | `test_privacy_officer_role` | Integration | DB | <1s |

- Plausible bugs → catching case: off-by-one counting day 0 (Oct 26→Nov 9 case); weekend received date
  shifts wrong (Sat case); holiday ignored (holiday-in-window case); approver == requester allowed
  (self-approval case); `Sales Manager` treated as PO (non-PO case); status forged via REST save (save case);
  guard checks only `source_docname`, not matches (delete a matched deal case); guard blocks forever after
  Executed (post-Executed case); hold treats "On Hold" deal status as closed (deal-status-type case).
- Failure scenarios: permission denied (above); idempotent patch.
- TDD: RED on skeleton doctype for every row.
- While coding: `bench --site test_site run-tests --app crm --module crm.fcrm.doctype.crm_erasure_request.test_crm_erasure_request`
- Integration / consumers: `--module crm.fcrm.doctype.crm_deal.test_crm_deal`, `...crm_lead.test_crm_lead`
- Final gate: phase 05.  Coverage: 90% line / 80% branch on new modules (`--coverage`).

## Success Criteria
All rows above GREEN; existing deal/lead suites still GREEN; Oct 26 example yields Nov 9 / Dec 10.

## Risk Assessment
- Deal `on_update` hook adds a query to every deal save (Med likelihood / Low impact) → indexed lookup on
  `CRM Erasure Match.ref_name`, early return when no open requests exist.
- Guard blocks a legitimate merge/cleanup (Low/Med) → message names the request; System Manager can
  reject the request first.

## Security Considerations
Guards in Python only trust `frappe.session.user` and `frappe.get_roles()`; never a client-sent user.
Child `matches` store doc names only. `identifiers` are the only PII on the request (open item 1).

## Next Steps
Phase 02 fills `matches` and adds `submit_for_approval`; phase 03 adds approve/execute.
