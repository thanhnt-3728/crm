# Personal Data Erasure Requests (CCPA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any CRM user log a CCPA erasure request, have Compliance (never the logger) approve it after seeing exactly what happens, erase the person everywhere the CRM holds them without moving any dashboard number, track the 10-business-day / 45-day deadlines with reminders, and keep only a 24-month log entry plus a hashed do-not-contact block afterwards.

**Architecture:**
- **Data model:** new FCRM doctypes. `CRM Erasure Request` has child tables for identifiers, matched records and the checklist. There are also `CRM Do Not Contact`, `CRM Retained Contract`, and a single `CRM Privacy Settings` holding the editable personal-fields list.
- **Logic:** a plain Python package `crm/privacy/` holds the logic in focused modules: deadlines, identifiers, matching, preview, erasure, blocking, inbound, reminders and retention. Whitelisted endpoints live in `crm/api/erasure.py`.
- **How erasure writes:** erasure runs as one background job in one DB transaction. It writes with `frappe.db.set_value(..., update_modified=False)`, never `doc.save()`, so no new `Version` rows or automation hooks capture the old values.
- **UI:** Vue pages in the CRM UI: a list, a detail page, an approval modal, a log-request modal and a settings page.

**Tech Stack:** Frappe (Python, `IntegrationTestCase`), Vue 3 + frappe-ui, vitest.

**Spec:** `docs/superpowers/specs/2026-11-05-ccpa-erasure-requests-design.md`. Read it before any task. Section numbers below (§) refer to it.

## Global Constraints

- **Request naming:** `PDR-.####` (e.g. `PDR-0001`).
- **Placeholders, exact strings:**
  - Names and addresses: `Erased person {request_name}`.
  - Text and content: `Content erased {request_name}`.
- **Request type:** always `Erasure`. Channels: `Email`, `Phone`, `Web form`, `Mail`, `Other`.
- **Statuses:** `Logged`, `Awaiting Sign-off`, `On Hold`, `Erasing`, `Erased`, `Declined`, `Closed`. `Erasing` is a transient lock while the job runs.
- **Outcomes:** `Completed`, `Partly completed`, `Denied`. `Denied` and `Declined` both require `denial_reason`.
- **Deadlines:**
  - respond_by = received_on + 45 calendar days.
  - acknowledge_by = 10th business day after received_on (Mon–Fri, excluding US federal holidays with observed dates). Counting starts the day after.
- **Reminders:**
  - Acknowledgment: if unticked when today ≥ the date 3 business days before acknowledge_by, remind all Compliance users.
  - Day 30 (received_on + 30): remind all Compliance users.
  - Day 40 (received_on + 40): alert the Head of Compliance.
  - All reminders are sent only while status ≠ `Closed`, once each, as both a CRM Notification and an email.
- **Retention:** a closed request (the log entry) is deleted 24 months after `answered_on`. A retained-contract entry is deleted on its `delete_after` date.
- **Approval:** the approver must hold role `Compliance` and must not be `logged_by`. This is checked on the server, by user. Sales Managers and System Managers cannot approve without `Compliance`.
- **Visibility:**
  - `Compliance` and `Sales Manager` see all requests in full.
  - The logger sees their own request in full only while it's `Logged`. After that they see only status, received_on, acknowledge_by, respond_by and days left.
  - Nobody else sees requests at all.
- **`Compliance` is additive.** Compliance members also hold `Sales User` or `Sales Manager`, so they can open the linked leads, deals and contacts. `Compliance` is added to `CRM_ALLOWED_ROLES` only so the session flag works. *(plan-level call)*
- **Writes during erasure and close:**
  - Never call `doc.save()` on erased records. Use `frappe.db.set_value(..., update_modified=False)` or `frappe.db.delete`.
  - Files are deleted physically only via `frappe.db.after_commit`.
  - Anything deleted outright uses `frappe.delete_doc(..., delete_permanently=True, ignore_permissions=True)`, so no `Deleted Document` copy is made.
- **Dashboard numbers must be identical before and after erasure.** Leads and deals are never deleted.
- **Python tests:** `IntegrationTestCase`, files in `crm/tests/test_privacy_*.py`. Run with `bench --site <test-site> run-tests --app crm --module <module>`. No bench exists in this sandbox, so run them on a bench site.
- **Frontend tests:** `cd frontend && yarn test:run`. All existing tests must stay green.
- **Commit style:** `feat:` / `test:` / `docs:`, one commit per task, each ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Recipient strings with display names and odd casing.** `Communication.recipients`/`cc`/`bcc`/`sender` hold `"Marisol Vega" <Marisol.Vega@x.net>, bob@x.net`. A confirmed `marisol.vega@x.net` must match regardless of case or display name. Only her entry is replaced; `bob@x.net` stays. → test in Task 8.
2. **Phones typed differently.** `(916) 555-0100`, `916.555.0100` and `+19165550100` must all match one confirmed identifier, whether in call logs, blocking or the do-not-contact hash. → tests in Tasks 3, 8 and 10.
3. **A request logged late.** received_on is already 41 days ago. One reminder run sends the acknowledgment reminder, day-30 and day-40 once each, and a second run sends nothing. → test in Task 11.
4. **Double approval.** Two approve clicks, or two Compliance users at once. The second gets an error, and only one job runs. → test in Task 9.
5. **She's a non-primary contact on a closed deal.** The primary contact's email, mobile and phone on the deal are untouched. → test in Task 7.

---

## File Map

**Backend: create**
- `crm/fcrm/doctype/crm_privacy_settings/`: Single doctype.
  - `head_of_compliance` (Link User)
  - `contract_retention_months` (Int, default 0 = keep until counsel sets)
  - `hash_secret` (Password, auto-generated on first save)
  - `personal_fields` (Table → CRM Personal Field)
- `crm/fcrm/doctype/crm_personal_field/`: child table.
  - `document_type` (Select: `CRM Lead`, `CRM Deal`, `Contact`, `CRM Contacts`, `Address`)
  - `fieldname` (Data)
- `crm/fcrm/doctype/crm_erasure_request/`: main doctype (`.json`, `.py`, `test_crm_erasure_request.py`).
- `crm/fcrm/doctype/crm_erasure_identifier/`: child.
  - `kind` (Select Email/Phone)
  - `value` (Data)
  - `excluded` (Check)
  - `match_count` (Int, read only)
- `crm/fcrm/doctype/crm_erasure_match/`: child.
  - `reference_doctype` (Link DocType)
  - `reference_name` (Dynamic Link)
  - `confirmed` (Check)
  - `source` (Select: `Started from`, `Identifier match`, `Linked record`)
  - `removed_from_open_deal` (Check, read only)
- `crm/fcrm/doctype/crm_erasure_checklist_item/`: child.
  - `description` (Data)
  - `auto_added` (Check)
  - `done` (Check)
  - `done_by` (Link User)
  - `done_on` (Datetime)
- `crm/fcrm/doctype/crm_do_not_contact/`: `kind` (Select Email/Phone), `value_hash` (Data, unique, indexed). Autoname hash.
- `crm/fcrm/doctype/crm_retained_contract/`:
  - `person_name` (Data)
  - `contract_reference` (Data)
  - `delete_after` (Date)
  - `request` (Data, the request number as text; not a Link, since the request is deleted at 24 months)
- `crm/privacy/__init__.py`, `deadlines.py`, `identifiers.py`, `matching.py`, `preview.py`, `erasure.py`, `blocking.py`, `inbound.py`, `reminders.py`, `retention.py`, `notify.py`
- `crm/api/erasure.py`: whitelisted endpoints.
- `crm/patches/v1_0/add_privacy_setup.py`
- `crm/tests/test_privacy_deadlines.py`, `test_privacy_identifiers.py`, `test_privacy_matching.py`, `test_privacy_preview.py`, `test_privacy_erasure_records.py`, `test_privacy_erasure_content.py`, `test_privacy_api.py`, `test_privacy_blocking.py`, `test_privacy_reminders.py`

**Backend: modify**
- `crm/hooks.py`: `doc_events`, `scheduler_events.daily`, `has_permission`, `permission_query_conditions`.
- `crm/install.py`: `after_install` calls `crm.privacy.setup.ensure_privacy_setup()`.
- `crm/patches.txt`
- `crm/api/session.py`: `CRM_ALLOWED_ROLES` and `is_compliance` flag.
- `crm/utils/__init__.py`: `create_lead_from_incoming_email` early return.
- `crm/fcrm/doctype/crm_notification/crm_notification.json`: add `Privacy` to `type` options.

**Frontend: create**
- `frontend/src/utils/erasureRequest.js` + `frontend/tests/unit/erasureRequest.test.js`
- `frontend/src/pages/ErasureRequests.vue`, `frontend/src/pages/ErasureRequest.vue`
- `frontend/src/components/Modals/LogErasureRequestModal.vue`, `frontend/src/components/Modals/ApproveErasureModal.vue`
- `frontend/src/components/Settings/PrivacySettings.vue`

**Frontend: modify**
- `frontend/src/router.js`
- `frontend/src/components/Layouts/AppSidebar.vue`
- `frontend/src/components/Settings/Settings.vue`
- `frontend/src/pages/Lead.vue`, `Deal.vue`, `Contact.vue`: "Request erasure" action. Add it to the same header actions and command list where `deleteLeadCommand()` is registered (`Lead.vue:451`), and the equivalents in Deal and Contact.
- The session store reading `is_sales_manager`: add `is_compliance` the same way. Grep `is_sales_manager` in `frontend/src`.

---

### Task 1: Privacy settings, Compliance role, notification helper

**Files:**
- Create: `crm/fcrm/doctype/crm_privacy_settings/*`, `crm/fcrm/doctype/crm_personal_field/*`, `crm/privacy/__init__.py`, `crm/privacy/setup.py`, `crm/privacy/notify.py`, `crm/patches/v1_0/add_privacy_setup.py`
- Modify: `crm/install.py`, `crm/patches.txt`, `crm/api/session.py`, `crm_notification.json`
- Test: `crm/tests/test_privacy_setup.py`

**Interfaces:**
- Produces:
  - `crm.privacy.setup.ensure_privacy_setup() -> None` (idempotent)
  - `crm.privacy.setup.DEFAULT_PERSONAL_FIELDS: dict[str, list[str]]`
  - `crm.privacy.settings() -> CRMPrivacySettings` (cached `frappe.get_cached_doc`)
  - `crm.privacy.personal_fields(doctype: str) -> set[str]`
  - `crm.privacy.compliance_users() -> list[str]` (enabled users with role Compliance)
  - `crm.privacy.notify.notify(users: list[str], subject: str, message: str, request: str | None = None, reference_doctype: str | None = None, reference_name: str | None = None) -> None`

`DEFAULT_PERSONAL_FIELDS` (§5.1). These are exactly what the doc ships:
- `CRM Lead`: salutation, first_name, middle_name, last_name, lead_name, gender, email, mobile_no, phone, job_title, image, linkedin, twitter, facebook
- `CRM Deal`: salutation, first_name, last_name, lead_name, gender, email, mobile_no, phone, job_title, linkedin, twitter, facebook
- `Contact`: salutation, first_name, middle_name, last_name, full_name, gender, email_id, mobile_no, phone, designation, image
- `CRM Contacts`: full_name, email, mobile_no, phone, gender
- `Address`: address_title, address_line1, address_line2, city, county, state, pincode, email_id, phone, fax

- [ ] **Step 1: Write the failing tests**

```python
class TestPrivacySetup(IntegrationTestCase):
    def test_role_exists(self):
        ensure_privacy_setup()
        self.assertTrue(frappe.db.exists("Role", "Compliance"))

    def test_default_personal_fields_seeded_once(self):
        ensure_privacy_setup(); ensure_privacy_setup()
        self.assertIn("linkedin", personal_fields("CRM Lead"))
        self.assertIn("designation", personal_fields("Contact"))
        rows = frappe.get_single("CRM Privacy Settings").personal_fields
        self.assertEqual(len(rows), sum(len(v) for v in DEFAULT_PERSONAL_FIELDS.values()))

    def test_hash_secret_generated(self):
        ensure_privacy_setup()
        self.assertTrue(frappe.get_single("CRM Privacy Settings").get_password("hash_secret"))

    def test_session_flag_is_compliance(self):
        # user with Sales User + Compliance
        self.assertTrue(get_session_role_flags()["is_compliance"])

    def test_notify_creates_crm_notification_and_email(self):
        notify(["c1@example.com"], "Subject", "Body", request="PDR-0001")
        self.assertTrue(frappe.db.exists("CRM Notification", {"to_user": "c1@example.com", "type": "Privacy"}))
        self.assertTrue(frappe.db.exists("Email Queue", {"message": ["like", "%Body%"]}))
```

- [ ] **Step 2: Run the tests and confirm they fail.** Run `bench --site <test-site> run-tests --app crm --module crm.tests.test_privacy_setup`. Expected: ImportError / failures.
- [ ] **Step 3: Create the two doctypes** with the fields in the File Map. Settings permissions: System Manager and Compliance (read/write).
- [ ] **Step 4: Implement `ensure_privacy_setup`.** Create the Role `Compliance` (desk_access 1) if missing. Seed `personal_fields` only when the table is empty. Generate `hash_secret` with `frappe.generate_hash(length=64)` if empty. Call it from `after_install` and from patch `crm.patches.v1_0.add_privacy_setup`, appended to `patches.txt`.
- [ ] **Step 5: Add `Compliance` to the session.** Add it to `CRM_ALLOWED_ROLES`. Add `"is_compliance": "Compliance" in roles` to `get_session_role_flags`.
- [ ] **Step 6: Add `Privacy` to the `type` options** of CRM Notification. Implement `notify`: one `CRM Notification` per user (`from_user` = Administrator), plus one `frappe.sendmail(recipients=users, subject=..., message=...)`.
- [ ] **Step 7: Run the tests and confirm they pass.**
- [ ] **Step 8: Commit** with `feat: add privacy settings, Compliance role and notify helper`.

---

### Task 2: Deadline arithmetic

**Files:** Create `crm/privacy/deadlines.py`. Test `crm/tests/test_privacy_deadlines.py`.

**Interfaces:**
- Produces:
  - `us_federal_holidays(year: int) -> set[date]` (observed dates)
  - `is_business_day(d: date) -> bool`
  - `add_business_days(start: date, n: int) -> date` (counts from the day after `start`)
  - `subtract_business_days(end: date, n: int) -> date`
  - `acknowledge_by(received: date) -> date`
  - `respond_by(received: date) -> date`
  - `days_left(received: date, today: date) -> int` (may go negative)
  - `day_number(received: date, today: date) -> int`

**Holidays:**
- New Year's Day (Jan 1), MLK Day (3rd Mon Jan), Washington's Birthday (3rd Mon Feb), Memorial Day (last Mon May), Juneteenth (Jun 19), Independence Day (Jul 4), Labor Day (1st Mon Sep), Columbus Day (2nd Mon Oct), Veterans Day (Nov 11), Thanksgiving (4th Thu Nov), Christmas (Dec 25).
- A fixed-date holiday on Saturday is observed on Friday. One on Sunday is observed on Monday.
- Include next year's Jan 1 observed on Dec 31 when it falls on a Saturday.

- [ ] **Step 1: Write the failing tests**

```python
def test_marisol_dates(self):
    self.assertEqual(acknowledge_by(date(2026,10,26)), date(2026,11,9))
    self.assertEqual(respond_by(date(2026,10,26)), date(2026,12,10))

def test_holidays_2026(self):
    h = us_federal_holidays(2026)
    self.assertIn(date(2026,7,3), h)    # Jul 4 is Saturday → observed Fri
    self.assertIn(date(2026,11,26), h)  # Thanksgiving
    self.assertIn(date(2026,6,19), h)   # Juneteenth
    self.assertIn(date(2026,11,11), h)  # Veterans Day

def test_jan1_on_saturday_observed_previous_dec31(self):
    self.assertIn(date(2021,12,31), us_federal_holidays(2021))

def test_ack_skips_thanksgiving(self):
    # received Mon Nov 16 2026: business days Nov 17..Dec 1 skipping Thu Nov 26
    self.assertEqual(acknowledge_by(date(2026,11,16)), date(2026,12,1))

def test_days_left(self):
    self.assertEqual(days_left(date(2026,10,26), date(2026,11,6)), 34)
    self.assertEqual(days_left(date(2026,10,26), date(2026,12,12)), -2)

def test_subtract_business_days(self):
    self.assertEqual(subtract_business_days(date(2026,11,9), 3), date(2026,11,4))
```

- [ ] **Step 2: Run the tests and confirm they fail.** Run `bench --site <test-site> run-tests --app crm --module crm.tests.test_privacy_deadlines`.
- [ ] **Step 3: Implement** with pure `datetime`, no DB access.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: add CCPA deadline arithmetic with US federal holidays`.

---

### Task 3: Identifier normalization, scrambling, do-not-contact

**Files:**
- Create: `crm/privacy/identifiers.py`, `crm/fcrm/doctype/crm_do_not_contact/*`
- Test: `crm/tests/test_privacy_identifiers.py`

**Interfaces:**
- Consumes: `crm.utils.normalize_phone`, `crm.privacy.settings()`.
- Produces:
  - `normalize_email(v: str) -> str` (strip and lowercase; `""` for empty)
  - `normalize(kind: str, v: str) -> str` (kind is `"Email"` or `"Phone"`)
  - `scramble(kind: str, v: str) -> str` (HMAC-SHA256 hex of `f"{kind}:{normalize(kind, v)}"`, keyed with `hash_secret`)
  - `add_do_not_contact(kind: str, v: str) -> None` (idempotent)
  - `is_do_not_contact(kind: str, v: str) -> bool`
  - `extract_emails(header: str) -> list[str]` (parse a recipients string with `email.utils.getaddresses`)

- [ ] **Step 1: Write the failing tests**

```python
def test_email_case_insensitive(self):
    add_do_not_contact("Email", " Marisol.Vega@Example.net ")
    self.assertTrue(is_do_not_contact("Email", "marisol.vega@example.net"))

def test_phone_formats(self):
    add_do_not_contact("Phone", "(916) 555-0100")
    for v in ["916.555.0100", "+19165550100", "+1 916 555 0100"]:
        self.assertTrue(is_do_not_contact("Phone", v), v)

def test_stores_no_plaintext(self):
    add_do_not_contact("Email", "a@b.com")
    self.assertFalse(frappe.db.exists("CRM Do Not Contact", {"value_hash": ["like", "%a@b.com%"]}))
    self.assertEqual(len(frappe.db.get_value("CRM Do Not Contact", {"kind": "Email"}, "value_hash")), 64)

def test_idempotent(self):
    add_do_not_contact("Email", "a@b.com"); add_do_not_contact("Email", "A@B.com")
    self.assertEqual(frappe.db.count("CRM Do Not Contact", {"kind": "Email"}), 1)

def test_extract_emails(self):
    self.assertEqual(extract_emails('"Marisol Vega" <Marisol.Vega@x.net>, bob@x.net'),
                     ["marisol.vega@x.net", "bob@x.net"])
```

Phone tests assume the default region is US. Set `frappe.db.set_single_value("FCRM Settings", ...)` per `get_default_region` if needed.

- [ ] **Step 2: Run the tests and confirm they fail.** Run `bench --site <test-site> run-tests --app crm --module crm.tests.test_privacy_identifiers`.
- [ ] **Step 3: Create the doctype and implement the functions.** The doctype has no read permission for anyone except System Manager; access goes through these functions with `ignore_permissions`.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: add hashed do-not-contact list`.

---

### Task 4: Erasure request doctype: fields, state rules, visibility

**Files:**
- Create: `crm/fcrm/doctype/crm_erasure_request/*` and the three child doctypes from the File Map.
- Modify: `crm/hooks.py` (`has_permission`, `permission_query_conditions`).
- Test: `crm/fcrm/doctype/crm_erasure_request/test_crm_erasure_request.py`

**Fields on `CRM Erasure Request`:**
- `request_type` (Select `Erasure`, default, read only)
- `channel` (Select, the Global Constraints channels, reqd)
- `received_on` (Date, reqd, default Today)
- `logged_by` (Link User, read only, set on insert to session user)
- `status` (Select, the Global Constraints statuses, default `Logged`, read only)
- `requester_names` (Small Text)
- `original_message` (Long Text)
- `identifiers` (Table)
- `matches` (Table)
- `checklist` (Table)
- `contract_references` (Small Text, one per line)
- `acknowledgment_sent` (Check), `acknowledged_on` (Date)
- `acknowledge_by`, `respond_by` (Date, read only, computed in `validate` from Task 2)
- `approved_by` (Link User), `approved_on` (Datetime), `erased_on` (Datetime), `erasure_error` (Small Text). All read only.
- `answered_on` (Date), `outcome` (Select with blank + outcomes), `denial_reason` (Small Text)
- `ack_reminder_sent`, `day30_reminder_sent`, `day40_alert_sent` (Check, hidden)
- `delete_after` (Date, read only)

**DocPerms:**
- Compliance and Sales Manager: read/write/create.
- Sales User: read/write/create.
- The hook below narrows access.

**Interfaces:**
- Produces:
  - `CRMErasureRequest.can_approve(user: str) -> bool`
  - `crm.fcrm.doctype.crm_erasure_request.crm_erasure_request.has_permission(doc, ptype, user) -> bool`
  - `crm.fcrm.doctype.crm_erasure_request.crm_erasure_request.get_permission_query_conditions(user) -> str`
  - `FULL_ACCESS_ROLES = {"Compliance", "Sales Manager"}`

**Rules enforced in `validate`:**
- `status → Closed` requires: `answered_on`, `outcome`, `denial_reason` if outcome is `Denied`, and no checklist row with `done = 0`.
- `status → Declined` requires `denial_reason`.
- Ticking a checklist row stamps `done_by` = session user and `done_on` = now. Only `Compliance` may change checklist rows.
- `has_permission`:
  - True for users with a role in `FULL_ACCESS_ROLES`.
  - True for `logged_by == user` while status is `Logged`.
  - Otherwise False.
- The query condition mirrors `has_permission` in SQL.

- [ ] **Step 1: Write the failing tests**

```python
def test_dates_computed(self):
    r = make_request(received_on="2026-10-26")
    self.assertEqual(str(r.acknowledge_by), "2026-11-09"); self.assertEqual(str(r.respond_by), "2026-12-10")

def test_cannot_close_with_open_checklist(self):
    r = make_request(status="Erased", checklist=[{"description": "Delete recordings at provider (Twilio)"}])
    r.update({"status": "Closed", "answered_on": today(), "outcome": "Completed"})
    self.assertRaises(frappe.ValidationError, r.save)

def test_denied_needs_reason(self): ...  # status Closed, outcome Denied, no reason → ValidationError

def test_logger_cannot_approve_even_if_compliance(self):
    r = make_request(logged_by="comp1@example.com")
    self.assertFalse(r.can_approve("comp1@example.com"))
    self.assertTrue(r.can_approve("comp2@example.com"))
    self.assertFalse(r.can_approve("salesmanager@example.com"))

def test_visibility(self):
    r = make_request(logged_by="rep@example.com")
    self.assertTrue(has_permission(r, "read", "rep@example.com"))
    r.db_set("status", "Awaiting Sign-off")
    self.assertFalse(has_permission(r, "read", "rep@example.com"))
    self.assertTrue(has_permission(r, "read", "salesmanager@example.com"))
    self.assertFalse(has_permission(r, "read", "otherrep@example.com"))

def test_checklist_tick_stamps_user(self): ...
```

Create the test users with `frappe.get_doc({"doctype": "User", ...}).insert()` and roles: `comp1`/`comp2` (Sales User + Compliance), `salesmanager` (Sales Manager), `rep`/`otherrep` (Sales User).

- [ ] **Step 2: Run the tests and confirm they fail.** Run `bench --site <test-site> run-tests --app crm --doctype "CRM Erasure Request"`.
- [ ] **Step 3: Create the doctypes and implement the class and hooks.** Register them in `hooks.py`: `has_permission["CRM Erasure Request"]` and `permission_query_conditions["CRM Erasure Request"]`.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: add erasure request doctype with state and visibility rules`.

---

### Task 5: Matching, identifier counts, On Hold

**Files:**
- Create: `crm/privacy/matching.py`
- Modify: `crm/hooks.py` (`doc_events["CRM Deal"]["on_update"]` append)
- Test: `crm/tests/test_privacy_matching.py`

**Interfaces:**
- Consumes: `normalize`, `extract_emails` (Task 3), `notify` (Task 1).
- Produces:
  - `suggest_matches(request: CRMErasureRequest) -> None`. It appends unconfirmed `matches` rows:
    - Leads, contacts and deals whose personal-field email or phone equals a non-excluded identifier (`source = Identifier match`).
    - Deals with `lead =` a confirmed lead, and deals with a confirmed contact in `contacts` (`source = Linked record`).
    - It never duplicates existing rows.
  - `refresh_identifiers(request) -> None`. It adds identifiers found on confirmed leads and contacts (lead `email`/`mobile_no`/`phone`; Contact Email and Contact Phone rows) and recomputes `match_count`. The count is the number of leads, contacts, deals, Communications and call logs containing it.
  - `confirmed(request, doctype: str) -> list[str]`
  - `active_identifiers(request, kind: str) -> list[str]` (normalized, non-excluded)
  - `open_deals_with_person(request) -> list[str]`. These are deals whose status type is in (`Open`, `Ongoing`, `On Hold`) and whose `contacts` include a confirmed contact.
  - `submit_request(request_name: str) -> str`. Called from the API. It requires at least one confirmed match and sets status `On Hold` or `Awaiting Sign-off`. Returns the new status.
  - `on_deal_update(doc, method) -> None`. If any request in status `On Hold` includes this deal, re-check; when `open_deals_with_person` is empty, set `Awaiting Sign-off`. If she was removed from a deal, mark that match row `removed_from_open_deal = 1`.
  - On entering On Hold, notify each open deal's `deal_owner`. Subject: `Remove {contact} from {deal} or close it — erasure request {name}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_suggests_by_email_and_linked_deals(self):
    lead, contact, deal = make_person("marisol@x.net", "+19165550100")  # deal.lead=lead, contact in deal.contacts
    r = make_request(identifiers=[{"kind": "Email", "value": "Marisol@X.net"}])
    suggest_matches(r)
    found = {(m.reference_doctype, m.reference_name) for m in r.matches}
    self.assertIn(("CRM Lead", lead.name), found); self.assertIn(("Contact", contact.name), found)
    self.assertIn(("CRM Deal", deal.name), found)

def test_excluded_identifier_not_used(self): ...  # shared office line excluded → its lead not suggested

def test_refresh_identifiers_adds_contact_phone_and_counts(self): ...  # match_count ≥ 1

def test_open_deal_puts_request_on_hold_and_notifies_owner(self):
    status = submit_request(r.name)
    self.assertEqual(status, "On Hold")
    self.assertTrue(frappe.db.exists("CRM Notification", {"to_user": deal.deal_owner, "type": "Privacy"}))

def test_removing_her_from_deal_releases_hold(self):
    deal.contacts = [row for row in deal.contacts if row.contact != contact.name]; deal.save()
    self.assertEqual(frappe.db.get_value("CRM Erasure Request", r.name, "status"), "Awaiting Sign-off")

def test_closing_deal_lost_releases_hold(self): ...
```

- [ ] **Step 2: Run the tests and confirm they fail.** Run `bench --site <test-site> run-tests --app crm --module crm.tests.test_privacy_matching`.
- [ ] **Step 3: Implement.** Email matching against leads, deals and contacts uses `LOWER(field) = value`. Phone matching compares `normalize_phone(field)` in Python over candidates pre-filtered by `phone_search_digits` with `LIKE '%digits%'`.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: match erasure requests to records and hold on open deals`.

---

### Task 6: Approval preview

**Files:** Create `crm/privacy/preview.py`. Test `crm/tests/test_privacy_preview.py`.

**Interfaces:**
- Consumes: Task 5 helpers, `personal_fields`.
- Produces: `get_erasure_preview(request_name: str) -> dict` (§5.6 "approval screen") with this shape:

```python
{
  "remove": [{"kind": "Lead"|"Deal"|"Contact"|"Address"|"Email"|"Call"|"Note"|"Task"|"Comment"|"File"|"WhatsApp", "doctype": str, "name": str, "label": str}],
  "counts": {kind: int},
  "keep": [{"label": str, "reason": str}],  # organization(s); deal values/status; anonymized lead/deal shells;
                                            # placeholders; notes/tasks/comments/files of deals with removed_from_open_deal=1;
                                            # retained-contract entry if contract_references set
  "open_checklist": [str],
  "unlisted_custom_fields": [{"doctype": str, "fieldname": str, "label": str}],  # Custom Field rows on CRM Lead/CRM Deal/Contact
                                                                                  # of type Data/Small Text/Text/Phone/Attach Image not in personal_fields
  "recordings_present": bool,
}
```

`collect_targets(request) -> Targets` is shared with Task 7/8 so the preview and the executor can never disagree. It's a dataclass with one list of names per kind.
- "Deals she is still on" = confirmed deals where `removed_from_open_deal = 0`.
- The content sweep for emails and calls also includes any Communication or Call Log matching an active identifier anywhere.

- [ ] **Step 1: Write the failing tests**

```python
def test_preview_lists_lead_deal_contact_emails(self): ...   # counts["Email"] == 3 for 3 linked/matching emails
def test_removed_from_open_deal_notes_are_kept(self): ...    # note on that deal appears in keep, not remove
def test_still_on_deal_notes_removed(self): ...
def test_unlisted_custom_field_flagged(self):
    create_custom_field("CRM Lead", {"fieldname": "personal_mobile", "fieldtype": "Data", "label": "Personal mobile"})
    self.assertIn("personal_mobile", [f["fieldname"] for f in get_erasure_preview(r.name)["unlisted_custom_fields"]])
def test_recordings_present(self): ...
```

- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement** `collect_targets` and `get_erasure_preview`.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: build erasure preview from shared target collection`.

---

### Task 7: Erase records: lead, contact, address, deal, change history, deleted copies

**Files:** Create `crm/privacy/erasure.py` (record part). Test `crm/tests/test_privacy_erasure_records.py`.

**Interfaces:**
- Consumes: `collect_targets` (Task 6), `personal_fields`.
- Produces:
  - `erase_records(request: CRMErasureRequest, targets: Targets) -> None`
  - `scrub_version_data(data: dict, fields: set[str], placeholder: str) -> dict` (pure)
  - `placeholder_person(request_name) -> str`
  - `placeholder_content(request_name) -> str`
  - `erase_person_values(request) -> set[str]`. These are her normalized emails and phones plus the name strings from confirmed records and `requester_names`. Task 8 uses them for text replacement.

**Behaviour (§5.6):**
- **Lead:**
  - Each personal field is blanked (`""`; `None` for Link/Attach Image).
  - `first_name` and `lead_name` become the person placeholder.
  - The image File is deleted (Task 8 handles the physical file).
- **Contact:**
  - Same blanking, with `first_name`/`full_name` as the placeholder.
  - `frappe.db.delete("Contact Email", {"parent": name})` and the same for `Contact Phone`.
- **Address** (Dynamic Link `link_doctype = Contact` to a confirmed contact): each listed field is blanked, and `address_title` becomes the placeholder.
- **Deal she is still on:**
  - Her `CRM Contacts` row: `full_name` becomes the placeholder; email, mobile and phone are blanked. The `contact` link is kept.
  - The deal's own personal fields are blanked **only where the current value equals one of her values** (normalized compare).
- **Version** rows with `ref_doctype`/`docname` in the erased leads, contacts and deals: apply `scrub_version_data` with that doctype's personal fields plus the `CRM Contacts` fields for `row_changed`/`added`/`removed` rows of table `contacts`.
- **Deleted Document** rows whose `deleted_doctype` is in (CRM Lead, Contact, CRM Deal, Communication, FCRM Note, CRM Call Log, Address) and whose `data` contains any of her emails or normalized phones (`LIKE`): delete them with `frappe.db.delete`.

- [ ] **Step 1: Write the failing tests**

```python
def test_dashboard_numbers_unchanged(self):
    before = snapshot_dashboard()   # dict of get_total_leads/get_ongoing_deals/get_won_deals/get_forecasted_revenue/get_funnel_conversion/... for a wide date range, as Administrator
    erase_records(r, collect_targets(r))
    self.assertEqual(before, snapshot_dashboard())

def test_lead_blanked_with_placeholder(self):
    lead = frappe.get_doc("CRM Lead", lead_name)
    self.assertEqual(lead.first_name, f"Erased person {r.name}"); self.assertFalse(lead.email or lead.mobile_no or lead.linkedin)
    self.assertEqual(lead.status, original_status)

def test_non_primary_contact_on_deal_primary_untouched(self):
    # deal: primary = Bob (bob@x.net), Marisol non-primary
    deal = frappe.get_doc("CRM Deal", deal_name)
    self.assertEqual(deal.email, "bob@x.net")
    self.assertEqual([c.full_name for c in deal.contacts if c.contact == contact_name], [f"Erased person {r.name}"])

def test_no_version_holds_email(self):
    self.assertFalse(frappe.db.exists("Version", {"data": ["like", "%marisol@x.net%"]}))

def test_no_new_version_rows_created(self):
    n = frappe.db.count("Version"); erase_records(r, collect_targets(r)); self.assertLessEqual(frappe.db.count("Version"), n)

def test_deleted_document_copies_removed(self): ...

def test_scrub_version_data_pure(self):
    data = {"changed": [["email", "m@x.net", "n@x.net"], ["status", "New", "Contacted"]]}
    out = scrub_version_data(data, {"email"}, "Erased person PDR-0001")
    self.assertEqual(out["changed"], [["email", "Erased person PDR-0001", "Erased person PDR-0001"], ["status", "New", "Contacted"]])
```

- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: erase personal fields on records, history and deleted copies`.

---

### Task 8: Erase content and run the job

**Files:**
- Modify: `crm/privacy/erasure.py` (content part and job)
- Test: `crm/tests/test_privacy_erasure_content.py`

**Interfaces:**
- Consumes: Tasks 3, 6 and 7.
- Produces:
  - `erase_content(request, targets) -> None`
  - `erase_communications(names: list[str], request_name: str, person_values: set[str]) -> None` (the Communication rule below; Task 9's `close` reuses it)
  - `run_erasure(request_name: str) -> None` (the enqueued job)
  - `CHECKLIST_TWILIO = "Delete recordings at provider (Twilio)"`

**Behaviour (§5.6, §5.7, §5.9, §5.11):**
- **Communication:**
  - `subject` and `content` become the content placeholder.
  - In `sender`, `recipients`, `cc` and `bcc`, each address in her emails is replaced by the person placeholder. Other addresses are left intact (use `extract_emails` and rebuild the comma-joined list).
  - `sender_full_name` becomes the person placeholder if `sender` was hers.
  - Communication rows are never deleted.
- **CRM Call Log:**
  - `from`/`to` holding her phone become the person placeholder. `recording_url` is cleared.
  - The linked `note` is treated as an FCRM Note.
  - If any target call had a non-empty `recording_url`, append the checklist row `CHECKLIST_TWILIO` (`auto_added = 1`).
- **FCRM Note:** `title` and `content` become the content placeholder. **CRM Task:** `title` and `description` do too; status, dates and assignee are kept. **Comment** (`reference_doctype`/`reference_name` on targets): `content` does too.
- **Files:**
  - Delete the `File` docs attached to target leads, contacts, still-on deals and target Communications, plus the lead/contact `image` files.
  - Delete with `delete_permanently=True`. Physical removal goes through `frappe.db.after_commit`.
  - Where a file was listed on a Communication, its content placeholder stands in for it.
- **Other places:**
  - `CRM Notification`: `message` and `notification_text` on target references, or containing her values, have her values replaced by the person placeholder.
  - `Email Queue` rows whose recipients include her email are deleted.
  - `WA Message` on target references: `message` becomes the content placeholder. A `WA Profile` matching her phone is deleted.
  - `Event Participants` with her email: email becomes the placeholder.
  - `Failed Lead Sync Log`: `lead_data` containing her values becomes the content placeholder.
  - `CRM Enrichment Run Change` with `old_value`/`new_value` containing her values: the value becomes the person placeholder.
- **Search:** `CRMSearch().index_doc(doctype, name)` for every changed lead, deal, contact, note, task and Communication. Run it after commit.
- **`run_erasure`:**
  1. Load the request. Require status `Erasing`.
  2. `targets = collect_targets(request)`, then `erase_records`, then `erase_content`.
  3. `add_do_not_contact` for each active identifier.
  4. Create a `CRM Retained Contract` per line of `contract_references`. `person_name` is the first line of `requester_names`; `delete_after` = today + `contract_retention_months` months, or blank when 0.
  5. Set status `Erased` and `erased_on`, then commit.
  6. On any exception: `frappe.db.rollback()`, set status `Awaiting Sign-off` and `erasure_error = str(e)`, commit, then re-raise for the job log.

- [ ] **Step 1: Write the failing tests**

```python
def test_mixed_email_keeps_other_recipient(self):
    c = make_communication(recipients='"Marisol Vega" <Marisol@X.net>, bob@x.net', content="Hi Marisol, call me at 916-555-0100")
    run(r)
    c.reload()
    self.assertEqual(c.content, f"Content erased {r.name}")
    self.assertIn("bob@x.net", c.recipients); self.assertIn(f"Erased person {r.name}", c.recipients)
    self.assertNotIn("marisol", c.recipients.lower())

def test_email_on_unrelated_deal_matching_address_wiped(self): ...
def test_call_with_recording_adds_twilio_item(self): ...
def test_note_on_removed_from_open_deal_untouched(self): ...
def test_files_deleted(self): ...
def test_do_not_contact_created(self): self.assertTrue(is_do_not_contact("Phone", "916.555.0100"))
def test_retained_contract_created(self): ...
def test_failure_rolls_back_and_returns_to_awaiting(self):
    with patch("crm.privacy.erasure.erase_content", side_effect=Exception("boom")):
        self.assertRaises(Exception, run_erasure, r.name)
    self.assertEqual(frappe.db.get_value("CRM Erasure Request", r.name, ["status", "erasure_error"]), ("Awaiting Sign-off", "boom"))
    self.assertEqual(frappe.db.get_value("CRM Lead", lead_name, "email"), "marisol@x.net")
```

- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: erase emails, calls, notes and files and run erasure as one job`.

---

### Task 9: API: log, submit, approve, decline, close

**Files:** Create `crm/api/erasure.py`. Test `crm/tests/test_privacy_api.py`.

**Interfaces (all `@frappe.whitelist()`):**
- `create_request(channel: str, received_on: str, requester_names: str = "", original_message: str = "", identifiers: list[dict] | None = None, start_doctype: str | None = None, start_name: str | None = None) -> str`.
  - If a start record is given, it prefills identifiers from it and adds a confirmed match with `source = Started from`.
  - Then it calls `refresh_identifiers` and `suggest_matches`. Returns the name.
- `get_request(name: str) -> dict`. Returns the full doc plus `days_left` and `day_number` for full-access users and for the logger while `Logged`. For the logger after submit it returns only `{name, status, received_on, acknowledge_by, respond_by, days_left}`. Otherwise PermissionError.
- `list_requests(include_closed: int = 0) -> list[dict]`. Returns open requests sorted by `respond_by` ascending: full rows for full-access users, and the restricted shape for the logger's own submitted ones.
- `update_matches(name: str, matches: list[dict], identifiers: list[dict]) -> None`. Allowed for the logger while `Logged`, or for Compliance before approval. Re-runs `refresh_identifiers`.
- `submit(name: str) -> str` delegates to `submit_request`.
- `preview(name: str) -> dict`. Compliance only; delegates to `get_erasure_preview`.
- `approve(name: str, typed_name: str) -> None`.
  - Requires `typed_name == name`, `can_approve(session user)` and status `Awaiting Sign-off`.
  - Re-checks `open_deals_with_person`; if any are open, sets status `On Hold` and throws.
  - Atomically sets `Erasing`, `approved_by` and `approved_on` with `UPDATE ... WHERE status='Awaiting Sign-off'`. If the update affected 0 rows, throws "already approved".
  - Then runs `frappe.enqueue("crm.privacy.erasure.run_erasure", request_name=name, queue="long", enqueue_after_commit=True)`.
- `decline(name: str, reason: str) -> None`. Compliance only, not the logger. Requires a reason. Status becomes `Declined`.
- `close(name: str, answered_on: str, outcome: str, denial_reason: str = "") -> None`. Compliance only; status must be `Erased` or `Declined`. Then:
  - Validates as in Task 4.
  - Calls `erase_communications` on Communications linked to this request (the inbound emails from §5.9).
  - Wipes `requester_names`, `original_message`, `identifiers`, `matches`, the checklist `description`s and `contract_references`. Checklist rows are kept with descriptions wiped.
  - Sets status `Closed` and `delete_after = answered_on + 24 months`.
  - Saves with `ignore_version=True`, then deletes Version rows for this request.

- [ ] **Step 1: Write the failing tests**

```python
def test_approve_requires_typed_number(self): ...        # wrong text → ValidationError
def test_logger_cannot_approve(self): ...                # PermissionError
def test_sales_manager_cannot_approve(self): ...
def test_double_approve_second_fails(self):
    approve(r.name, r.name)
    self.assertRaises(frappe.ValidationError, approve, r.name, r.name)
def test_logger_sees_restricted_after_submit(self):
    self.assertEqual(set(get_request(r.name)), {"name", "status", "received_on", "acknowledge_by", "respond_by", "days_left"})
def test_close_wipes_identifying_details(self):
    close(r.name, today(), "Completed")
    d = frappe.get_doc("CRM Erasure Request", r.name)
    self.assertFalse(d.requester_names or d.original_message or d.identifiers or d.matches)
    self.assertEqual(d.request_type, "Erasure"); self.assertTrue(d.received_on and d.channel and d.answered_on)
    self.assertFalse(frappe.db.exists("Version", {"ref_doctype": "CRM Erasure Request", "docname": r.name}))
def test_list_sorted_by_days_left(self): ...
```

- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: add erasure request API with guarded approval and close`.

---

### Task 10: Blocking and inbound email

**Files:**
- Create: `crm/privacy/blocking.py`, `crm/privacy/inbound.py`
- Modify: `crm/hooks.py` (`doc_events` validate for `CRM Lead`, `CRM Deal`, `Contact`; Communication `after_insert` prepend), `crm/utils/__init__.py`
- Test: `crm/tests/test_privacy_blocking.py`

**Interfaces:**
- Produces:
  - `crm.privacy.blocking.validate(doc, method) -> None`. Throws `frappe.ValidationError` with the message `This person asked to be erased under a privacy request. Their details can't be added to the CRM.`:
    - for a new document (`doc.is_new()`) where any email or phone field is on the do-not-contact list;
    - for an existing document where such a field changed (`doc.has_value_changed(f)`) to a blocked value.
  - Fields checked:
    - Lead: `email`, `mobile_no`, `phone`.
    - Deal: each `contacts` row's `email`, `mobile_no` and `phone`, for new rows or changed values.
    - Contact: `email_ids[].email_id`, `phone_nos[].phone`, `email_id`, `mobile_no` and `phone`.
  - `crm.privacy.inbound.is_erased_sender(email: str) -> bool`. True if the address is on the do-not-contact list or is an active identifier of a non-closed request.
  - `crm.privacy.inbound.on_communication_insert(doc, method) -> None`. For a received Communication whose sender is an active identifier of a non-closed request: set `reference_doctype/name` to that request via `db_set`. If instead it's on the do-not-contact list: leave it unlinked and `notify(compliance_users(), "Email received from an erased person", ...)`. The notification message contains no address; it links the Communication.
  - In `create_lead_from_incoming_email`: `if is_erased_sender(doc.sender): return` before creating a lead.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_lead_blocked(self):
    add_do_not_contact("Email", "marisol@x.net")
    with self.assertRaisesRegex(frappe.ValidationError, "asked to be erased"):
        frappe.get_doc({"doctype": "CRM Lead", "first_name": "M", "email": "MARISOL@x.net"}).insert()

def test_phone_format_blocked(self): ...   # mobile_no "(916) 555-0100" vs stored +19165550100
def test_existing_record_saves_if_unchanged(self): ...  # lead already holding value, edit other field → saves
def test_deal_contact_row_blocked(self): ...
def test_facebook_sync_path_blocked(self): ...  # call the lead_syncing insert helper; lead not created
def test_inbound_email_open_request_attached(self): ...
def test_inbound_email_after_close_notifies_compliance_no_lead(self):
    self.assertFalse(frappe.db.exists("CRM Lead", {"email": "marisol@x.net"}))
```

- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.** Register `crm.privacy.blocking.validate` first in each validate list. Add `crm.privacy.inbound.on_communication_insert` before `crm.utils.on_communication_insert`.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: block erased people from re-entry and route their inbound email`.

---

### Task 11: Reminders, retention, outcome email template

**Files:**
- Create: `crm/privacy/reminders.py`, `crm/privacy/retention.py`
- Modify: `crm/hooks.py` (`scheduler_events["daily"]`), `crm/privacy/setup.py` (template)
- Test: `crm/tests/test_privacy_reminders.py`

**Interfaces:**
- Produces:
  - `send_due_reminders(today: date | None = None) -> None` (daily)
  - `purge_expired(today: date | None = None) -> None` (daily)
  - Email Template `Erasure outcome`, created by `ensure_privacy_setup`

**Reminder rules:** see Global Constraints.
- Use the `*_sent` flags so each reminder fires once.
- If `head_of_compliance` is unset, the day-40 alert goes to all Compliance users, so it's never silently dropped. Add test `test_day40_falls_back_to_compliance_when_no_head`.
- Message: `{name}: {days_left} of 45 days left — respond by {respond_by}`. The acknowledgment version says `acknowledge by {acknowledge_by}`.
- Messages contain no requester name, email or phone.

**Purge rules:**
- Delete `CRM Erasure Request` where status is `Closed` and `delete_after <= today`.
- Delete `CRM Retained Contract` where `delete_after <= today`.
- Both use `delete_permanently=True`.

**Template body.** These are the sections §5.10 requires, with `[...]` placeholders for Compliance to fill:
- What we erased: `[categories]`, including at external providers: `[yes/no + providers]`.
- What we kept and why: `[items and reasons]`.
- That we keep a record of this request (date received, type, how it arrived, date answered, outcome) for 24 months, and a scrambled form of your email address and phone number so your details are not added again.
- Known limitation: passing mentions of you inside records about other people, such as a note on a deal, are not searched for or erased.

- [ ] **Step 1: Write the failing tests**

```python
def test_late_logged_request_sends_each_reminder_once(self):
    r = make_request(received_on=add_days(today(), -41))
    send_due_reminders(); send_due_reminders()
    self.assertEqual(frappe.db.count("CRM Notification", {"type": "Privacy", "to_user": "head@example.com"}), 1)
    self.assertEqual(frappe.db.count("CRM Notification", {"type": "Privacy", "to_user": "comp1@example.com"}), 2)  # ack + day 30

def test_ack_reminder_three_business_days_before(self):
    r = make_request(received_on="2026-10-26")
    send_due_reminders(date(2026, 11, 3)); self.assertFalse(r.reload() or r.ack_reminder_sent)
    send_due_reminders(date(2026, 11, 4)); r.reload(); self.assertTrue(r.ack_reminder_sent)

def test_ack_ticked_suppresses_reminder(self): ...
def test_closed_request_gets_no_reminders(self): ...
def test_purge_after_24_months(self): ...
def test_template_exists(self): self.assertTrue(frappe.db.exists("Email Template", "Erasure outcome"))
```

- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement** and register both functions in `scheduler_events["daily"]`.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Commit** with `feat: add erasure reminders, retention purge and outcome template`.

---

### Task 12: Frontend helpers (pure, unit-tested)

**Files:** Create `frontend/src/utils/erasureRequest.js`. Test `frontend/tests/unit/erasureRequest.test.js`.

**Interfaces:**
- Produces:
  - `daysLeftLabel(daysLeft: number) -> string`: `"33 of 45 days left"`, `"Due today"`, `"2 days overdue"`.
  - `urgencyTheme(daysLeft: number) -> 'red'|'orange'|'gray'`: red ≤ 5, orange ≤ 15, else gray.
  - `statusTheme(status: string) -> string` (badge theme per status).
  - `canApprove(request, sessionUser: string, isCompliance: boolean) -> boolean` (UI hint only; the server is authoritative).
  - `confirmMatches(typed: string, requestName: string) -> boolean` (exact, trimmed).

- [ ] **Step 1: Write the failing tests**

```js
expect(daysLeftLabel(33)).toBe('33 of 45 days left')
expect(daysLeftLabel(0)).toBe('Due today')
expect(daysLeftLabel(-2)).toBe('2 days overdue')
expect(urgencyTheme(5)).toBe('red')
expect(canApprove({ logged_by: 'a@x', status: 'Awaiting Sign-off' }, 'a@x', true)).toBe(false)
expect(canApprove({ logged_by: 'a@x', status: 'Awaiting Sign-off' }, 'b@x', true)).toBe(true)
expect(canApprove({ logged_by: 'a@x', status: 'On Hold' }, 'b@x', true)).toBe(false)
expect(confirmMatches(' PDR-0001 ', 'PDR-0001')).toBe(true)
expect(confirmMatches('pdr-0001', 'PDR-0001')).toBe(false)
```

- [ ] **Step 2: Run the tests and confirm they fail.** Run `cd frontend && yarn test:run tests/unit/erasureRequest.test.js`.
- [ ] **Step 3: Implement.** Wrap the labels in `__()`.
- [ ] **Step 4: Run the tests and confirm they pass.** Run `yarn test:run`; all tests pass.
- [ ] **Step 5: Commit** with `feat: add erasure request UI helpers`.

---

### Task 13: Requests list, detail page and approval modal

**Files:**
- Create: `frontend/src/pages/ErasureRequests.vue`, `ErasureRequest.vue`, `components/Modals/ApproveErasureModal.vue`
- Modify: `router.js`, `AppSidebar.vue`, the session store (add `is_compliance`)

**Interfaces:**
- Consumes: Task 9 endpoints via `createResource` (`crm.api.erasure.*`), and the Task 12 helpers.
- Produces:
  - Routes `/privacy-requests` (name `ErasureRequests`) and `/privacy-requests/:requestId` (name `ErasureRequest`).
  - A sidebar item "Privacy requests", shown when `is_compliance || is_sales_manager`.

**Screens:**
- **List:** columns are Request, Status, Received, Acknowledge by (with ✓ when sent), Respond by, and days left as a badge using `urgencyTheme`. Sorted by days left. There's a "Log request" button (opens Task 14's modal blank) and a "Show closed" toggle.
- **Detail header:** the request number, a status badge, `daysLeftLabel`, the two due dates, and the acknowledgment checkbox (Compliance only).
- **Detail sections:**
  - Identifiers: excluded toggle and match count.
  - Matched records: confirm toggle and link. Editable by the logger while `Logged`, and by Compliance until approval.
  - Checklist: tick, plus add item (Compliance).
  - Contract references (Compliance).
  - Requester details and original message.
  - The restricted view shows only the header for the logger after submit.
- **Actions by state:**
  - Submit: logger or Compliance, while `Logged`.
  - Approve (opens the modal) and Decline (reason prompt): Compliance, when `canApprove`.
  - Close (answered on, outcome, denial reason): Compliance, when `Erased` or `Declined`.
  - Show `erasure_error` as an error banner when set. Show an `On Hold` banner listing the open deals.
- **ApproveErasureModal:**
  - Three sections from `preview`: **Will be removed** (counts per kind, expandable links), **Will be kept** (label + reason), and **Open checklist items / unlisted custom fields** (warning style).
  - A text input with the instruction "Type {name} to confirm. This can't be undone."
  - The Approve button is disabled until `confirmMatches` passes.

- [ ] **Step 1: Implement the pages, modal, route, sidebar item and session flag.**
- [ ] **Step 2: Run `cd frontend && yarn test:run` and `yarn build`.** Expected: all tests pass and the build succeeds.
- [ ] **Step 3: Manual check on a dev site:**
  - Log a blank request as a rep. Confirm matches. Submit. The rep now sees only the header.
  - As a different Compliance user, approve by typing the number. The status becomes `Erased`.
  - As the logging Compliance user, Approve is hidden, and calling the API directly is rejected.
- [ ] **Step 4: Commit** with `feat: add privacy request list, detail page and approval modal`.

---

### Task 14: Log-request modal, record actions, privacy settings page

**Files:**
- Create: `frontend/src/components/Modals/LogErasureRequestModal.vue`, `frontend/src/components/Settings/PrivacySettings.vue`
- Modify: `pages/Lead.vue`, `Deal.vue`, `Contact.vue`, `components/Settings/Settings.vue`

**Interfaces:**
- Consumes: `crm.api.erasure.create_request`.
- Produces:
  - `LogErasureRequestModal` props: `startDoctype?: string`, `startName?: string`. On create it routes to `ErasureRequest`.
  - On a deal, the modal first asks which contact is the requester (a select from `doc.contacts`). The start record is that Contact.

**Modal fields:**
- How it arrived (select)
- Date received (default today)
- Requester name(s)
- Emails and phones (repeatable; prefilled from the start record)
- Original message (textarea)

**Record actions:**
- "Request erasure" in the header dropdown/actions and the command palette of Lead, Deal and Contact pages, for every CRM user.

**Settings page:**
- Under System Configuration as "Privacy"; visible to `is_compliance` or System Manager.
- Fields: Head of Compliance (user picker), contract retention period (months), and the personal fields table (document type + field select, populated from `getMeta(doctype).getFields()` for that document type; add/remove rows).

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Run `cd frontend && yarn test:run` and `yarn build`.** Expected: green.
- [ ] **Step 3: Manual check:**
  - From Marisol's lead, "Request erasure" prefills her email and phone and creates `PDR-xxxx` with the lead confirmed.
  - From a deal, picking her contact does the same.
  - The settings page saves a new personal field, and that field no longer shows under "unlisted custom fields" in the approval modal.
- [ ] **Step 4: Commit** with `feat: log erasure requests from records and configure privacy settings`.

---

### Task 15: Final verification

- [ ] **Step 1: Run the full suites.** `bench --site <test-site> run-tests --app crm` passes, and `cd frontend && yarn test:run` passes.
- [ ] **Step 2: Walk through the end-to-end Marisol scenario on a dev site:**
  - Lead, 2 deals (one in Negotiation), a contact, emails with a CC'd colleague, a call with a recording, and a custom field "Personal mobile".
  - Log from the lead: the request goes On Hold, and the deal owner is notified.
  - Remove her from the Negotiation deal: the request is back to Awaiting Sign-off.
  - Approve as Dana-equivalent: the Twilio checklist item appears.
  - Dashboard numbers are unchanged.
  - Re-adding her email to a new lead is blocked.
  - Tick the checklist and close: the request keeps only the log fields.
- [ ] **Step 3: Add a feature doc** `.pi/feats/privacy-requests/guide.md` (a user-facing how-to for reps and Compliance) and a line in `AGENTS.md` Key files for `crm/privacy/`.
- [ ] **Step 4: Commit** with `docs: add privacy requests guide`.
