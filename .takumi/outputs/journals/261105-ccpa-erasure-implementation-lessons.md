# CCPA erasure built test-first and sealed by review, but the full suite is red and sign-off is pending

**Date**: 2026-11-05 19:36
**Severity**: high
**Component**: CRM erasure (`crm/erasure/`, `crm/api/erasure.py`, `CRM Erasure Request` doctype, `frontend/src/components/Erasure/`)
**Status**: blocked

## What Happened

Six phases went in as uncommitted work: request doctype and states, registry-driven discovery, approval and execution with hidden copies, the Vue log dialog and pages, the end-to-end gate with runbook, and docs. Each phase was written test-first. The whole-change review returned SEALED (score 8, 0 critical). The change is blocked on Privacy Officer sign-off (`riskGate.humanSignedOff: false`). The version-15 lane never ran.

## The Brutal Truth

The full suite is not green, and it does not go green on this box. What is green is the 27-module safety-critical group. That is the honest claim, and it is much narrower than "all tests pass." The per-phase reviews caught defects in code we had already called done. Two of them, a suffix-match email lookup and a plain Draft save that could swap identifiers, would have shipped a privacy bug with a passing suite.

## Technical Details

- `bench --site gate_site run-tests --app crm --coverage`: exit 1. 12 failures reproduce identically at HEAD (`git archive HEAD crm` via PYTHONPATH).
- Safety-critical group: 27 modules, each exit 0, 267 tests (`temper-results.json`).
- Backend coverage: 96.2% lines (2032/2113). Lowest is `crm/erasure/post_commit.py` at 81.1%. Branch coverage not measured.
- Frontend: 468 tests, 467 passed. `filesUploader.test.js` timed out at 5000 ms under load. The file is untouched.
- `test_site` held 1190 CRM Leads from 34 committed copies of `crm_lead/test_records.json`. That broke 8 `test_dashboard` tests. The fresh site passes them.
- Spike: `delete_doc("File")` posts an "Attachment Removed" Comment naming her file on her Lead. `__global_search` and `tabError Log` are MyISAM, so a rollback does not restore them.

## What We Tried

- Reading the full-suite failures as a regression. The HEAD diff proved they were pre-existing.
- Using `delete_doc` for files. Rejected: it writes the comment, and it removes disk files only when `content_hash` is set.
- Keeping pending disk-file names only in Redis. Rejected: `allkeys-lru` eviction would leave PII-named files on disk with no DB pointer. Now stored as HMAC hashes in the outcome.
- Trusting the search index after erasure. The queued snapshot re-indexed her email. Fixed by dropping queued entries for her records before sync.
- Controller slips: a reviewer brief went out with an unfilled placeholder. A fake `testCount` was briefly recorded for a build. Builds are not test runs, so it was removed.

## Root Cause Analysis

Erasure is a set of seams: Version, Deleted Document, search index, queue, MyISAM tables, file names, comments, Redis. Our unit tests covered the paths we intended. The defects sat in the places we did not probe: a regex `findall` restarting after a non-atext character, a phone region default of IN that dropped Italian leading zeros, and a File lookup by `file_url` that matched colleagues' deduplicated files. The Draft-save hole crossed two phases, so neither phase's review saw it. The test-site drift was a fixture problem: the suite assumed a clean site.

## Lessons Learned

- In a privacy feature, each seam needs an adversarial probe, written as a failing test before the fix.
- Per-phase review plus a whole-change pass. Neither alone was enough.
- Establish the HEAD baseline before you blame a change for a red suite.
- Run the final gate on a fresh site. A dirty `test_site` manufactures failures.
- Executor writes use `update_modified=False` and raw deletes. Do not trust a rollback to undo MyISAM writes.

## Next Steps

- Privacy Officer sign-off on the whole change. Owner: the Privacy team. Needed before the 2026-11-27 runbook.
- Run the version-15 lane. Owner: whoever runs CI. Before merge.
- Measure branch coverage on the erasure modules. Owner: implementer.
- Review the last `erasure-request-notices.vue` edit, which no reviewer has seen.
- Reconcile `plan.md`: it still lists phases 4 and 5 as In Progress.
- Still undone: Postgres, the 1M-row performance run, the runbook staging dry-run, and the mutation spot-check.
