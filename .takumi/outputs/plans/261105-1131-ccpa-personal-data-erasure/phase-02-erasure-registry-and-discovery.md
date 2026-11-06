# Phase 02 — Erasure registry, identifier matching, discovery, preview

## Context Links
- Consultation §2 "Where her data lives", §4.3; §5 "Phone normalization is the weakest link"
- Research (this plan): `reports/frappe-v16-api-verification.md` (fields of Contact, Address, Communication,
  Comment, Email Queue, Notification Log, Version, Deleted Document, WA Profile/Message/Log)
- Code: `crm/utils/__init__.py:28` `normalize_phone`, `:50` `phone_search_digits`; `crm/integrations/api.py:195`
  `find_by_phone` (LIKE-prefilter → normalize pattern to copy); `crm/api/activities.py:448-640` (how
  calls/notes/tasks link via `reference_*` and `Dynamic Link`); `crm/hooks.py:16,280` (whatsapp app, `WA Message`)

## Overview
- Priority: P1 · Status: complete · Effort: 9h · Depends on: phase 01
- One declarative table says where a person's data lives and what happens to it. Discovery walks that table
  for a request and returns match rows (doc names only); the rep reviews and excludes, then submits.

## Key Insights
- The WhatsApp source is the `whatsapp` app (`WA Message`, `WA Profile`, `WA Log`), not frappe_whatsapp's
  `WhatsApp Message` (migrated by `crm/patches/v1_0/migrate_from_frappe_whatsapp.py`). `WA Profile` names are
  hashes, so it can be anonymized in place; `WA Message.from` holds her number on incoming rows; `WA Log`
  keeps raw webhook JSON with phone + text and has no link field → found by text scan only.
- Reuse `normalize_phone` / `phone_search_digits` (DRY, same E.164 rules as telephony lookup).
- A deal belongs to the organization too. Deal person fields are scrubbed only when they are hers
  (`deal.contact` is her contact, or deal email/phone match); her `CRM Contacts` row is always scrubbed.
- Communication `content`/`recipients`/`cc`/`bcc` never appear in Version diffs (Text Editor/Code skipped);
  `subject`, `sender`, `sender_full_name`, `phone_no` do.
- Name-only matches are never produced: every non-linked match needs an email or phone hit.

## Requirements
Functional
- F1 `REGISTRY`: ordered tuple of entries `{doctype, kind: person|activity|file|hidden, found_by, action,
  fields, keep}`; one place to add a source. Actions: `scrub`, `replace_content`, `delete_permanently`,
  `purge`, `filter_entries`.
- F2 Identifiers: emails lower-cased + trimmed, exact match (no substring: `ann@x.com` ≠ `joann@x.com`);
  phones via `normalize_phone`; values that normalize to empty are rejected at log time.
- F3 Discovery returns `[{ref_doctype, ref_name, reason: linked|email|phone|activity, action}]`, de-duplicated,
  ordered by registry order. Hidden copies are returned as counts per doctype, not rows.
- F4 `preview(request)` = discovery grouped by doctype with counts + hidden-copy counts; no PII in payload
  beyond doc titles the caller can already read (titles are permission-checked).
- F5 API (`crm/api/erasure.py`, whitelisted, type-annotated per `require_type_annotated_api_methods`):
  `log_request(source_doctype, source_docname, subject_name, received_on, emails, phones)` → Draft + matches;
  `refresh_matches(name)`; `set_exclusions(name, excluded: list[str])` (Draft only, requester);
  `submit_for_approval(name)` → hold check (phase 01) → Pending Approval | On Hold;
  `get_preview(name)` (requester or Privacy Officer).
- F6 Re-discovery diff helper `diff_matches(stored, current)` → new rows flagged `new_since_logging`;
  used by phase 03.
Non-functional
- Discovery for one person < 5 s on a site with 1M Communication rows (LIKE prefilter on indexed-ish
  columns, then exact compare in Python). Read-only; never writes outside the request doc.

## Architecture — the registry (source of truth, also renders the runbook in phase 05)
| Doctype | Found by | Action | Fields (kept fields in brackets) |
|---|---|---|---|
| CRM Lead | source; email/mobile_no/phone; `CRM Deal.lead` of her deals | scrub | salutation, first/middle/last_name, lead_name, email, mobile_no, phone, gender, job_title, image, linkedin, twitter, facebook, facebook_lead_id; lost_notes→marker [status, source, owner, territory, organization, values, dates] |
| CRM Deal | lead's deals; her `CRM Contacts` row; email/mobile_no/phone; `contact` | scrub (if hers) | salutation, first/last_name, lead_name, email, mobile_no, phone, gender, job_title; lost_notes→marker [status, value, probability, dates, owner, org] |
| CRM Contacts (Deal child) | `contact` = her Contact; email/phone | scrub | full_name→marker, email, mobile_no, phone, gender |
| Contact (+Contact Email/Phone) | source; Contact Email.email_id; Contact Phone.phone; email_id/phone/mobile_no | scrub; delete email/phone child rows | names, full_name, email_id, phone, mobile_no, image, salutation, gender, designation, department, user, google_contacts_id [links, company_name] |
| Address | Dynamic Link → her Contact | scrub if linked only to her, else unlink | address_title, address_line1/2, city, county, state, pincode, email_id, phone, fax |
| Dynamic Link / Communication Link | `link_name` = her Lead/Deal/Contact | scrub | link_title→marker |
| Communication | reference/timeline_links to her docs; sender/recipients/cc/bcc; phone_no | replace_content + scrub | subject, content, text_content→marker; her address removed from sender, sender_full_name, recipients, cc, bcc; phone_no |
| Comment | reference to her docs or her activities; comment_email | replace_content | content, subject; comment_email/comment_by/ip_address if hers |
| FCRM Note | reference to her docs; `CRM Call Log.note` | replace_content | title, content |
| CRM Task / ToDo | reference to her docs / to her CRM Tasks | replace_content | title, description / description |
| CRM Call Log | reference + `links` to her docs; from/to (normalized) | scrub | from/to if hers, recording_url |
| CRM Notification | reference_* or notification_type_doc in matched set | replace_content | message, notification_text |
| Notification Log | document_type/name in matched set | replace_content | title, subject, description, email_content |
| WA Profile | phone_number/wa_id; links → her docs | scrub; drop her link rows | phone_number, wa_id, profile_name→marker |
| WA Message | `to` ∈ her profiles; reference her docs; `from` | replace_content + scrub | message, reaction, template_*_parameters, interactive_* →marker/None; media_url, media_id, attach→None; from if hers |
| File | attached to any matched doc; Lead/Contact image | delete_permanently (after commit) | — |
| Version | ref = any matched doc; data matches identifiers | purge; CRM Deal and unmatched refs → filter_entries | changed/added/removed/row_changed entries naming person fields or her identifiers |
| Deleted Document | data matches identifiers | purge | — |
| `__global_search` | matched docs; content matches identifiers | delete + re-index | — |
| Email Queue (+Recipient) | recipient = her email; reference/communication in matched set | purge | — |
| WA Log, Error Log | request_data/response_data/message/error text matches identifiers | purge | — |
| `_comments` column | her Lead/Deal/Contact | rewrite to `{name}`-only entries | — |

Marker = `Content erased <REQ-no>`; person-name marker = `Erased <REQ-no>`.

```
crm/erasure/
  registry.py         REGISTRY entries + PERSON_FIELDS + KNOWN_LIMITATIONS (data only, ~150 lines)
  identifiers.py      normalize_email, Identifiers(emails, phones), matches_text(text) for JSON/text scans
  discovery.py        discover(request) -> MatchSet ; seeds -> activities -> identifier hits -> hidden counts
  discovery_queries.py one query builder per found_by kind (link / email column / phone column / text scan)
crm/api/erasure.py    whitelisted endpoints (F5), permission checks, no business logic
```
Data flow: rep dialog → `log_request` → insert request (identifiers) → `discover` → `matches` rows (names only)
→ rep excludes → `submit_for_approval` → phase 01 hold check.

## Related Code Files
- Create: `crm/erasure/{__init__,registry,identifiers,discovery,discovery_queries}.py`, `crm/api/erasure.py`,
  tests `crm/erasure/test_identifiers.py` (unit), `crm/erasure/test_registry_integrity.py` (meta check),
  `crm/erasure/test_discovery.py` (integration)
- Modify: none outside the new package (phase 01 owns the doctype)

## Implementation Steps
1. Tests first (table below); skeleton modules returning empty results; record RED.
2. `identifiers.py`; parameterise phone cases with real formats from the data (`(415) 555-0123`,
   `+1 415-555-0123`, `4155550123`, `001 415 555 0123`, extension `x12`).
3. `registry.py` as data; integrity test asserts every listed field exists in `frappe.get_meta`
   (skip whatsapp entries if the app is absent → test asserts the skip is explicit, not silent).
4. `discovery_queries.py`: link lookups; email columns via `LIKE %x%` prefilter + exact token compare
   (comma/angle-bracket parsing via `frappe.utils.parse_addr`); phone columns via `phone_search_digits`
   prefilter + `normalize_phone` compare; text scans for hidden copies.
5. `discovery.py` + `diff_matches`; `crm/api/erasure.py` endpoints with permission checks.
6. GREEN, refactor, module run.

## Todo List
- [x] RED tests  - [x] identifiers  - [x] registry + integrity test  - [x] queries  - [x] discovery + diff
- [x] API endpoints with permission checks  - [x] GREEN

## Test plan
- Changed: new package + API. Impacted: none at runtime until phase 03 executes. Risk: **safety-critical**
  (a missed match = PII left behind; a false match = someone else's data erased).

| AC / risk | Test | Level | Why | Est. |
|---|---|---|---|---|
| F2 email exact, case-insensitive, no substring; phones across formats; empty/invalid rejected | `test_identifiers` table | Unit | Pure | <1s |
| F1 every registry field exists in meta; every action known | `test_registry_integrity` | Integration (meta) | Needs installed doctypes | <1s |
| F3 Marisol fixture: lead + 2 deals + contact + emails/calls/notes/tasks/comments/WA/files all found | `test_discovery::test_finds_every_source` (count per doctype asserted) | Integration | Real SQL joins + LIKE | ~3s |
| F3 near-misses not found: `joann@` vs `ann@`, other person same name, colleague's phone differing by one digit | `test_discovery::test_near_misses` | Integration | SQL prefilter + compare | ~1s |
| F3 colleague's deal person fields untouched when she is a secondary contact | `test_discovery::test_secondary_contact_deal` | Integration | Join logic | ~1s |
| F5 Sales User can't preview others' requests; non-requester can't set exclusions; non-Draft exclusions rejected | `test_erasure_api` | Integration | Permission boundary | ~2s |
| F6 diff flags only new rows | `test_identifiers::test_diff_matches` (pure) | Unit | Pure set diff | <1s |
- Plausible bugs: substring email match; case-sensitive email; phone with country code vs without
  unmatched; extension breaks normalization; deal person fields of a colleague scrubbed; WA messages via
  profile missed; Comment on a matched Communication missed; duplicate match rows; name-only match added.
- TDD: RED for each row. While coding: `bench --site test_site run-tests --app crm --module crm.erasure.test_discovery`
- Coverage: 90/80 on `crm/erasure/*` at the phase 05 gate.

## Success Criteria
Fixture finds every seeded source with exact per-doctype counts; zero near-miss hits; API denies all
listed permission cases while the positive controls pass.

## Risk Assessment
- Phone normalization misses a real format (High/High) → table from real data; residual scan in phase 03
  catches what discovery missed and fails the run.
- LIKE scans slow on large Communication/Version tables (Med/Med) → run once per request; executor runs as a
  long-queue job (phase 03).

## Security Considerations
Endpoints check `frappe.has_permission` on the request and on the source doc; match titles returned only for
docs the caller can read (else name only). No identifier is logged.

## Next Steps
Phase 03 executes the registry; phase 04 renders preview/exclusions; phase 05 renders the runbook from it.
