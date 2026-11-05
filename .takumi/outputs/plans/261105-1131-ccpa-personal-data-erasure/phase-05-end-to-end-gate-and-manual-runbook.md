# Phase 05 — End-to-end verification gate and manual fallback runbook

## Context Links
- Consultation §1 "Timeline", §5 "manual fallback needs an admin", §6 success measures
- Registry: phase 02 Architecture table (`crm/erasure/registry.py`); oracle: phase 03 `verify.full_scan`
- Dashboard: `crm/api/dashboard.py:27` `get_dashboard`, `get_*` endpoints L210-1276
- CI: `.github/workflows/server-tests.yml` (MariaDB 10.6; version-15 and version-16 lanes, `--coverage`),
  `frontend-tests.yml`

## Overview
- Priority: P1 · Status: pending · Effort: 7h
- Part A (runbook) depends on phase 02 only; deliver by **2026-11-27** so the Privacy team can erase
  Marisol by hand before **2026-12-10** if the feature is not live.
- Part B (E2E gate) depends on phases 03 and 04; it is the single final gate before the December pilot.

## Key Insights
- The runbook is rendered from `REGISTRY` by code, and a test fails when the committed runbook differs
  from the rendering → the manual path and the product can never drift (DRY).
- Manual steps that touch Version, Deleted Document, `__global_search`, Email Queue and logs need a System
  Manager with bench console or Desk System Console; the Privacy team cannot do them alone.
- The E2E test re-enables versioning (tests suppress it) so seeded Version rows exist like in production.

## Requirements
Functional
- A1 `crm/erasure/runbook.py:render_runbook()` → Markdown: prerequisites (System Manager, backup note,
  maintenance window), per registry row (registry order): where to find it (Desk list filter), what to
  change, the SQL/console statement template with `%(email)s`/`%(phone_digits)s` parameters, then hidden
  copies, then the verification query (same SQL as `verify.full_scan`), then the known-limitations list.
- A2 Committed copy at `docs/ccpa-manual-erasure-runbook.md`; `bench execute crm.erasure.runbook.write_runbook`
  regenerates it.
- B1 E2E scenario (Marisol fixture): lead (converted) + Deal A (Won, value) + Deal B (Negotiation) +
  contact with 2 emails/2 phones + Communications (her + colleague on cc), calls with recording URL, notes,
  tasks, comments, CRM Notification, WA profile/messages/log, files on lead and on an email, a previously
  deleted note (Deleted Document), an Email Queue row, Version rows on lead/deal/note/communication.
  Flow: rep logs → submit → On Hold (Deal B open) → owner sets Deal B Lost → Pending Approval → dashboard
  snapshot → rep approve attempt denied → PO approves with typed number → job runs → assertions.
- B2 Assertions: (a) every `dashboard.py` endpoint returns identical values before/after, for manager
  (`user=None`) and the deal owner, over a wide range and the default current month; (b) `verify.full_scan`
  returns zero rows outside `CRM Erasure Request`/`CRM Erasure Identifier`; (c) kept fields unchanged and
  colleague's address still in the cc; (d) outcome has counts and no identifier; (e) second run = no change;
  (f) files gone from disk; (g) delete of her lead blocked before execution, allowed after Closed.
Non-functional
- E2E test < 30 s; runs in the normal `bench run-tests --app crm` gate on both CI lanes.

## Architecture
```
crm/erasure/runbook.py                 render_runbook(registry=REGISTRY) -> str ; write_runbook()
crm/erasure/test_runbook.py            committed file == render_runbook(); every registry doctype appears
crm/erasure/test_end_to_end.py         B1/B2 (fixture builder in crm/erasure/erasure_test_fixtures.py)
docs/ccpa-manual-erasure-runbook.md    generated, committed
```
Dashboard snapshot (pseudocode): `{fn: fn(frm, to, user) for fn in dashboard module get_* with params
(from_date, to_date, user)} | {"get_dashboard": get_dashboard(frm, to)}` → `json.dumps(sort_keys=True,
default=str)`; compare before vs after per user.

## Related Code Files
- Create: the four files above
- Modify: none

## Implementation Steps
1. (Part A, after phase 02) write `test_runbook.py` (RED), `runbook.py`, generate and commit the doc;
   Privacy team + a System Manager dry-run it on a staging copy with a fake person; fix gaps.
2. (Part B) fixture builder; `test_end_to_end.py` written against the final code.
3. Prove it bites: run B2 with phase 03's executor swapped to the git base of one hidden-copy module and
   with one registry row removed (≤3 bounded fault injections, restored and hash-checked) → must fail.
4. Final gate (below); then strengthened-mode extras (safety-critical): SHA-256 manifest of erasure test
   files after RED; ≤5 mutations in changed files (`approval.py` guard flip, `identifiers.py` case fold,
   `hidden_copies.py` Deal filter, `jobs.py` commit order, `erasure_guards.py` status set); classify survivors.

## Todo List
- [ ] Runbook test RED → renderer → doc committed (by 2026-11-27)
- [ ] Staging dry-run with Privacy team + System Manager
- [ ] Fixture + E2E test  - [ ] fault injections  - [ ] final gate  - [ ] mutation spot-check + manifest

## Test plan
- Scope Contract — Changed: whole erasure subsystem (phases 01–04). Impacted: Lead/Deal/Contact delete
  paths, Deal save hook, dashboard, activity timelines, WhatsApp hooks. Will verify: whole erasure group +
  `crm_lead`, `crm_deal`, `crm_call_log`, `test_whatsapp`, dashboard-related tests; frontend unit suite.
  Deliberately skipped: browser e2e (logic proven below the UI; UI wiring checked by build + phase 04 smoke);
  Postgres (CI runs MariaDB only — stays unproven, noted in SPEC).

| AC / invariant | Test | Level | Why | Est. |
|---|---|---|---|---|
| Dashboard numbers do not move (R4) | `test_end_to_end::test_dashboard_parity` | Integration | Real SQL aggregates | ~5s |
| Zero rows match her identifiers DB-wide | `test_end_to_end::test_full_scan_zero` | Integration | All tables | ~10s |
| Two-person rule end-to-end | `test_end_to_end::test_rep_cannot_approve` | Integration | Session switch | ~1s |
| Idempotent re-run | `test_end_to_end::test_rerun_noop` | Integration | | ~3s |
| Runbook in sync with registry | `test_runbook` | Unit (string compare) | Pure render | <1s |
- Plausible bugs: dashboard moves because `modified`/`creation` touched or a Lead deleted; full scan
  misses formatted phones (scan uses digits-only); colleague's data erased; runbook stale after registry edit.
- Final gate: `bench --site test_site run-tests --app crm --coverage` (exit code recorded) and
  `cd frontend && yarn test:run && yarn build`. Coverage on `crm/erasure/*` and the doctype folder ≥ 90%
  line / 80% branch; frontend utils via `yarn test:coverage`.

## Success Criteria
Final gate exit 0 on both CI lanes; dashboard parity and full-scan tests GREEN; runbook dry-run signed off
by the Privacy team before 2026-12-01; mutation survivors classified.

## Risk Assessment
- Feature slips past Dec 10 (Med/High) → Part A ships first; Marisol handled by runbook.
- Full scan slow on CI DB (Low/Low) → test DB is small; production uses it only from the runbook.

## Security Considerations
Fixture uses `example.net` addresses and 555 numbers only. Runbook SQL is parameterised; it never embeds
a real identifier and instructs not to paste identifiers into tickets or chat.

## Next Steps
Phase 06 docs; December pilot with the Privacy team; all reps live 2027-01-15.
