---
title: "CCPA personal data erasure"
description: "Reps log a person's erasure request in the CRM; a Privacy Officer approves; a registry-driven service anonymizes her data without moving dashboard numbers."
status: in-progress
priority: P1
effort: 48h
branch: develop
tags: [ccpa, privacy, personal-data, data-mutation, backend, frontend, safety-critical]
created: 2026-11-05
---

# CCPA personal data erasure

Sources: `.takumi/outputs/reports/261105-1111-personal-data-erasure-consultation.md` (approved, Path A);
`03-slack-thread.txt`; `04-emails.txt`; `reports/frappe-v16-api-verification.md` (this plan)

## Overview
New `CRM Erasure Request` doctype + `Privacy Officer` role + a declarative registry (`crm/erasure/`) that
drives discover → preview → execute. Lead/Deal/Contact are anonymized in place; activity keeps its rows with
`Content erased <REQ-no>`; files are deleted permanently; Version, Deleted Document, global search, Email
Queue, WA/Error logs are purged or filtered. Two-person rule, On Hold on open deals, typed confirmation and
the delete guard are enforced in Python. Safety-critical: tests first, whole erasure group at every gate.

## Phases
| # | Phase | Status | Effort | Depends on |
|---|---|---|---|---|
| 1 | [Request doctype, role, states, deadlines, delete guard](./phase-01-request-doctype-role-states-guards.md) | Complete | 7h | — |
| 2 | [Erasure registry and discovery](./phase-02-erasure-registry-and-discovery.md) | Complete | 9h | 1 |
| 3 | [Approval, execution and hidden copies](./phase-03-approval-execution-and-hidden-copies.md) | Complete | 13h | 1, 2 |
| 4 | [Vue log dialog and request pages](./phase-04-vue-log-dialog-and-request-pages.md) | In Progress | 10h | 2 (3 for approve wiring; parallel with 3, frontend files only) |
| 5 | [End-to-end gate and manual runbook](./phase-05-end-to-end-gate-and-manual-runbook.md) | In Progress | 7h | Part A: 2 · Part B: 3, 4 |
| 6 | [Docs: SPEC, archive, changelog, guide](./phase-06-docs-spec-and-changelog.md) | Complete | 2h | 5 |

## Key dependencies and milestones
- Frappe v16 (CI also runs a version-15 lane) · `whatsapp` app (`WA Message`/`WA Profile`/`WA Log`) ·
  MariaDB (Postgres unproven).
- 2026-11-27 runbook (phase 5A) ready → manual fallback for Marisol (response due **2026-12-10**).
- Nov 2026 build · Dec 2026 Privacy team pilot · **2027-01-15** all reps live.
- File ownership: phases 3 (backend `crm/erasure/*`, `crm/api/erasure.py`) and 4 (`frontend/*`) share no file.
- Way back: each phase is additive (new doctype/package/files + hook entries); revert the phase's commits.
  Executed erasures are irreversible by design (backups out of scope, R5).

## Open items (unresolved)
1. **What the request record retains after execution** (Dana; CCPA 24-month record keeping). Build keeps
   identifiers until Close; `apply_retention()` (phase 3) is the single place to change it. Default proposed:
   masked email/phone + REQ number + dates, name dropped.
2. **Where the Privacy Officer works** (default: CRM UI pages from phase 4; Desk form remains for admins).
3. **Whether Sales User loses global delete on Lead/Deal** (Priya; separate decision — this plan only
   blocks delete while a request is open).
