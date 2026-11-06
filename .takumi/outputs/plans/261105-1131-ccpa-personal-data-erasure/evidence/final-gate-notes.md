# Final gate notes (2026-11-05)

Environment: docker `crmtest-frappe`, Frappe 16.55.2 (version-16), whatsapp app, MariaDB 10.6.
Version-15 lane: NOT run (verification incomplete for that lane).

## Full app run on a fresh site (CI-like)

`bench new-site gate_site` + install whatsapp + crm (exit 0), then
`bench --site gate_site run-tests --app crm --coverage` → **exit 1**:
682 tests FAILED (errors=2); 155 tests FAILED (failures=1, errors=9, skipped=26); 192 OK; 32 OK.

The 12 non-passing tests are pre-existing — the same 12 fail on the same fresh site with HEAD's `crm`
package (no erasure code; `git archive HEAD crm`, imported first via PYTHONPATH):

| Module | HEAD baseline | With change |
|---|---|---|
| crm.tests.test_email (TestCancelScheduledEmail) | 9 errors | 9 errors |
| crm.tests.test_event_reminders | 1 error | 1 error |
| crm.tests.test_search_sqlite (`add_to_queue` missing in Frappe 16.55.2) | 1 error | 1 error |
| crm.fcrm.doctype.crm_invitation.test_crm_invitation | 1 failure | 1 failure |

On the long-lived `test_site` an earlier full run also failed 8 `crm.tests.test_dashboard` tests: that site
holds 1190 CRM Leads (34 committed copies of `crm_lead/test_records.json`, one per test run today);
on the fresh site those 8 pass.

## Safety-critical group (temper-results.json)

27 modules (all erasure modules + crm_deal + crm_lead) run one by one on gate_site, all exit 0, 266 tests.

## Coverage (changed logic)

- Backend, from gate_site `coverage.xml`: 96.2% lines (2032/2113) over 43 erasure modules; lowest
  `crm/erasure/post_commit.py` 81.1%. Branch coverage: not measured (bench `--coverage` records lines only).
- Frontend erasure utils + navigation: 100% lines, 96.49% branches (vitest v8).

## Final tree (after Stage 5 fix rounds 1–2)

`bench --site gate_site migrate` exit 0; the 27-module safety-critical group re-run, all exit 0, 267 tests
(temper-results.json). Frontend `yarn test:run`: 468 tests, 467 passed, 1 failed (same filesUploader
timeout); that file plus all erasure/navigation tests re-run alone: 6 files, 88 passed, exit 0.
`yarn build` exit 0 (built after the last frontend edit). The full `--app crm` run was not repeated on the
final tree; the fix rounds touched only erasure files, whose whole group is above.
Last frontend edit (erasure-request-notices.vue neutral "cleanup pending" note) was made after the
round-2 reviewer verdict and is not covered by a review.

## Frontend (first gate)

`yarn test:run`: 463 tests, 462 passed, 1 failed — `tests/unit/filesUploader.test.js` timed out at 5000 ms
under container load (untouched file; passed alone earlier this session). `yarn build`: passed.
