# Phase 06 — Docs: SPEC, PLAN/ARCHIVE, changelog, user guide

## Context Links
- `AGENTS.md` → "Docs structure" (`.pi/PLAN.md` future, `.pi/SPEC.md` stable contracts, `.pi/ARCHIVE.md`
  done + rationale, `.pi/feats/` user docs); project rule `documentation-management.md` (`docs/project-changelog.md`)
- Consultation report (rationale to archive), phases 01–05

## Overview
- Priority: P2 · Status: complete · Effort: 2h · Depends on: phase 05 (documents what shipped)

## Key Insights
- SPEC holds only stable contracts: the registry entry shape, API endpoints, states, guard rules.
- The rationale (Path A over B/C, no deletion of activity, hold rule) belongs in ARCHIVE, not SPEC.
- `docs/project-changelog.md` does not exist yet; create it with this entry (project rule).

## Requirements
- F1 `.pi/SPEC.md`: new section "Personal data erasure" — registry entry contract, actions, marker
  format, API endpoints + who may call them, state table, delete guard, retention seam, test commands.
- F2 `.pi/ARCHIVE.md`: decision record (paths considered, approval rules, known limitations, Postgres unproven).
- F3 `.pi/feats/personal-data-erasure/guide.md`: rep guide (log, review matches) and PO guide (approve, typed
  confirm, retry, close); link to the runbook.
- F4 `docs/project-changelog.md`: entry "feat: CCPA personal data erasure" (date, impact, new role).
- F5 `.pi/PLAN.md`: add nothing unless a follow-up remains (open items below).

## Architecture
Docs only. Each doc links to `crm/erasure/registry.py` instead of copying the table (DRY); the runbook is
the generated copy from phase 05.

## Related Code Files
- Modify: `.pi/SPEC.md`, `.pi/ARCHIVE.md`, `.pi/PLAN.md` (only if follow-ups)
- Create: `.pi/feats/personal-data-erasure/guide.md`, `docs/project-changelog.md`

## Implementation Steps
1. Read current SPEC/ARCHIVE headings; add sections in their style.
2. Write the guide from the shipped UI labels (phase 04).
3. Changelog entry; check every relative link resolves.

## Todo List
- [x] SPEC section  - [x] ARCHIVE decision record  - [x] feature guide  - [x] changelog  - [x] link check

## Test plan
- Changed: Markdown only. Check: links resolve (`grep -o '](\./[^)]*)'` + file existence); no code tests.
- Deliberately skipped: unit tests (no executable change).

## Success Criteria
SPEC lists every endpoint and state that exists in code (spot-check against `crm/api/erasure.py`); all links
resolve; guide reviewed by Dana/Priya for the pilot.

## Risk Assessment
Docs drift from code (Med/Low) → SPEC points at registry/runbook rather than duplicating them.

## Security Considerations
No real identifiers (Marisol's email) in docs; examples use `example.net` and 555 numbers.

## Next Steps
Resolve open items in plan.md; pilot feedback → follow-up plan if needed.
