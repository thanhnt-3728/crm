# Project Changelog

## 2026-11-05

### feat: CCPA personal data erasure

Reps log an erasure request from a Lead, Deal or Contact; a Privacy Officer approves it; a registry-driven background job anonymizes the person's data without changing activity counts.

**Impact**
- New doctypes `CRM Erasure Request`, `CRM Erasure Identifier`, `CRM Erasure Match`; new package `crm/erasure/`; new endpoints in `crm/api/erasure.py` (POST only).
- New CRM pages `Erasure Requests` and `Erasure Request`, a "Log erasure request" action on Lead, Deal and Contact, and a sidebar entry for System Manager, Sales Manager, Sales User and Privacy Officer.
- Behavior change: while an erasure request is open (Draft, Pending Approval, On Hold, Approved), the person's Lead, Deal and Contact cannot be deleted or renamed. Deal updates and deletes now re-evaluate the On Hold rule.
- Executed erasures are irreversible; backups are out of scope.
- Safety-critical (data deletion, permissions). Known limitations are listed in `crm/erasure/registry.py`. MariaDB only; Postgres is unproven.

**New role**: `Privacy Officer`, additive (holders also need a CRM role). Created on install and by patch `crm.patches.v1_0.add_privacy_officer_role` for existing sites (run `bench migrate`).

**New setting**: `FCRM Settings > Erasure Request Holiday List` (`erasure_holiday_list`, Link to `CRM Holiday List`): holidays skipped when counting the 10 business days to acknowledge a request. Empty means weekends only.

**Docs**: [SPEC](../.pi/SPEC.md#personal-data-erasure), [decision record](../.pi/ARCHIVE.md#ccpa-personal-data-erasure), [user guide](../.pi/feats/personal-data-erasure/guide.md), [manual runbook](./ccpa-manual-erasure-runbook.md).
