# Phase 03 — Approval, execution (scrub / replace / delete / purge) and hidden copies

## Context Links
- Consultation §4.2, §4.3, §4.5, §4.7; §5 "Partial failure"; §6 success measures
- `reports/frappe-v16-api-verification.md` (Version shape, `delete_permanently`, global search, test Version gotcha)
- Registry: `phase-02-erasure-registry-and-discovery.md` → Architecture table
- Code: `crm/api/dashboard.py` (reads CRM Lead, CRM Deal, CRM Deal Status, CRM Status Change Log, User only)

## Overview
- Priority: P1 · Status: pending · Effort: 13h · Depends on: phases 01, 02
- The approver re-runs discovery, sees new items flagged, excludes, types the request number; the server
  enforces the two-person rule and the hold, then a job applies the registry in one DB transaction,
  purges hidden copies, commits, deletes files, and records a PII-free outcome.

## Key Insights
- Writes go through `frappe.db.set_value(..., update_modified=False)` / `frappe.db.delete` /
  `frappe.db.sql` only: no controller, no hooks, no Version, no `modified` bump (dashboard date
  filters and list order unchanged). Never `doc.save()` or `db_set` (fires `on_change`).
- In tests Frappe suppresses Versions (`ignore_version = frappe.in_test`): the "no new Version" test must
  run with versioning re-enabled, else it passes on a buggy save-based scrub.
- Communication, Comment, Email Queue, WA Log, FCRM Note, CRM Lead, CRM Deal all keep Versions; Contact
  and Address do not. Rule: purge Versions of every touched doc except CRM Deal (filter person/her-row
  entries); then filter any remaining Version whose `data` matches her identifiers; delete if empty.
- Global search: `delete_for_document` then `update_global_search` (it never writes empty content).
- File physical deletion on `delete_doc` is UNVERIFIED → step 1 spike confirms on the bench.

## Requirements
Functional
- F1 `get_approval_preview(name)` (Privacy Officer, ≠ requester): re-discovers, returns stored + new rows
  (`new_since_logging`), hidden-copy counts, and `preview_hash` (sha256 of sorted ref list).
- F2 `approve(name, confirm_name, excluded: list[str], preview_hash)`: lock row `for_update`; guard
  (phase 01 roles, status Pending Approval); `confirm_name.strip() == name` else throw; hold re-check →
  On Hold + throw; re-discover and compare hash → throw "matches changed, reload"; persist final matches
  + exclusions; status Approved; `approver`, `approved_on`; enqueue job (`queue="long"`,
  `job_id=f"crm-erasure::{name}"`, `deduplicate=True`, `enqueue_after_commit=True`).
- F3 `reject(name, reason)` (PO, ≠ requester) → Rejected. `close(name)` (PO) Executed → Closed and applies
  the retention rule (open item 1; one function `apply_retention(request)`).
- F4 Job `execute_request(name)`: status must be Approved; `executor.run(request)` → residual check →
  set Executed, `executed_on`, `outcome`, `known_limitations` → `commit` → delete files (each its own
  commit, `ignore_missing`) → on any DB exception: `rollback`, write `last_error` (no PII: exception
  class + registry doctype) in a fresh commit, status stays Approved. `retry_execution(name)` (PO) re-enqueues.
- F5 Executor applies registry actions to non-excluded matches only, in registry order; person records
  anonymized in place; activity content → `Content erased <REQ>`; her tokens removed from address lists.
- F6 Hidden copies per registry (Version, Deleted Document, `__global_search`, Email Queue + Recipient,
  WA Log, Error Log, `_comments`, link_title).
- F7 Residual check in the job: `verify.residual_hits(identifiers, tables=registry tables)` scans the text
  columns of every registry table (emails via `LOWER(col) LIKE`, phones via digits-only `REGEXP_REPLACE`),
  ignoring excluded matches' rows; hits >0 → rollback + `last_error` listing table names only.
  `verify.full_scan(identifiers)` runs the same check over every table in information_schema (minus the
  request's own tables); too slow for the job, used by tests (phase 05) and the runbook/bench command.
- F8 Outcome JSON: `{doctype: count}`, `docs: [names]`, `files_deleted`, `excluded_count`; no identifiers.
- F9 Idempotent: a re-run on an Executed or half-done request makes no further change and reports zero
  new changes; job refuses to run when status ≠ Approved.
Non-functional
- One DB transaction for all DB work; files only after commit. Job timeout 1500 s.
- Each module < 200 lines.

## Architecture
```
crm/erasure/
  approval.py          get_approval_preview, approve, reject, close, retry_execution (called by crm/api/erasure.py)
  executor.py          run(request) -> Changes  : iterate registry, dispatch by action
  scrub_actions.py     scrub_person, replace_content, scrub_address_list, unlink_or_scrub_address
  hidden_copies.py     purge_versions, filter_version_entries, purge_deleted_documents, reindex_search,
                       purge_email_queue, purge_logs, rewrite_comments_column
  jobs.py              execute_request(name): lock, run, verify, commit, delete files, record outcome
  verify.py            residual_hits(ids, tables) / full_scan(ids) — independent raw-SQL oracle (MariaDB;
                       Postgres uses regexp_replace too), also exposed for `bench execute` in the runbook
```
Data flow: approve (API) → commit (status Approved) → RQ job → `executor.run` → `hidden_copies.*` →
`verify.residual_hits` == 0 → status Executed + outcome → COMMIT → `delete_doc("File", n,
delete_permanently=True, ignore_permissions=True)` per file → commit each.
Version filter (pseudocode): `keep = [e for e in data["changed"] if e[0] not in PERSON_FIELDS[doctype]
and not ids.matches_text(json.dumps(e))]`, same for `added`/`removed`/`row_changed`; empty → delete row.

## Related Code Files
- Create: the six modules above; tests `crm/erasure/test_scrub_actions.py` (unit: address-list scrub,
  version-entry filter), `test_executor.py`, `test_hidden_copies.py`, `test_approval.py`, `test_jobs.py`
  (integration)
- Modify: `crm/api/erasure.py` (expose approval endpoints)

## Implementation Steps
1. Spike on the bench (30 min): confirm `delete_doc("File", …, delete_permanently=True)` removes the disk
   file, `frappe.db.set_value` on a `track_changes` doctype writes no Version, and whether a Communication
   linked to her Lead/Deal writes a snippet into the parent's `_comments` column (if yes,
   `rewrite_comments_column` must cover it). Record in `reports/`.
2. Tests first (table); RED on skeletons.
3. `scrub_actions.py` pure helpers (address list, version filter) → unit GREEN.
4. `executor.py` + `hidden_copies.py` → integration GREEN incl. Version/no-Version and dashboard parity.
5. `verify.py` (oracle) then `jobs.py` (transaction + rollback + file stage), `approval.py`, API wiring.
6. Module run, refactor.

## Todo List
- [ ] Bench spike recorded  - [ ] RED tests  - [ ] scrub helpers  - [ ] executor + hidden copies
- [ ] verify oracle  - [ ] job with rollback + file stage  - [ ] approval endpoints  - [ ] GREEN

## Test plan
- Changed: approval + execution engine. Impacted: every registry doctype's rows; dashboard endpoints
  (must not move); Deal/Lead activity timelines (Version purge removes old diffs by design).
- Risk: **safety-critical** (personal data, deletion, permissions, idempotency) → whole erasure group.

| AC / risk | Test | Level | Why | Est. |
|---|---|---|---|---|
| F2 self-approval, non-PO, wrong typed number (`crm-erq-…` lower-case, trailing chars) rejected; correct PO succeeds (control) | `test_approval` | Integration | Session/roles boundary | ~2s |
| F2 approve while open deal → On Hold, nothing executed | `test_approval::test_hold_on_approve` | Integration | Hook + query | ~1s |
| F2 stale `preview_hash` → rejected | `test_approval::test_stale_preview` | Integration | Re-discovery | ~1s |
| F5 person fields scrubbed, kept fields equal before/after (status, values, owner, dates, `modified`) | `test_executor::test_person_records` | Integration | Real columns | ~2s |
| F5 excluded match untouched | `test_executor::test_exclusions` | Integration | | ~1s |
| F5/F6 no new Version rows (versioning re-enabled via `patch("frappe.in_test", False)`) | `test_hidden_copies::test_no_new_versions` | Integration | Would be hollow otherwise | ~1s |
| F6 Version: Lead purged; Deal keeps status/value entries, drops person + her CRM Contacts row entries | `test_hidden_copies::test_versions` | Integration | JSON in DB | ~2s |
| F6 Deleted Document with her email/phone purged; unrelated one kept | `test_hidden_copies::test_deleted_documents` | Integration | | ~1s |
| F6 `__global_search` has no row containing her identifiers; scrubbed doc still indexed by marker | `test_hidden_copies::test_global_search` | Integration | | ~1s |
| F6 Email Queue/Recipient, WA Log, Error Log rows purged; colleague's queue row kept | `test_hidden_copies::test_queues_and_logs` | Integration | | ~1s |
| F4 injected failure mid-run (patch one scrub action to raise) → no row changed, `last_error` set, status Approved; retry succeeds | `test_jobs::test_rollback_and_retry` (`frappe.db.commit` patched to a recorder; rollback real) | Integration | Transaction boundary | ~2s |
| F4 files deleted only after commit; disk file gone | `test_jobs::test_file_stage` | Integration | Disk + DB | ~1s |
| F9 second run → zero changes, outcome unchanged; job refuses non-Approved | `test_jobs::test_idempotent` | Integration | | ~2s |
| F7/F8 outcome has counts/names and no identifier string; residual scan zero | `test_jobs::test_outcome_free_of_pii` | Integration | | ~1s |
| Address-list scrub (`"A <a@x>, Marisol <MARISOL.VEGA@example.net>"`), version-entry filter | `test_scrub_actions` | Unit | Pure | <1s |
- Plausible bugs: `doc.save()` used → Version + `modified` bump; `update_modified` left True; dashboard
  date ranges shift; colleague's address dropped from recipients; case-different email kept in cc; Deal
  status Version entries purged (finance audit lost); child-row Version `added` keeps her row dict; file
  deleted before commit then rollback → orphan; re-run duplicates marker (`Content erased X Content erased X`);
  approval guard checks owner but not requested_by; typed confirm case-insensitive; stale preview executes
  unseen items; outcome contains her email via doc title.
- Failure scenarios: interruption mid-run (rollback test); retry/idempotency; permission denied; concurrency
  (two approves: second sees status Approved → throws; `for_update` lock).
- TDD: RED for every row. While coding: `bench --site test_site run-tests --app crm --module crm.erasure.test_executor`
- Widen to whole erasure group + `crm.fcrm.doctype.crm_deal.test_crm_deal` after the group. Final gate: phase 05.

## Success Criteria
Every row GREEN; residual scan zero on the fixture; rollback test leaves the DB identical.

## Risk Assessment
- Unknown table keeps a copy (Med/High) → `full_scan` in the phase 05 gate and in the runbook's last step
  finds it; fix = new registry row. The job's targeted check turns a registry-table miss into a visible error.
- Long job on big Version table (Med/Med) → long queue, timeout 1500 s, LIKE prefilter.
- Partial file deletion (Low/Low) → re-run deletes the rest (File rows still found via `attached_to_name`).

## Security Considerations
All guards server-side; job re-checks status and approver at start (job args are only `name`). `last_error`
and logs carry no identifiers. Executor uses `ignore_permissions` only inside the job after guards passed.

## Next Steps
Phase 04 UI consumes F1–F3; phase 05 runs the end-to-end gate and renders the runbook from the registry.
