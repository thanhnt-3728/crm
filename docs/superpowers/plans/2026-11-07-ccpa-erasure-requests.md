# Personal Data Erasure Requests (CCPA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a rep log a CCPA erasure request, let a second person in Compliance approve it, then erase the person everywhere the CRM holds them in one all-or-nothing job. Pipeline and revenue numbers must not change. The CRM also tracks deadlines, reminds people, keeps only the legally required log, and blocks the person from being re-entered.

**Architecture:** A new Frappe module `Privacy` (`crm/privacy/`) holds:
- the request doctype and its child tables, plus a single settings doctype and two small ledgers (do-not-contact, retained contracts);
- pure rule modules (deadlines, normalization, placeholders, history scrubbing);
- service modules for matching, hold, plan, erasure, blocking, inbound mail, lifecycle and reminders;
- one whitelisted API module, `crm/privacy/api.py`.

The erasure job runs inside a DB savepoint and writes only with `frappe.db` / query builder, so it creates no Version or Deleted Document copies of the data it removes. Disk deletions and re-indexing run only after commit. The frontend adds a requests list page, a request detail page, an approval modal with typed confirmation, a "Request erasure" button on Lead, Deal and Contact pages, and a Privacy settings tab.

**Tech Stack:** Frappe (v16 develop) Python, MariaDB, `phonenumbers` (already used through `crm.utils.normalize_phone`), Vue 3 + frappe-ui, vitest.

**Spec:** `docs/superpowers/specs/2026-11-05-ccpa-erasure-requests-design.md`. Section references like "5.6" below point into it.

## Global Constraints

- **Python tests need a bench.** Run them with `bench --site $SITE run-tests --app crm --module <module>`; the site needs `allow_tests` set. Run `bench --site $SITE migrate` after any doctype JSON change. Frontend tests: `cd frontend && yarn test:run` (all must pass, per AGENTS.md).
- **Test conventions:**
  - Pure modules are tested with `frappe.tests.UnitTestCase`.
  - DB tests use `frappe.tests.IntegrationTestCase`, with `tearDown` doing `frappe.set_user("Administrator"); frappe.db.rollback()`.
  - All privacy tests live in `crm/privacy/tests/`.
- **Commits:** one per task, using the prefixes `feat:` / `test:` / `fix:` / `docs:`. Pre-commit runs prettier, eslint and oxlint; if they change a file, re-add it and commit again. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Naming:** requests are named `PDR-.####` (e.g. `PDR-0001`).
- **Placeholders** (exact copy):
  - `Erased person PDR-0001` for names, addresses, numbers and email addresses;
  - `Content erased PDR-0001` for subjects, bodies, notes, tasks and comments;
  - `File erased PDR-0001` for removed files.
- **The legal clock:**
  - Respond by = received + 45 calendar days.
  - Acknowledge by = the 10th US business day after receipt; counting starts the day after receipt.
  - Business days are Mon–Fri excluding US federal holidays, including observed dates.
- **Reminders:**
  - acknowledgment: 3 business days before *acknowledge by*, sent to all Compliance users;
  - day 30: sent to all Compliance users;
  - day 40: sent to the Head of Compliance.
  - Each goes out once per request, as a CRM Notification plus an email, and only while the request is not Closed.
- **Retention:** a closed request's log entry is kept 24 months after *date answered*. A retained-contract entry is kept for erasure date + `contract_retention_months`.
- **Never write the requester's name, email or phone into** notifications, emails, error messages, `frappe.log_error` titles, or exception text produced by this feature. Refer to the request number only. The one exception is the On Hold deal-owner notification (Task 7), which names the contact; the erasure sweep scrubs it.
- **Erasure writes:**
  - Erasure writes go through `frappe.db.set_value(..., update_modified=False)`, `frappe.db.delete`, or `frappe.qb.update`. Never use `doc.save()` (it would write a Version with the old values) or `frappe.delete_doc` without `delete_permanently=True`.
  - Lead and deal rows are never deleted. Status, source, territory, owner, dates, values, products, status-change logs and organization are never touched.
- **Phones:** normalized by `crm.utils.normalize_phone(value, region="US")` through `crm.privacy.identifiers.PHONE_REGION = "US"`, so hashes don't change if System Settings' country does. **Emails:** lowercased and stripped.
- **Permissions:**
  - Only the Compliance role approves, declines, manages the checklist and closes.
  - The approver must not be the logger.
  - Every check runs server-side, by user.
  - Holding Sales Manager or System Manager without Compliance grants none of these.

## Review Focus

1. **An inbound email from an erased or in-request address must still be stored.** Frappe creates leads and contacts during mail ingest, so a validation throw could abort the mail. Expected: the Communication exists, no lead or contact is created for her, and the mail is attached to the open request (or to nothing, with Compliance notified, after close). Tests: Task 13.
2. **One phone typed four ways.** `(530) 555-0142`, `530.555.0142`, `+1 530 555 0142` and `5305550142` must all match, sweep and block as the same number. The same goes for `Marisol@SierraFoothills.example ` vs lowercase. Tests: Tasks 2, 6, 10, 12.
3. **A failure halfway through erasure.** Expected: no data changed, no file removed from disk, the request still *Awaiting Sign-off* with the error shown, and approving again works. Tests: Task 9.
4. **Her name inside record names.** Contact and Address `name`s are built from the person's name (e.g. `Marisol Vega`). Expected: renamed to the placeholder, links kept, and the "renamed from …" comment scrubbed. Tests: Task 9.
5. **A file shared with someone else.** A file whose `file_url` is also referenced by another record's File row must keep its disk content; only her File row goes. Tests: Task 10.

---

## File Structure

```
crm/privacy/
  __init__.py
  deadlines.py        pure: holidays, business days, deadlines            (T1)
  identifiers.py      normalize/hash identifiers, DNC lookups             (T2, T4)
  rules.py            pure: placeholders, text/address/version scrubbing,
                      deal-field rule, default personal fields             (T2, T3)
  install.py          role, settings seed, email template seed            (T4, T14)
  permissions.py      has_permission / query conditions / access level    (T5)
  matching.py         suggestions, identifier sync, identifier usage      (T6)
  hold.py             open-deal check, owner notices, release on save     (T7)
  plan.py             ErasurePlan + preview                               (T8)
  erasure.py          run_erasure orchestrator + record erasure           (T9)
  sweep.py            emails, calls, notes, tasks, comments, files, misc  (T10)
  history.py          Version / Deleted Document scrub, DNC, contracts    (T11)
  blocking.py         ErasedPersonError, validate hook                    (T12)
  inbound.py          Communication routing, inbound lead guard           (T13)
  lifecycle.py        decline, close + wipe, purge                        (T14)
  reminders.py        daily reminders, notify helper                      (T15, T7 uses notify)
  api.py              whitelisted endpoints                               (T6–T9, T14)
  doctype/
    crm_erasure_request/              (+ .json/.py/__init__)              (T5)
    crm_erasure_identifier/           child                               (T5)
    crm_erasure_match/                child                               (T5)
    crm_erasure_checklist_item/       child                               (T5)
    crm_privacy_settings/             single                              (T4)
    crm_personal_field/               child                               (T4)
    crm_do_not_contact/                                                    (T4)
    crm_retained_contract/                                                 (T4)
  tests/
    __init__.py, factories.py, test_*.py
frontend/src/
  utils/erasureRequest.js                                                  (T16)
  pages/ErasureRequests.vue, pages/ErasureRequest.vue                      (T16)
  components/Privacy/ApproveErasureModal.vue                               (T17)
  components/Privacy/RequestErasureButton.vue                              (T17)
  components/Settings/PrivacySettings.vue                                  (T17)
frontend/tests/unit/erasureRequest.test.js                                 (T16)
```

Modified: `crm/modules.txt`, `crm/hooks.py`, `crm/install.py`, `crm/utils/__init__.py` (inbound lead path), `crm/api/whatsapp.py`, `crm/lead_syncing/doctype/lead_sync_source/facebook.py`, `crm/fcrm/doctype/crm_notification/crm_notification.json`, `crm/api/notifications.py`, `frontend/src/router.js`, `frontend/src/utils/navigation.js`, `frontend/src/components/Notifications.vue`, `frontend/src/components/Settings/Settings.vue`, and the Lead/Deal/Contact pages (desktop and mobile).

**Spec deviation (flag to reviewer):** 5.1 lists Address among the personal-field doctypes. Because 5.6 blanks *all* Address fields, Address gets no rows in the list; it is erased whole.

---

## Phase A — Pure rules

### Task 1: Deadline math

**Files:**
- Create: `crm/privacy/__init__.py` (empty), `crm/privacy/tests/__init__.py` (empty), `crm/privacy/deadlines.py`
- Modify: `crm/modules.txt` (append line `Privacy`)
- Test: `crm/privacy/tests/test_deadlines.py`

**Interfaces:**
- Produces:
  - `us_federal_holidays(year: int) -> dict[date, str]`: the observed dates falling **in** `year`, including an observed New Year's Day of `year + 1` that falls on Dec 31.
  - `is_business_day(day: date) -> bool`
  - `add_business_days(start: date, n: int) -> date`: `n` may be negative; counting starts the day after (or before) `start`.
  - `acknowledge_by(received: date) -> date`
  - `respond_by(received: date) -> date`
  - `days_left(received: date, today: date) -> int`: may be negative.
  - `reminder_dates(received: date) -> dict[str, date]`, with keys `"acknowledgment"`, `"day_30"`, `"day_40"`.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date

from frappe.tests import UnitTestCase

from crm.privacy.deadlines import (
	acknowledge_by, add_business_days, days_left, is_business_day,
	reminder_dates, respond_by, us_federal_holidays,
)


class TestDeadlines(UnitTestCase):
	def test_spec_example(self):
		self.assertEqual(acknowledge_by(date(2026, 10, 26)), date(2026, 11, 9))
		self.assertEqual(respond_by(date(2026, 10, 26)), date(2026, 12, 10))

	def test_veterans_day_is_skipped(self):
		self.assertEqual(acknowledge_by(date(2026, 11, 5)), date(2026, 11, 20))

	def test_thanksgiving_is_skipped(self):
		self.assertEqual(acknowledge_by(date(2026, 11, 20)), date(2026, 12, 7))

	def test_holidays_2026(self):
		h = us_federal_holidays(2026)
		for d in [date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 5, 25),
				date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 10, 12),
				date(2026, 11, 11), date(2026, 11, 26), date(2026, 12, 25)]:
			self.assertIn(d, h)
		self.assertEqual(len(h), 11)

	def test_saturday_holidays_observed_friday(self):
		self.assertIn(date(2027, 6, 18), us_federal_holidays(2027))   # Juneteenth Sat
		self.assertIn(date(2027, 12, 24), us_federal_holidays(2027))  # Christmas Sat

	def test_new_year_observed_in_previous_year(self):
		self.assertFalse(is_business_day(date(2027, 12, 31)))  # Jan 1 2028 is a Saturday
		self.assertNotIn(date(2027, 12, 31), us_federal_holidays(2028))

	def test_sunday_holiday_observed_monday(self):
		self.assertFalse(is_business_day(date(2027, 7, 5)))  # Jul 4 2027 is a Sunday

	def test_add_business_days_backwards(self):
		self.assertEqual(add_business_days(date(2026, 11, 9), -3), date(2026, 11, 4))

	def test_days_left_and_overdue(self):
		self.assertEqual(days_left(date(2026, 10, 26), date(2026, 10, 26)), 45)
		self.assertEqual(days_left(date(2026, 10, 26), date(2026, 12, 12)), -2)

	def test_reminder_dates(self):
		self.assertEqual(reminder_dates(date(2026, 10, 26)), {
			"acknowledgment": date(2026, 11, 4),
			"day_30": date(2026, 11, 25),
			"day_40": date(2026, 12, 5),
		})
```

- [ ] **Step 2: Run to verify failure**

Run: `bench --site $SITE run-tests --app crm --module crm.privacy.tests.test_deadlines`
Expected: FAIL with `ModuleNotFoundError: crm.privacy.deadlines`.

- [ ] **Step 3: Implement `crm/privacy/deadlines.py`**

Stdlib only, no frappe import. Holidays are computed from their statutory rules:
- New Year's Day: Jan 1
- MLK Day: 3rd Monday of January
- Washington's Birthday: 3rd Monday of February
- Memorial Day: last Monday of May
- Juneteenth: Jun 19, only from 2021 on
- Independence Day: Jul 4
- Labor Day: 1st Monday of September
- Columbus Day: 2nd Monday of October
- Veterans Day: Nov 11
- Thanksgiving: 4th Thursday of November
- Christmas: Dec 25

Observed shift: Saturday → Friday, Sunday → Monday. Keep the rules in one module-level list, so adding a holiday is a one-line change. `is_business_day` must check both `us_federal_holidays(day.year)` and `us_federal_holidays(day.year + 1)`, so it sees the Dec 31 case; cache per year with `functools.lru_cache`. `reminder_dates["acknowledgment"]` is `add_business_days(acknowledge_by(r), -3)`.

- [ ] **Step 4: Run to verify pass** — same command, expected PASS (10 tests).

- [ ] **Step 5: Commit** — `git add crm/privacy crm/modules.txt && git commit -m "feat: add US business-day deadline math for erasure requests"`

---

### Task 2: Identifier normalization, hashing, placeholders, text scrubbing

**Files:**
- Create: `crm/privacy/identifiers.py`, `crm/privacy/rules.py`
- Test: `crm/privacy/tests/test_identifiers.py`, `crm/privacy/tests/test_rules_text.py`

**Interfaces:**
- Produces (`identifiers.py`, pure part):
  - `PHONE_REGION = "US"`
  - `normalize_email(value: str | None) -> str`
  - `normalize_identifier(kind: Literal["Email","Phone"], value: str | None) -> str`: phones go through `crm.utils.normalize_phone(value, region=PHONE_REGION)`.
  - `hash_identifier(kind: str, normalized: str, secret: str) -> str`: hex HMAC-SHA256 of `f"{kind}:{normalized}"`.
- Produces (`rules.py`):
  - `erased_person(request: str) -> str`
  - `erased_content(request: str) -> str`
  - `erased_file(request: str) -> str`
  - `scrub_identifiers(text: str | None, emails: set[str], phones: set[str], placeholder: str) -> str`: `emails` and `phones` are already normalized. Matching emails (case-insensitive) and phone numbers in any format are replaced by `placeholder`. Phones are found with `phonenumbers.PhoneNumberMatcher(text, PHONE_REGION)`.

- [ ] **Step 1: Write the failing tests**

```python
# test_identifiers.py
from frappe.tests import UnitTestCase

from crm.privacy.identifiers import hash_identifier, normalize_email, normalize_identifier


class TestIdentifiers(UnitTestCase):
	def test_email_lowercased_and_trimmed(self):
		self.assertEqual(normalize_email("  Marisol@SierraFoothills.example "), "marisol@sierrafoothills.example")

	def test_phone_formats_normalize_equal(self):
		forms = ["(530) 555-0142", "530.555.0142", "+1 530 555 0142", "5305550142"]
		self.assertEqual({normalize_identifier("Phone", f) for f in forms}, {"+15305550142"})

	def test_empty(self):
		self.assertEqual(normalize_identifier("Email", None), "")
		self.assertEqual(normalize_identifier("Phone", "  "), "")

	def test_hash_is_keyed_and_kind_scoped(self):
		h = hash_identifier("Email", "a@b.example", "s1")
		self.assertEqual(len(h), 64)
		self.assertNotEqual(h, hash_identifier("Email", "a@b.example", "s2"))
		self.assertNotEqual(h, hash_identifier("Phone", "a@b.example", "s1"))
```

```python
# test_rules_text.py
from frappe.tests import UnitTestCase

from crm.privacy.rules import erased_content, erased_file, erased_person, scrub_identifiers


class TestRulesText(UnitTestCase):
	def test_placeholders(self):
		self.assertEqual(erased_person("PDR-0001"), "Erased person PDR-0001")
		self.assertEqual(erased_content("PDR-0001"), "Content erased PDR-0001")
		self.assertEqual(erased_file("PDR-0001"), "File erased PDR-0001")

	def test_scrub_email_and_phone_any_format(self):
		text = "Call Marisol at 530.555.0142 or mail MARISOL@sierrafoothills.example; office 530-555-0100"
		out = scrub_identifiers(text, {"marisol@sierrafoothills.example"}, {"+15305550142"}, "X")
		self.assertEqual(out, "Call Marisol at X or mail X; office 530-555-0100")

	def test_none_text(self):
		self.assertEqual(scrub_identifiers(None, {"a@b.example"}, set(), "X"), "")
```

- [ ] **Step 2: Run to verify failure** — `bench --site $SITE run-tests --app crm --module crm.privacy.tests.test_identifiers` and `... test_rules_text`. Expected: FAIL, import errors.

- [ ] **Step 3: Implement both modules.** `hash_identifier` uses `hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()`. Email scrubbing uses `re.sub(re.escape(email), placeholder, text, flags=re.I)`.

- [ ] **Step 4: Run to verify pass.**

- [ ] **Step 5: Commit** — `feat: add identifier normalization, hashing and placeholder rules`

---

### Task 3: Structured scrubbing rules (deal fields, address headers, Version data)

**Files:**
- Modify: `crm/privacy/rules.py`
- Test: `crm/privacy/tests/test_rules_struct.py`

**Interfaces:**
- Consumes: `normalize_identifier` (Task 2).
- Produces:
  - `DEAL_FIELD_SOURCES: dict[str, tuple[str, ...]]`: maps each deal personal field to the her-value keys it is compared against. Pin these:
    - `first_name`, `last_name`, `salutation`, `gender`, `linkedin`, `twitter`, `facebook` → the same key;
    - `lead_name` → `lead_name`, `full_name`;
    - `job_title` → `job_title`, `designation`.
  - `deal_fields_to_blank(deal: dict, her_values: dict[str, set[str]], emails: set[str], phones: set[str]) -> list[str]`:
    - `email` is blanked when its normalized value is in `emails`;
    - `mobile_no` and `phone` are blanked when their normalized value is in `phones`;
    - every other key in `DEAL_FIELD_SOURCES` is blanked when its stripped, case-folded value is in any of its source sets;
    - empty values are never listed.
  - `replace_addresses(header: str | None, emails: set[str], placeholder: str) -> str`: parses with `email.utils.getaddresses` and replaces each matching address, together with its display name, by `placeholder`. Other addresses are re-joined unchanged as `", "`-separated `formataddr` output.
  - `scrub_version_data(data: dict, should_scrub: Callable[[str, Any], bool], placeholder: str) -> dict`: returns a new dict. For `changed` `[[field, old, new]]`, it replaces `old` / `new` where `should_scrub(field, value)` is true. For `added` / `removed` `[[table, row]]`, it replaces each row key where the predicate is true. For `row_changed` `[[table, idx, rowname, [[field, old, new]]]]`, it does the same as `changed`. Every other key passes through unchanged.

- [ ] **Step 1: Write the failing tests**

```python
from frappe.tests import UnitTestCase

from crm.privacy.rules import deal_fields_to_blank, replace_addresses, scrub_version_data

EMAILS = {"marisol@sierrafoothills.example"}
PHONES = {"+15305550142"}
HER = {"first_name": {"marisol"}, "last_name": {"vega"}, "lead_name": {"marisol vega"}, "full_name": {"marisol vega"}}


class TestRulesStruct(UnitTestCase):
	def test_deal_fields_only_where_hers(self):
		deal = {"email": "Marisol@SierraFoothills.example", "mobile_no": "530 555 0142",
				"phone": "530-555-0100", "first_name": "Marisol", "last_name": "Okafor", "lead_name": "Marisol Vega"}
		self.assertEqual(sorted(deal_fields_to_blank(deal, HER, EMAILS, PHONES)),
				["email", "first_name", "lead_name", "mobile_no"])

	def test_deal_of_someone_else_untouched(self):
		deal = {"email": "dana@x.example", "first_name": "Dana", "mobile_no": ""}
		self.assertEqual(deal_fields_to_blank(deal, HER, EMAILS, PHONES), [])

	def test_replace_addresses(self):
		out = replace_addresses('"Marisol Vega" <Marisol@SierraFoothills.example>, tyler@northpine.example', EMAILS, "P")
		self.assertEqual(out, "P, tyler@northpine.example")

	def test_scrub_version_changed_rows(self):
		data = {"changed": [["email", "marisol@sierrafoothills.example", ""], ["status", "New", "Contacted"]],
				"added": [["email_ids", {"email_id": "marisol@sierrafoothills.example", "is_primary": 1}]],
				"row_changed": [["phone_nos", 1, "r1", [["phone", "5305550142", "+15305550142"]]]]}
		out = scrub_version_data(data, lambda f, v: f in {"email", "email_id", "phone"}, "P")
		self.assertEqual(out["changed"], [["email", "P", "P"], ["status", "New", "Contacted"]])
		self.assertEqual(out["added"][0][1], {"email_id": "P", "is_primary": 1})
		self.assertEqual(out["row_changed"][0][3], [["phone", "P", "P"]])
		self.assertEqual(data["changed"][0][1], "marisol@sierrafoothills.example")  # input not mutated
```

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_rules_struct`, expected ImportError.
- [ ] **Step 3: Implement the three functions** in `rules.py`. `scrub_version_data` deep-copies its input first (`copy.deepcopy`).
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat: add deal-field, address-header and version scrubbing rules`

---

## Phase B — Records and access

### Task 4: Compliance role, Privacy settings, ledgers, seeding

**Files:**
- Create the doctypes (`.json`, `.py`, `__init__.py`; module `Privacy`) under `crm/privacy/doctype/`:
  - **`CRM Privacy Settings`** (`issingle`). Fields:
    - `head_of_compliance` (Link User)
    - `contract_retention_months` (Int)
    - `identifier_secret` (Password, hidden, read_only)
    - `personal_fields` (Table → CRM Personal Field)
    - Permissions: System Manager and Compliance have read/write. Sales User has none.
  - **`CRM Personal Field`** (`istable`). Fields:
    - `document_type` (Select, reqd; options `CRM Lead\nCRM Deal\nContact\nContact Email\nContact Phone\nCRM Contacts`)
    - `fieldname` (Data, reqd)
  - **`CRM Do Not Contact`** (`autoname: hash`, `track_changes: 0`). Fields:
    - `identifier_hash` (Data, reqd, unique)
    - `kind` (Select `Email\nPhone`)
    - `request` (Data, the request number as text so purging the request leaves no broken link)
    - Permissions: Compliance has read only.
  - **`CRM Retained Contract`** (`autoname: hash`, `track_changes: 0`). Fields:
    - `person_name` (Data)
    - `contract_references` (Small Text)
    - `request` (Data)
    - `delete_after` (Date, reqd)
    - Permissions: Compliance has read only.
- Create: `crm/privacy/install.py`
- Modify:
  - `crm/privacy/identifiers.py`: add the DB helpers.
  - `crm/hooks.py`: add `"crm.privacy.install.after_migrate"` to `after_migrate`.
  - `crm/install.py`: in `after_install()`, call `crm.privacy.install.after_migrate()` before the final commit.
- Test: `crm/privacy/tests/test_settings.py`

**Interfaces:**
- Produces:
  - `crm.privacy.rules.DEFAULT_PERSONAL_FIELDS: dict[str, list[str]]` (pin exactly):
    - `CRM Lead`: salutation, first_name, middle_name, last_name, lead_name, email, mobile_no, phone, job_title, image, gender, linkedin, twitter, facebook
    - `CRM Deal`: salutation, first_name, last_name, lead_name, email, mobile_no, phone, job_title, gender, linkedin, twitter, facebook
    - `Contact`: salutation, first_name, middle_name, last_name, full_name, email_id, mobile_no, phone, designation, image, gender
    - `Contact Email`: email_id
    - `Contact Phone`: phone
    - `CRM Contacts`: full_name, email, mobile_no, phone, gender
  - `crm.privacy.install.after_migrate() -> None`: calls `ensure_compliance_role()` (inserts Role `Compliance` with `desk_access=1` if missing) and `seed_personal_fields()` (fills the table from `DEFAULT_PERSONAL_FIELDS` **only when the table is empty**, so admin removals survive migrate). Task 14 adds `seed_outcome_template()` here.
  - `crm.privacy.identifiers.get_secret() -> str`: reads `identifier_secret` via `get_password`. If it's empty, it generates `secrets.token_hex(32)`, saves it, and returns it.
  - `crm.privacy.identifiers.personal_fields() -> dict[str, set[str]]`: reads the settings table.
  - `crm.privacy.identifiers.is_blocked(kind: str, value: str) -> bool`: normalizes, hashes, and checks `CRM Do Not Contact`.
  - `crm.privacy.identifiers.add_do_not_contact(kind: str, value: str, request: str) -> None`: idempotent.
  - `crm.privacy.identifiers.compliance_users() -> list[str]`: enabled users with the Compliance role, excluding Administrator and Guest.

- [ ] **Step 1: Write the failing tests** (`IntegrationTestCase`)

```python
class TestPrivacySettings(IntegrationTestCase):
	def test_role_and_seed(self):
		after_migrate()
		self.assertTrue(frappe.db.exists("Role", "Compliance"))
		self.assertEqual(personal_fields()["CRM Lead"], set(DEFAULT_PERSONAL_FIELDS["CRM Lead"]))

	def test_seed_does_not_readd_removed_rows(self):
		after_migrate()
		s = frappe.get_single("CRM Privacy Settings")
		s.personal_fields = [r for r in s.personal_fields if r.fieldname != "gender"]
		s.save()
		after_migrate()
		self.assertNotIn("gender", personal_fields()["CRM Lead"])

	def test_secret_generated_once(self):
		self.assertEqual(get_secret(), get_secret())

	def test_do_not_contact_roundtrip_any_format(self):
		add_do_not_contact("Phone", "(530) 555-0142", "PDR-0001")
		add_do_not_contact("Phone", "530.555.0142", "PDR-0001")
		self.assertEqual(frappe.db.count("CRM Do Not Contact"), 1)
		self.assertTrue(is_blocked("Phone", "+1 530 555 0142"))
		self.assertFalse(is_blocked("Phone", "530-555-0100"))
		row = frappe.get_last_doc("CRM Do Not Contact")
		self.assertNotIn("5550142", frappe.as_json(row.as_dict()))
```

- [ ] **Step 2: Run to verify failure** — `bench --site $SITE migrate && bench --site $SITE run-tests --app crm --module crm.privacy.tests.test_settings`
- [ ] **Step 3: Create the doctypes and implement the helpers.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat: add Compliance role, privacy settings and do-not-contact ledger`

---

### Task 5: The request doctype, access rules, test factories

**Files:**
- Create the doctypes under `crm/privacy/doctype/`:
  - **`CRM Erasure Request`** (`autoname: PDR-.####`, `track_changes: 0`, `title_field: name`). Fields, in order:
    - `request_type` (Select `Erasure`, default `Erasure`, read_only)
    - `arrived_via` (Select `Email\nPhone\nWeb form\nMail\nOther`, reqd, default `Email`)
    - `date_received` (Date, reqd, default `Today`)
    - `logged_by` (Link User, read_only)
    - `status` (Select `Logged\nAwaiting Sign-off\nOn Hold\nErased\nDeclined\nClosed`, default `Logged`, read_only)
    - `acknowledge_by`, `respond_by` (Date, read_only)
    - `requester_name` (Data), `other_names` (Small Text), `original_message` (Text)
    - `identifiers` (Table → CRM Erasure Identifier), `matches` (Table → CRM Erasure Match)
    - `contract_references` (Small Text)
    - `checklist` (Table → CRM Erasure Checklist Item)
    - `acknowledgment_sent` (Check), `acknowledged_on` (Date)
    - `approved_by` (Link User), `approved_on` (Datetime), `erased_on` (Datetime)
    - `erasure_status` (Select `\nQueued\nFailed`), `erasure_error` (Small Text)
    - `decline_reason` (Small Text)
    - `date_answered` (Date), `outcome` (Select `\nCompleted\nPartly completed\nDenied`), `denial_reason` (Small Text)
    - hidden Checks: `ack_reminder_sent`, `day30_reminder_sent`, `day40_alert_sent`
    - Permissions: Compliance has read/write/create; Sales Manager has read; Sales User has read/write/create (narrowed by the hook below).
  - **`CRM Erasure Identifier`** (istable): `kind` (Select `Email\nPhone`, reqd), `value` (Data, reqd; stored normalized), `source` (Select `Typed\nRecord`), `excluded` (Check).
  - **`CRM Erasure Match`** (istable): `reference_doctype` (Select `CRM Lead\nContact\nCRM Deal`, reqd), `reference_name` (Dynamic Link, reqd), `title` (Data), `reason` (Data), `confirmed` (Check).
  - **`CRM Erasure Checklist Item`** (istable): `description` (Data, reqd), `done` (Check), `done_by` (Link User, read_only), `done_on` (Datetime, read_only).
- Create: `crm/privacy/permissions.py`, `crm/privacy/tests/factories.py`
- Modify: `crm/hooks.py`. Add `"CRM Erasure Request"` to `permission_query_conditions` (→ `crm.privacy.permissions.get_permission_query_conditions`) and to `has_permission` (→ `crm.privacy.permissions.has_permission`).
- Test: `crm/privacy/tests/test_request.py`

**Interfaces:**
- Consumes: the `deadlines` functions (Task 1) and `normalize_identifier` (Task 2).
- Produces:
  - **`CRMErasureRequest` controller:**
    - `before_insert` sets `logged_by = frappe.session.user`.
    - `validate` does three things:
      1. sets `acknowledge_by` / `respond_by` from `date_received`;
      2. normalizes each identifier `value`, and throws `frappe.ValidationError("Not a valid email or phone")` when it normalizes to `""`; it drops duplicate `(kind, value)` rows, keeping the first;
      3. stamps checklist rows: when `done` turns on, it sets `done_by = session user` and `done_on = now`; when `done` turns off, it clears both.
    - Raises `frappe.ValidationError` if `date_received` is in the future.
  - **`crm.privacy.permissions`:**
    - `is_compliance(user: str | None = None) -> bool`
    - `access_level(doc, user: str | None = None) -> Literal["full", "summary"] | None`:
      - `"full"` for Compliance or Sales Manager;
      - `"full"` for the logger while `status == "Logged"`;
      - `"summary"` for the logger at any other status;
      - `None` otherwise.
    - `has_permission(doc, ptype: str, user: str) -> bool`:
      - Compliance: any ptype;
      - Sales Manager: `read` only;
      - logger with status Logged: `read` / `write`;
      - `create`: allowed for anyone holding Sales User;
      - otherwise False.
    - `get_permission_query_conditions(user: str) -> str`: `""` for Compliance / Sales Manager. Otherwise ``(`tabCRM Erasure Request`.logged_by = {escaped user} and `tabCRM Erasure Request`.status = 'Logged')``.
  - **`factories.py`:**
    - `make_compliance_user(email: str = "privacy.officer@example.com") -> str`: roles Compliance and Sales User.
    - `make_marisol(owner: str | None = None) -> frappe._dict` with keys `lead`, `contact`, `open_deal`, `won_deal`, `org`. When `owner` is given, it becomes `lead_owner` and `deal_owner`, so a Sales User logger can read the records. The data:
      - Organization "Sierra Foothills Dental Group";
      - lead with first_name Marisol, last_name Vega, email `Marisol@SierraFoothills.example`, mobile `(530) 555-0142`, job_title "Office Manager", status New;
      - contact named via first/last name with the same email and mobile;
      - `open_deal` in status `Negotiation` and `won_deal` in status `Won`, both with `contacts=[{"contact": contact}]`, `lead=lead`, organization, and `deal_value` 12000 / 8000.
    - `make_request(**fields) -> Document`: inserts a CRM Erasure Request as the current user.
    - Reuse `create_test_contact` / `create_test_deal` from `crm.fcrm.doctype.crm_deal.test_crm_deal`, and `make_user` from `crm.permissions.test_org_hierarchy`.

- [ ] **Step 1: Write the failing tests**

```python
class TestErasureRequest(IntegrationTestCase):
	def test_naming_and_deadlines(self):
		r = make_request(date_received="2026-10-26", requester_name="M")
		self.assertRegex(r.name, r"^PDR-\d{4}$")
		self.assertEqual(str(r.acknowledge_by), "2026-11-09")
		self.assertEqual(str(r.respond_by), "2026-12-10")
		self.assertEqual(r.logged_by, "Administrator")

	def test_identifiers_normalized_and_deduped(self):
		r = make_request(identifiers=[{"kind": "Phone", "value": "(530) 555-0142"},
				{"kind": "Phone", "value": "530.555.0142"}, {"kind": "Email", "value": " A@B.example"}])
		self.assertEqual([(i.kind, i.value) for i in r.identifiers],
				[("Phone", "+15305550142"), ("Email", "a@b.example")])

	def test_future_date_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_request(date_received=frappe.utils.add_days(frappe.utils.today(), 1))

	def test_checklist_stamp(self):
		r = make_request(checklist=[{"description": "Delete recordings at provider (Twilio)"}])
		r.checklist[0].done = 1
		r.save()
		self.assertEqual(r.checklist[0].done_by, "Administrator")
		self.assertIsNotNone(r.checklist[0].done_on)

	def test_visibility(self):
		make_user("rep@example.com", ["Sales User"]); make_user("other@example.com", ["Sales User"])
		make_user("mgr@example.com", ["Sales Manager"]); officer = make_compliance_user()
		frappe.set_user("rep@example.com")
		r = make_request(requester_name="M")
		self.assertEqual(access_level(r, "rep@example.com"), "full")
		self.assertIsNone(access_level(r, "other@example.com"))
		self.assertFalse(frappe.has_permission("CRM Erasure Request", "read", r.name, user="other@example.com"))
		frappe.db.set_value("CRM Erasure Request", r.name, "status", "Awaiting Sign-off")
		r.reload()
		self.assertEqual(access_level(r, "rep@example.com"), "summary")
		self.assertFalse(frappe.has_permission("CRM Erasure Request", "read", r.name, user="rep@example.com"))
		self.assertEqual(access_level(r, "mgr@example.com"), "full")
		self.assertFalse(frappe.has_permission("CRM Erasure Request", "write", r.name, user="mgr@example.com"))
		self.assertEqual(access_level(r, officer), "full")
```

- [ ] **Step 2: Run to verify failure** — migrate, then `--module crm.privacy.tests.test_request`.
- [ ] **Step 3: Create the doctypes, controller, permissions and factories.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat: add erasure request doctype with deadline fields and access rules`

---

## Phase C — Logging, matching, hold

### Task 6: Logging, matching and the request API

**Files:**
- Create: `crm/privacy/matching.py`, `crm/privacy/api.py`
- Test: `crm/privacy/tests/test_matching.py`

**Interfaces:**
- Consumes: the factories, `access_level`, `normalize_identifier`, and the `deadlines` functions.
- Produces (`matching.py`):
  - `sync_identifiers(request) -> None`: adds `source="Record"` identifiers for every email and phone on confirmed CRM Lead rows (`email`, `mobile_no`, `phone`) and on confirmed Contacts (`Contact Email.email_id`, `Contact Phone.phone`). It never removes rows and never changes `excluded`.
  - `find_matches(request) -> list[dict]`: each item is `{reference_doctype, reference_name, title, reason}`. Matching uses the non-excluded identifiers:
    - leads: `email` equal, or `mobile_no` / `phone` normalized equal;
    - contacts: Contact Email / Contact Phone / `mobile_no`;
    - deals: `email` / `mobile_no` / `phone`;
    - linked: deals with `lead` in confirmed leads (reason `"Converted from lead"`), and deals whose `CRM Contacts.contact` is in confirmed contacts (reason `"Lists confirmed contact"`).
    - Phones are pre-filtered in SQL with `crm.utils.phone_search_digits(value, "US")` and `crm.integrations.api._digits_only(column).like(...)`, then confirmed in Python with `normalize_identifier`.
    - Email reasons are `"Email matches"`; phone reasons are `"Phone matches"`.
  - `refresh_matches(request) -> None`: repeats `sync_identifiers` → `find_matches` until no new confirmed-record identifiers appear, with at most 3 rounds. It appends new suggestions unconfirmed, drops unconfirmed rows no longer suggested, and keeps confirmed rows.
  - `identifier_usage(request) -> list[dict]`: one dict per identifier, `{kind, value, excluded, records: int, emails: int, calls: int}`. `emails` counts Communications with the address in `sender` / `recipients` / `cc` / `bcc`; `calls` counts CRM Call Logs with the number in `from` / `to`.
- Produces (`api.py`, every endpoint `@frappe.whitelist()` and type-annotated):
  - `log_request(source_doctype: str | None = None, source_name: str | None = None) -> str`. The source must be one of CRM Lead, Contact, CRM Deal, and the caller needs read access to it. With a source, it:
    - prefills `requester_name` (lead `lead_name`, contact `full_name`, or the deal's primary contact `full_name`);
    - adds `Typed` identifiers from the source's email and phone fields;
    - adds a confirmed match for the source;
    - runs `refresh_matches`, saves, and returns the name.
    - Without a source, it creates an empty request.
  - `get_requests() -> list[dict]`. Each row has `name, status, date_received, acknowledge_by, respond_by, days_left, logged_by`, plus `requester_name`, which is `None` unless access is full.
    - Rows: Compliance and Sales Manager see all; everyone else sees only rows they logged.
    - Order: open rows (status ≠ Closed) by `days_left` ascending, then Closed rows by `date_received` descending.
    - `days_left` is `None` for Closed rows.
  - `get_request(name: str) -> dict`:
    - throws `frappe.PermissionError` when `access_level` is None;
    - summary: `{access: "summary", name, status, acknowledge_by, respond_by, days_left}`;
    - full: the same keys plus `doc` (`as_dict()`), `identifier_usage`, `emails` (Communications whose reference is this request: `name, subject, sender, communication_date`), and `can`.
    - `can = {edit, submit, approve, decline, close, manage_checklist}`:
      - `edit`: the logger while Logged, or Compliance while not Erased / Closed;
      - `submit`: edit access and status Logged;
      - `approve`: Compliance, not the logger, status Awaiting Sign-off;
      - `decline`: Compliance and status in Logged / Awaiting Sign-off / On Hold;
      - `close`: Compliance and status in Erased / Declined;
      - `manage_checklist`: Compliance and status not Closed.
  - `save_request(name: str, values: dict) -> dict`. Requires `can.edit`, except that `checklist` and `acknowledgment_sent` / `acknowledged_on` need `manage_checklist`.
    - Allowed keys: `arrived_via`, `date_received`, `requester_name`, `other_names`, `original_message`, `identifiers`, `matches`, `contract_references` (Compliance only), `checklist`, `acknowledgment_sent`, `acknowledged_on`. Any other key raises `frappe.ValidationError`.
    - Table keys take a list of row dicts and are **merged, not replaced**. A row with a `name` updates that row: only `excluded` for identifiers, `confirmed` for matches, `done` for checklist. A row without a `name` is appended: `kind` + `value` (source Typed) for identifiers; `reference_doctype` + `reference_name` + `confirmed` for matches, only if the caller can read that record; `description` for checklist. Rows that aren't mentioned stay as they are.
    - It runs `refresh_matches`, saves, and returns `get_request(name)`.
  - `refresh_request_matches(name: str) -> dict`: requires `can.edit`.

- [ ] **Step 1: Write the failing tests**

```python
class TestMatching(IntegrationTestCase):
	def test_log_from_lead_suggests_contact_and_both_deals(self):
		m = make_marisol()
		name = log_request("CRM Lead", m.lead)
		r = frappe.get_doc("CRM Erasure Request", name)
		self.assertEqual(r.requester_name, "Marisol Vega")
		confirmed = {(x.reference_doctype, x.reference_name) for x in r.matches if x.confirmed}
		self.assertEqual(confirmed, {("CRM Lead", m.lead)})
		suggested = {(x.reference_doctype, x.reference_name) for x in r.matches}
		self.assertTrue({("Contact", m.contact), ("CRM Deal", m.open_deal), ("CRM Deal", m.won_deal)} <= suggested)

	def test_phone_in_other_format_matches(self):
		m = make_marisol()
		other = create_test_contact(first_name="Front", mobile_no="530.555.0142")
		r = make_request(identifiers=[{"kind": "Phone", "value": "+1 530 555 0142"}])
		refresh_matches(r)
		self.assertIn(("Contact", other.name), {(x.reference_doctype, x.reference_name) for x in r.matches})

	def test_excluded_identifier_does_not_match(self):
		m = make_marisol()
		r = make_request(identifiers=[{"kind": "Phone", "value": "5305550142", "excluded": 1}])
		refresh_matches(r)
		self.assertEqual(r.matches, [])

	def test_confirming_contact_pulls_its_identifiers(self):
		m = make_marisol()
		c = frappe.get_doc("Contact", m.contact)
		c.append("email_ids", {"email_id": "mv@home.example"})
		c.save()
		r = make_request(matches=[{"reference_doctype": "Contact", "reference_name": m.contact, "confirmed": 1}])
		refresh_matches(r)
		self.assertIn(("Email", "mv@home.example"), {(i.kind, i.value) for i in r.identifiers})

	def test_summary_hides_details_after_submit(self):
		make_user("rep@example.com", ["Sales User"])
		frappe.set_user("rep@example.com")
		name = log_request()
		frappe.db.set_value("CRM Erasure Request", name, "status", "Awaiting Sign-off")
		out = get_request(name)
		self.assertEqual(set(out), {"access", "name", "status", "acknowledge_by", "respond_by", "days_left"})

	def test_save_request_rejects_unknown_keys(self):
		name = log_request()
		with self.assertRaises(frappe.ValidationError):
			save_request(name, {"status": "Erased"})

	def test_list_sorted_by_days_left(self):
		a = make_request(date_received=frappe.utils.add_days(frappe.utils.today(), -40)).name
		b = make_request(date_received=frappe.utils.today()).name
		names = [r["name"] for r in get_requests()]
		self.assertLess(names.index(a), names.index(b))
```

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_matching`
- [ ] **Step 3: Implement `matching.py` and these `api.py` endpoints.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat: log erasure requests and suggest matching records`

---

### Task 7: Submission, On Hold and release

**Files:**
- Create: `crm/privacy/hold.py`, and `crm/privacy/reminders.py` (only `notify` for now)
- Modify:
  - `crm/privacy/api.py`
  - `crm/hooks.py`: add `"crm.privacy.hold.on_deal_update"` to `doc_events["CRM Deal"]["on_update"]`
  - `crm/fcrm/doctype/crm_notification/crm_notification.json`: append `Privacy` to the `type` options
- Test: `crm/privacy/tests/test_hold.py`

**Interfaces:**
- Produces:
  - `crm.privacy.reminders.notify(users: list[str], subject: str, request: str, reference_doctype: str = "CRM Erasure Request", reference_name: str | None = None) -> None`. For each user it inserts a CRM Notification with `type="Privacy"`, `from_user` = Administrator, `notification_text=subject`, `message=subject`, `notification_type_doctype="CRM Erasure Request"`, `notification_type_doc=request`, `reference_doctype` / `reference_name` (default: the request). It then sends one `frappe.sendmail(recipients=users, subject=subject, message=subject, reference_doctype="CRM Erasure Request", reference_name=request)`. It returns early when `users` is empty.
  - `crm.privacy.hold.open_deals_for(request) -> list[str]`: deals whose `CRM Contacts.contact` is a confirmed Contact match, and whose status `type` is in `("Open", "Ongoing", "On Hold")`.
  - `crm.privacy.hold.apply_hold(request) -> bool`:
    - If `open_deals_for` is non-empty: set status `On Hold`, and notify each deal owner about each of their deals. The notice uses `reference_doctype="CRM Deal"`, `reference_name=deal`, and subject `f"Erasure request {request.name} is on hold: contact {contact} on deal {deal} asked to be erased. Remove them from the deal or close it."`. Return True.
    - Otherwise return False.
  - `crm.privacy.hold.on_deal_update(doc, method) -> None`: for every request with status On Hold, recompute `open_deals_for`. When it is empty, set status to `Awaiting Sign-off` via `frappe.db.set_value`. On Hold requests are few, so it doesn't filter by deal.
  - `api.submit_request(name: str) -> dict`:
    - requires `can.submit`;
    - requires at least one confirmed match or one non-excluded identifier, else `frappe.ValidationError`;
    - sets `Awaiting Sign-off`, then calls `apply_hold`;
    - returns `get_request(name)`.
  - `crm/api/notifications.py` must route `reference_doctype == "CRM Erasure Request"` to `route_name="Erasure Request"` (the frontend param comes in Task 16). Keep the existing Lead / Deal behaviour.

- [ ] **Step 1: Write the failing tests**

```python
class TestHold(IntegrationTestCase):
	def _submitted(self, m):
		name = log_request("Contact", m.contact)
		save_request(name, {"matches": [{"reference_doctype": "CRM Deal", "reference_name": m.open_deal, "confirmed": 1}]})
		return submit_request(name)

	def test_open_deal_puts_on_hold_and_notifies_owner(self):
		make_user("owner@example.com", ["Sales User"])
		m = make_marisol()
		frappe.db.set_value("CRM Deal", m.open_deal, "deal_owner", "owner@example.com")
		out = self._submitted(m)
		self.assertEqual(out["status"], "On Hold")
		self.assertTrue(frappe.db.exists("CRM Notification", {"to_user": "owner@example.com", "type": "Privacy",
				"reference_name": m.open_deal}))

	def test_removing_contact_releases_hold(self):
		m = make_marisol()
		name = self._submitted(m)["name"]
		remove_contact(m.open_deal, m.contact)          # crm_deal.remove_contact -> deal.save()
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", name, "status"), "Awaiting Sign-off")

	def test_won_only_goes_straight_to_sign_off(self):
		m = make_marisol()
		frappe.get_doc("CRM Deal", m.open_deal).update({"status": "Lost", "lost_reason": "Other", "lost_notes": "x"}).save()
		self.assertEqual(self._submitted(m)["status"], "Awaiting Sign-off")

	def test_empty_request_cannot_submit(self):
		with self.assertRaises(frappe.ValidationError):
			submit_request(log_request())
```

(Create a `CRM Lost Reason` named `Other` in `setUp` if it doesn't exist.)

- [ ] **Step 2: Run to verify failure** — migrate, then `--module crm.privacy.tests.test_hold`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat: submit erasure requests and hold them while the person is on an open deal`

---

## Phase D — Erasure

### Task 8: Erasure plan and approval preview

**Files:**
- Create: `crm/privacy/plan.py`
- Modify: `crm/privacy/api.py`
- Test: `crm/privacy/tests/test_plan.py`

**Interfaces:**
- Produces:

```python
@dataclass
class ErasurePlan:
	request: str
	emails: set[str]            # confirmed, non-excluded, normalized
	phones: set[str]
	leads: list[str]            # confirmed
	contacts: list[str]         # confirmed
	deals_on: list[str]         # confirmed deals listing a confirmed contact, or whose email/mobile/phone is hers
	deals_removed: list[str]    # other confirmed deals
	addresses: list[str]        # Address linked (Dynamic Link or Contact.address) to confirmed contacts
	communications: list[str]
	call_logs: list[str]
	notes: list[str]            # on records + notes linked from those call logs
	tasks: list[str]
	comments: list[str]
	files: list[str]            # File names
	has_recordings: bool
	her_values: dict[str, set[str]]   # case-folded name/title/social values from confirmed leads+contacts, keyed by fieldname
```

  - `plan_erasure(request) -> ErasurePlan`. The record sets are `R = leads ∪ contacts ∪ deals_on`.
    - **Communications:** reference in `R`, or a `timeline_links` row in `R`, or a confirmed email in `sender` / `recipients` / `cc` / `bcc`. Pre-filter with `like %email%`, then confirm with `normalize_email` over `email.utils.getaddresses`.
    - **Call logs:** `reference_docname` in `R`, or a `links` row in `R`, or a confirmed phone in `from` / `to` (digits pre-filter, then normalize).
    - **Notes, tasks, comments:** reference in `R`.
    - **Files:** `attached_to_doctype` / `attached_to_name` in `R ∪ communications`, plus Files whose `file_url` equals a lead or contact `image`.
  - `unlisted_custom_fields() -> list[dict]`: Custom Field rows on CRM Lead, CRM Deal or Contact with fieldtype in `Data, Small Text, Text, Long Text, Phone, Attach, Attach Image, Text Editor` whose fieldname is not in `personal_fields()`. Each row is `{dt, fieldname, label}`.
  - `preview(plan: ErasurePlan) -> dict`, with shape `{remove: [...], keep: [...], warnings: {open_checklist: [str], unlisted_custom_fields: [...]}}`:
    - `remove` items: `{kind, count, links: [{doctype, name, title}]}`, where kind is one of `Leads, Contacts, Deals (still on), Addresses, Emails, Calls, Notes, Tasks, Comments, Files`. Links are listed only for the record kinds.
    - `keep` items: `{label, links}` for organizations, "Deal values, status and stage", "Open deals she was removed from (their notes, tasks, comments and files stay)" with `deals_removed` links, "Lead and deal records as anonymized shells", "Email, call and note records as placeholders", and, when `contract_references` is set, "Retained-contract entry".
  - `api.get_erasure_preview(name: str) -> dict`: Compliance only; returns `preview(plan_erasure(doc))`.

- [ ] **Step 1: Write the failing tests**

```python
class TestPlan(IntegrationTestCase):
	def setUp(self):
		self.m = make_marisol()
		self.r = make_request(identifiers=[{"kind": "Email", "value": "marisol@sierrafoothills.example"},
				{"kind": "Phone", "value": "5305550142"}],
			matches=[{"reference_doctype": d, "reference_name": n, "confirmed": 1} for d, n in
				[("CRM Lead", self.m.lead), ("Contact", self.m.contact), ("CRM Deal", self.m.won_deal), ("CRM Deal", self.m.open_deal)]])
		remove_contact(self.m.open_deal, self.m.contact)

	def test_still_on_vs_removed(self):
		p = plan_erasure(self.r)
		self.assertEqual(p.deals_on, [self.m.won_deal])
		self.assertEqual(p.deals_removed, [self.m.open_deal])

	def test_email_by_address_anywhere_and_notes_on_removed_deal_kept(self):
		c = make_communication(sender="Marisol Vega <MARISOL@sierrafoothills.example>", reference=("CRM Deal", self.m.open_deal))
		n = make_note(("CRM Deal", self.m.open_deal))
		p = plan_erasure(self.r)
		self.assertIn(c, p.communications)
		self.assertNotIn(n, p.notes)

	def test_call_log_matched_by_formatted_number_and_recording_flag(self):
		cl = make_call_log(**{"from": "530.555.0142", "to": "+15550001111", "recording_url": "https://api.twilio.com/r/1"})
		p = plan_erasure(self.r)
		self.assertIn(cl, p.call_logs)
		self.assertTrue(p.has_recordings)

	def test_preview_flags_unlisted_custom_field(self):
		create_custom_field("CRM Lead", {"fieldname": "personal_mobile", "fieldtype": "Data", "label": "Personal mobile"})
		out = preview(plan_erasure(self.r))
		self.assertIn("personal_mobile", [f["fieldname"] for f in out["warnings"]["unlisted_custom_fields"]])
		self.assertIn("Leads", [x["kind"] for x in out["remove"]])
```

Add `make_communication(sender, reference=None, recipients="", subject="Hello", content="Hi")`, `make_note(reference)` and `make_call_log(**fields)` to `factories.py` (inserts with `ignore_permissions`). `create_custom_field` comes from `frappe.custom.doctype.custom_field.custom_field`.

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_plan`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat: build the erasure plan and approval preview`

---

### Task 9: Approval, the all-or-nothing job, record erasure

**Files:**
- Create: `crm/privacy/erasure.py`
- Modify: `crm/privacy/api.py`
- Test: `crm/privacy/tests/test_erasure_records.py`

**Interfaces:**
- Consumes: `plan_erasure`, `apply_hold`, the `rules` placeholders, `deal_fields_to_blank`, and `personal_fields`.
- Produces:
  - `api.approve_request(name: str, confirmation: str) -> dict`. Checks, in this order (each failure is `frappe.PermissionError` or `frappe.ValidationError`):
    1. Compliance;
    2. user ≠ `logged_by`;
    3. status is `Awaiting Sign-off`;
    4. `confirmation.strip() == name`;
    5. `contract_references` empty, or `contract_retention_months` > 0;
    6. `apply_hold(doc)` is False. If it returns True, return `get_request(name)` with status On Hold and do not enqueue.

    It then sets `erasure_status="Queued"`, clears `erasure_error`, and calls `frappe.enqueue("crm.privacy.erasure.run_erasure", queue="long", job_id=f"erasure-{name}", deduplicate=True, enqueue_after_commit=True, request=name, approver=frappe.session.user)`. It returns `get_request(name)`.
  - `erasure.run_erasure(request: str, approver: str) -> None`:

```python
def run_erasure(request, approver):
	doc = frappe.get_doc("CRM Erasure Request", request)
	if doc.status != "Awaiting Sign-off":
		return
	frappe.db.savepoint("erasure")
	after_commit: list[Callable] = []      # registered only on success: savepoint rollback doesn't clear frappe's callbacks
	try:
		plan = plan_erasure(doc)
		for step in STEPS:                 # erase_records (T9), sweep_activities (T10), finish (T11)
			step(plan, doc, after_commit)
		frappe.db.set_value("CRM Erasure Request", request, {"status": "Erased", "approved_by": approver,
			"approved_on": now(), "erased_on": now(), "erasure_status": "", "erasure_error": ""})
	except Exception:
		frappe.db.rollback(save_point="erasure")
		frappe.db.set_value("CRM Erasure Request", request, {"erasure_status": "Failed",
			"erasure_error": frappe.get_traceback(with_context=False)[-2000:]})   # no PII in our own messages
		_commit()
		return
	for fn in after_commit:
		frappe.db.after_commit.add(fn)
	_commit()

def _commit():
	if not frappe.flags.in_test:           # tests keep their transaction; they call frappe.db.after_commit.run() when needed
		frappe.db.commit()
```

  - `STEPS: list[Callable[[ErasurePlan, Document, list[Callable]], None]]`. This task registers `erase_records`.
  - `erase_records(plan, doc, after_commit) -> None`:
    - **Leads:** for each listed personal field that is set, write `""`. `first_name` and `lead_name` get `erased_person(req)` instead.
    - **Deals in `deals_on`:** blank the fields returned by `deal_fields_to_blank(deal_row, plan.her_values, plan.emails, plan.phones)`.
    - **Every deal, confirmed or not:**
      - a `CRM Contacts` row whose `contact` is a confirmed contact gets `full_name` set to the placeholder and `email`, `mobile_no` and `phone` blanked, with the `contact` link kept. The row is her data even on a deal nobody confirmed.
      - deal `email` / `mobile_no` / `phone` values that normalize to a confirmed identifier are blanked. These are copied from her as primary contact.
    - **Contacts:**
      - blank the listed personal fields; `first_name` and `full_name` get the placeholder;
      - `frappe.db.delete` the `Contact Email` and `Contact Phone` rows;
      - rename with `frappe.rename_doc("Contact", old, new, force=True, show_alert=False)`. `new` is `erased_person(req)`, with suffixes `-2`, `-3`… for further contacts.
    - **Addresses:** blank every Data / Small Text / Text / Link / Select field except `address_type`, then rename the same way.
    - **Rename comments:** delete the `Comment` rows of type `Edit` that rename_doc added on the renamed records.
    - **No-op guarantees:** no `doc.save()`, and every `set_value` uses `update_modified=False`. Tasks 10 and 11 append `sweep_activities` and `finish` to `STEPS`.

- [ ] **Step 1: Write the failing tests**

```python
class TestErasureRecords(IntegrationTestCase):
	def setUp(self):
		make_user("rep@example.com", ["Sales User"])
		self.m = make_marisol(owner="rep@example.com")
		self.officer = make_compliance_user()
		frappe.get_doc("CRM Deal", self.m.open_deal).update({"status": "Lost", "lost_reason": "Other", "lost_notes": "x"}).save()
		frappe.set_user("rep@example.com")
		self.name = log_request("CRM Lead", self.m.lead)
		# open_deal (now Lost) stays unconfirmed on purpose: her contact row on it must still be anonymized
		save_request(self.name, {"matches": [{"reference_doctype": d, "reference_name": n, "confirmed": 1}
			for d, n in [("Contact", self.m.contact), ("CRM Deal", self.m.won_deal)]]})
		submit_request(self.name)
		frappe.set_user("Administrator")

	def test_logger_cannot_approve_and_manager_cannot_approve(self):
		frappe.set_user("rep@example.com")
		with self.assertRaises(frappe.PermissionError):
			approve_request(self.name, self.name)
		make_user("mgr@example.com", ["Sales Manager", "System Manager"]); frappe.set_user("mgr@example.com")
		with self.assertRaises(frappe.PermissionError):
			approve_request(self.name, self.name)

	def test_wrong_confirmation(self):
		frappe.set_user(self.officer)
		with self.assertRaises(frappe.ValidationError):
			approve_request(self.name, "PDR-9999")

	def test_records_blanked_kept_and_renamed(self):
		run_erasure(self.name, self.officer)
		lead = frappe.get_doc("CRM Lead", self.m.lead)
		self.assertEqual((lead.first_name, lead.lead_name, lead.email, lead.mobile_no, lead.job_title),
			(f"Erased person {self.name}",) * 2 + ("", "", ""))
		self.assertEqual(lead.status, "New")
		self.assertFalse(frappe.db.exists("Contact", self.m.contact))
		new_contact = f"Erased person {self.name}"
		self.assertEqual(frappe.db.count("Contact Email", {"parent": new_contact}), 0)
		deal = frappe.get_doc("CRM Deal", self.m.won_deal)
		self.assertEqual((deal.email, deal.mobile_no, deal.deal_value, deal.status), ("", "", 8000, "Won"))
		self.assertEqual(deal.contacts[0].contact, new_contact)
		self.assertEqual(deal.contacts[0].full_name, new_contact)
		self.assertFalse(frappe.db.exists("Comment", {"reference_name": new_contact, "content": ["like", "%Marisol%"]}))
		lost = frappe.get_doc("CRM Deal", self.m.open_deal)        # unconfirmed deal
		self.assertEqual((lost.contacts[0].full_name, lost.email), (new_contact, ""))
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", self.name, "status"), "Erased")

	def test_failure_rolls_back_everything(self):
		def boom(*a): raise RuntimeError("x")
		with patch.object(erasure, "STEPS", [erasure.erase_records, boom]):
			run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.get_value("CRM Lead", self.m.lead, "email"), "Marisol@SierraFoothills.example")
		self.assertTrue(frappe.db.exists("Contact", self.m.contact))
		r = frappe.db.get_value("CRM Erasure Request", self.name, ["status", "erasure_status"], as_dict=True)
		self.assertEqual((r.status, r.erasure_status), ("Awaiting Sign-off", "Failed"))
		run_erasure(self.name, self.officer)            # a retry after failure succeeds
		self.assertEqual(frappe.db.get_value("CRM Erasure Request", self.name, "status"), "Erased")
```

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_erasure_records`
- [ ] **Step 3: Implement.** If `rename_doc` writes anything other than `Edit` comments that holds the old name, scrub it too, and record what in the commit message.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat: approve erasure requests and erase lead, deal, contact and address records`

---

### Task 10: Sweep emails, calls, notes, tasks, comments, files and side tables

**Files:**
- Create: `crm/privacy/sweep.py`
- Modify: `crm/privacy/erasure.py` (append `sweep_activities` to `STEPS`)
- Test: `crm/privacy/tests/test_sweep.py`

**Interfaces:**
- Consumes: `ErasurePlan`, `replace_addresses`, `scrub_identifiers`, and the placeholders.
- Produces:
  - `erase_communications(names: list[str], emails: set[str], phones: set[str], request: str) -> None`: the Communications rules below, as a standalone function. Task 14 reuses it at close.
  - `sweep_activities(plan, doc, after_commit) -> None`. Placeholders: P = `erased_person(req)`, C = `erased_content(req)`.
  - **Communications:**
    - `subject` and `content` become C;
    - `sender`, `recipients`, `cc` and `bcc` go through `replace_addresses(..., plan.emails, P)`;
    - `sender_full_name` becomes P when the sender was hers;
    - `phone_no` becomes P when it normalizes into `plan.phones`;
    - `Communication Link.link_title` becomes P for links into the plan's record sets.
  - **Call logs:**
    - `from` / `to` become P where they normalize into `plan.phones`;
    - `recording_url` is cleared;
    - linked notes are added to the notes handling;
    - when `plan.has_recordings`, append the checklist row "Delete recordings at provider (Twilio)" once.
  - **Notes, tasks, comments:**
    - FCRM Note `title` and `content` become C;
    - CRM Task `title` and `description` become C, with status, dates and assignee kept;
    - Comment `content` becomes C;
    - `_comments` on each record in `R` is reset to `"[]"`.
  - **Files:**
    - delete the File rows with `frappe.db.delete("File", {"name": ...})`;
    - for each File attached to a record in `R`, insert one `Comment` (`comment_type="Info"`, content `erased_file(req)`, `reference_doctype` / `reference_name` = the record);
    - for each removed `file_url` with no remaining File row, append a disk-delete callable to `after_commit` (path `frappe.get_site_path("private" if is_private else "public", "files", basename)`; ignore FileNotFoundError).
  - **Side tables:** all text goes through `scrub_identifiers(text, plan.emails, plan.phones, P)`, or becomes C when the row references a record in `R` or the request.
    - CRM Notification: `message`, `notification_text`
    - Notification Log: `subject`, `email_content`
    - ToDo: `description` for `reference_name` in `R`
    - Email Queue: `message` becomes C when the queue row references `R` / the request or contains a confirmed email; Email Queue Recipient: `recipient` where it is a confirmed email
    - WA Message: `message` where `reference_docname` is in `R`, or `to` is a WA Profile whose `phone_number` normalizes into `plan.phones`
    - WA Profile: `phone_number` and `profile_name` become P
    - Event Participants: `email` where hers
    - Failed Lead Sync Log: `lead_data` and `traceback` become C where they contain a confirmed email or phone digits
    - CRM Enrichment Run with `reference_name` in `R`: `raw_json = "{}"`, `notes = C`, `social_profiles = ""`; its `changes` rows whose `fieldname` is a personal field get `old_value` / `new_value` = C
  - **Before writing the WA, Event and Notification Log fieldnames,** open `apps/whatsapp/.../wa_message.json`, `wa_profile.json`, `apps/frappe/frappe/desk/doctype/event_participants/event_participants.json` and `notification_log.json` in the bench and confirm them.
  - **Re-index:** append `CRMSearch().index_doc(doctype, name)` callables to `after_commit` for every Comment, Communication and FCRM Note touched.

- [ ] **Step 1: Write the failing tests** (setUp as in Task 9, then `run_erasure` as Administrator)

```python
	def test_email_wiped_everywhere_colleague_kept(self):
		c = make_communication(sender="tyler@northpine.example",
			recipients='"Marisol Vega" <marisol@sierrafoothills.example>, dana@northpine.example', subject="Quote",
			content="Hi Marisol, call 530-555-0142")
		run_erasure(self.name, self.officer)
		row = frappe.db.get_value("Communication", c, ["subject", "content", "recipients", "sender"], as_dict=True)
		self.assertEqual(row.subject, f"Content erased {self.name}")
		self.assertEqual(row.content, f"Content erased {self.name}")
		self.assertEqual(row.recipients, f"Erased person {self.name}, dana@northpine.example")
		self.assertEqual(row.sender, "tyler@northpine.example")

	def test_call_log_number_and_recording(self):
		cl = make_call_log(**{"from": "(530) 555-0142", "to": "+15550001111", "recording_url": "https://x/r.mp3"})
		run_erasure(self.name, self.officer)
		row = frappe.db.get_value("CRM Call Log", cl, ["from", "to", "recording_url"], as_dict=True)
		self.assertEqual((row["from"], row.to, row.recording_url), (f"Erased person {self.name}", "+15550001111", None))
		items = frappe.get_all("CRM Erasure Checklist Item", {"parent": self.name}, pluck="description")
		self.assertEqual(items, ["Delete recordings at provider (Twilio)"])

	def test_task_text_wiped_status_kept(self):
		t = frappe.get_doc({"doctype": "CRM Task", "title": "Call Marisol", "status": "Todo",
			"reference_doctype": "CRM Lead", "reference_docname": self.m.lead}).insert()
		run_erasure(self.name, self.officer)
		self.assertEqual(frappe.db.get_value("CRM Task", t.name, ["title", "status"]), (f"Content erased {self.name}", "Todo"))

	def test_shared_file_content_survives(self):
		f1 = save_file("proposal.pdf", b"x", "CRM Lead", self.m.lead)
		f2 = frappe.get_doc({"doctype": "File", "file_url": f1.file_url, "attached_to_doctype": "CRM Organization",
			"attached_to_name": self.m.org}).insert()
		path = f1.get_full_path()
		run_erasure(self.name, self.officer)
		frappe.db.after_commit.run()
		self.assertFalse(frappe.db.exists("File", f1.name))
		self.assertTrue(frappe.db.exists("File", f2.name))
		self.assertTrue(os.path.exists(path))
		self.assertTrue(frappe.db.exists("Comment", {"reference_name": self.m.lead, "content": f"File erased {self.name}"}))

	def test_unshared_file_removed_from_disk_only_after_commit(self):
		f = save_file("id.pdf", b"y", "CRM Lead", self.m.lead)
		path = f.get_full_path()
		run_erasure(self.name, self.officer)
		self.assertTrue(os.path.exists(path))           # nothing leaves disk before commit
		frappe.db.after_commit.run()
		self.assertFalse(os.path.exists(path))
```

(`save_file` comes from `frappe.utils.file_manager`. `tearDown` must also delete any stray files on disk, since the DB rollback doesn't remove them.)

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_sweep`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify pass**, then re-run `test_erasure_records` (the rollback test must still pass with `sweep_activities` in `STEPS`).
- [ ] **Step 5: Commit** — `feat: sweep emails, calls, notes, files and side tables during erasure`

---

### Task 11: History scrub, do-not-contact, retained contract, dashboard invariance

**Files:**
- Create: `crm/privacy/history.py`
- Modify: `crm/privacy/erasure.py` (append `finish` to `STEPS`)
- Test: `crm/privacy/tests/test_history.py`

**Interfaces:**
- Produces: `finish(plan, doc, after_commit) -> None`, which calls the following in order:
  - **`scrub_versions(plan)`:** for every Version with `ref_doctype` / `docname` in the confirmed records (leads, contacts, both deal lists), rewrite `data` with `scrub_version_data`. The predicate is:
    - leads and contacts: `field in personal_fields()[doctype] ∪ Contact Email/Phone fields ∪ CRM Contacts fields`;
    - deals: the field is a deal personal field and its value is hers (case-folded in `her_values`, or normalized into `emails` / `phones`).
  - **`purge_deleted_documents(plan)`:** delete `Deleted Document` rows with `deleted_doctype` in `CRM Lead, Contact, CRM Deal, Communication, Address` whose `data` contains a confirmed email (`like`) or the phone's national digits.
  - **`create_do_not_contact(plan)`:** call `add_do_not_contact` for every email and phone in the plan.
  - **`create_retained_contract(doc)`:** when `contract_references` is set, insert a CRM Retained Contract with `person_name = doc.requester_name`, the references, `request = doc.name`, and `delete_after = add_months(today, contract_retention_months)`.

- [ ] **Step 1: Write the failing tests** (setUp as in Task 9)

```python
	def test_version_history_scrubbed_status_kept(self):
		lead = frappe.get_doc("CRM Lead", self.m.lead)
		lead.update({"email": "marisol.v@sierrafoothills.example", "status": "Contacted"}).save()
		save_request(self.name, {"identifiers": [{"kind": "Email", "value": "marisol.v@sierrafoothills.example"}]})
		run_erasure(self.name, self.officer)
		data = "".join(frappe.get_all("Version", {"ref_doctype": "CRM Lead", "docname": self.m.lead}, pluck="data"))
		self.assertNotIn("sierrafoothills", data.lower())
		self.assertIn("Contacted", data)

	def test_deleted_document_copy_removed(self):
		other = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Dup", "email": "marisol@sierrafoothills.example"}).insert()
		frappe.delete_doc("CRM Lead", other.name)
		run_erasure(self.name, self.officer)
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_name": other.name}))

	def test_do_not_contact_and_retained_contract(self):
		frappe.db.set_single_value("CRM Privacy Settings", "contract_retention_months", 84)
		frappe.db.set_value("CRM Erasure Request", self.name, "contract_references", "NP-2025-114")
		run_erasure(self.name, self.officer)
		self.assertTrue(is_blocked("Email", "MARISOL@sierrafoothills.example"))
		self.assertTrue(is_blocked("Phone", "530 555 0142"))
		rc = frappe.get_last_doc("CRM Retained Contract")
		self.assertEqual((rc.person_name, rc.contract_references), ("Marisol Vega", "NP-2025-114"))
		self.assertEqual(rc.delete_after, add_months(getdate(), 84))

	def test_dashboard_numbers_identical(self):
		frappe.set_user("Administrator")
		frm, to = "2020-01-01", "2030-12-31"
		before = get_dashboard(frm, to)
		run_erasure(self.name, self.officer)
		self.assertEqual(get_dashboard(frm, to), before)

	def test_no_personal_value_left_in_db_tables_we_control(self):
		run_erasure(self.name, self.officer)
		for dt, fields in [("CRM Lead", ["email", "lead_name"]), ("CRM Deal", ["email", "lead_name"]),
				("Contact", ["full_name", "email_id"]), ("CRM Contacts", ["full_name", "email"]),
				("Communication", ["recipients", "sender", "content"]), ("Version", ["data"]),
				("Comment", ["content"]), ("CRM Notification", ["notification_text", "message"])]:
			for f in fields:
				self.assertFalse(frappe.db.exists(dt, {f: ["like", "%sierrafoothills.example%"]}), f"{dt}.{f}")
				self.assertFalse(frappe.db.exists(dt, {f: ["like", "%Marisol%"]}), f"{dt}.{f}")
```

(`get_dashboard` comes from `crm.api.dashboard`.)

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_history`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify pass**, then run the whole privacy suite: `bench --site $SITE run-tests --app crm --module crm.privacy.tests.test_erasure_records` (plus `test_sweep` and `test_history`).
- [ ] **Step 5: Commit** — `feat: scrub change history, create do-not-contact entries and retained contracts on erasure`

---

## Phase E — Blocking and inbound mail

### Task 12: Block re-creation on every path

**Files:**
- Create: `crm/privacy/blocking.py`
- Modify:
  - `crm/hooks.py`: add `validate` → `crm.privacy.blocking.check_doc` for `CRM Lead`, `CRM Deal` and `Contact`. Contact already has a `validate` list, so append to it; CRM Lead and CRM Deal get new `validate` keys next to their `on_update`.
  - `crm/lead_syncing/doctype/lead_sync_source/facebook.py` (`sync_single_lead`, before the insert at :65)
  - `crm/api/whatsapp.py` (`_resolve_reference`, before `_create_lead` at :49-52)
- Test: `crm/privacy/tests/test_blocking.py`

**Interfaces:**
- Produces:
  - `class ErasedPersonError(frappe.DuplicateEntryError)`. The base class matters because Frappe's inbound-mail `_create_reference_document` swallows `DuplicateEntryError`, so a blocked sender never aborts mail ingest; Task 13 verifies this. The message is exactly `_("This person asked for their personal data to be erased. Their email address or phone number can't be added to the CRM.")`, with no values in it.
  - `IDENTIFIER_FIELDS` maps each doctype to `{"fields": {fieldname: kind}, "tables": {table_field: {fieldname: kind}}}`:
    - CRM Lead and CRM Deal: `email`, `mobile_no`, `phone`; CRM Deal also has table `contacts` → `email`, `mobile_no`, `phone`;
    - Contact: `email_id`, `mobile_no`, `phone`, plus tables `email_ids` → `email_id` and `phone_nos` → `phone`.
    - Extended at runtime with personal-field-list custom fields whose `fieldtype == "Phone"` or `options in ("Email", "Phone")`.
  - `new_identifier_values(doc) -> list[tuple[str, str]]`:
    - a new doc yields every non-empty value;
    - an existing doc yields only fields where `doc.has_value_changed(f)`, plus child-row values not present in the DB rows for that parent.
  - `blocked_values(doc) -> bool`: any `is_blocked(kind, value)` over `new_identifier_values(doc)`.
  - `check_doc(doc, method) -> None`: throws `ErasedPersonError` when `blocked_values(doc)`.
  - **Facebook:** when the mapped lead data's email or phone is blocked, skip silently. No insert and no Failed Lead Sync Log, since the log would store her data.
  - **WhatsApp:** when the incoming number is blocked, skip `_create_lead` and leave the message without a reference. The message is still saved.

- [ ] **Step 1: Write the failing tests**

```python
class TestBlocking(IntegrationTestCase):
	def setUp(self):
		add_do_not_contact("Email", "marisol@sierrafoothills.example", "PDR-0001")
		add_do_not_contact("Phone", "5305550142", "PDR-0001")

	def test_manual_lead_blocked_any_format(self):
		for kw in [{"email": "MARISOL@sierrafoothills.example"}, {"mobile_no": "(530) 555-0142"}]:
			with self.assertRaises(ErasedPersonError) as e:
				frappe.get_doc({"doctype": "CRM Lead", "first_name": "M", **kw}).insert()
			self.assertNotIn("530", str(e.exception))

	def test_contact_and_deal_row_blocked(self):
		with self.assertRaises(ErasedPersonError):
			create_test_contact(first_name="M", email="marisol@sierrafoothills.example")
		c = create_test_contact(first_name="Front desk", phone="530-555-0100")
		frappe.db.set_value("Contact", c.name, "mobile_no", "5305550142")   # pre-existing shared value
		with self.assertRaises(ErasedPersonError):
			create_test_deal(contacts=[{"contact": c.name}])

	def test_changing_existing_record_to_blocked_value(self):
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Other", "email": "o@x.example"}).insert()
		lead.email = "marisol@sierrafoothills.example"
		with self.assertRaises(ErasedPersonError):
			lead.save()

	def test_existing_record_saved_unchanged_not_blocked(self):
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Other", "mobile_no": "530-555-0100"}).insert()
		frappe.db.set_value("CRM Lead", lead.name, "phone", "5305550142")
		lead.reload(); lead.job_title = "CEO"; lead.save()

	def test_facebook_sync_skips_without_failure_log(self):
		before = frappe.db.count("Failed Lead Sync Log")
		run_facebook_sync_with({"email": "marisol@sierrafoothills.example", "first_name": "M"})
		self.assertEqual(frappe.db.count("Failed Lead Sync Log"), before)
		self.assertFalse(frappe.db.exists("CRM Lead", {"first_name": "M"}))
```

`run_facebook_sync_with(data)` is a test helper. It patches `FacebookSyncSource`'s field-mapping step to return `data` and calls `sync_single_lead`. Read `facebook.py:49-80` and patch the narrowest function that yields the lead dict.

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_blocking`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify pass**, then run `bench --site $SITE run-tests --app crm --module crm.fcrm.doctype.crm_deal.test_crm_deal`, `crm.tests.test_whatsapp` and `crm.tests.test_contact_deals`. All must still pass.
- [ ] **Step 5: Commit** — `feat: block re-creation of erased people on every creation path`

---

### Task 13: Inbound email routing

**Files:**
- Create: `crm/privacy/inbound.py`
- Modify:
  - `crm/hooks.py`: add `"before_insert": ["crm.privacy.inbound.route_inbound_email"]` to `Communication`, and append `"crm.privacy.inbound.notify_blocked_inbound"` to its `after_insert` list; add `"before_insert": ["crm.privacy.inbound.guard_inbound_lead"]` to `CRM Lead`.
  - `crm/utils/__init__.py`, `create_lead_from_incoming_email`: after the `_is_automated_email_sender` check (:269), add `if is_erasure_address(doc.sender): return`.
- Test: `crm/privacy/tests/test_inbound.py`

**Interfaces:**
- Produces:
  - `open_request_for_email(email: str) -> str | None`: the newest non-Closed request with a non-excluded identifier equal to `normalize_email(email)`.
  - `is_erasure_address(email: str) -> bool`: true for `open_request_for_email(email)` or `is_blocked("Email", email)`.
  - `route_inbound_email(doc, method) -> None`. It only acts when `doc.sent_or_received == "Received"` and `doc.communication_medium == "Email"`.
    - If there is an open request: set `reference_doctype="CRM Erasure Request"` and `reference_name=<it>`, and clear `timeline_links`.
    - Elif the sender is blocked: set the reference to None, clear `timeline_links`, and set `doc.flags.erasure_blocked_sender = True`.
  - `notify_blocked_inbound(doc, method) -> None` (Communication `after_insert`): when the flag is set, `frappe.db.after_commit.add` a call to `notify(compliance_users(), "An email arrived from a person whose data was erased. Decide what to do with it.", request=<the DNC row's request>, reference_doctype="Communication", reference_name=doc.name)`.
  - `guard_inbound_lead(doc, method) -> None`: raises `ErasedPersonError` when `doc.flags.ignore_mandatory` is set, `not frappe.flags.in_import`, and `open_request_for_email(doc.email)`. Frappe's inbound mail sets `ignore_mandatory` on the lead it creates. DNC addresses are already covered by `check_doc`.

- [ ] **Step 0: Confirm the framework behaviour.** In the bench, read `apps/frappe/frappe/email/inbound_mail.py` (`_create_reference_document`, `_build_communication_doc`) and `apps/frappe/frappe/contacts/doctype/contact/contact.py` (`get_contacts` auto-create). Confirm three things:
  - (a) the lead insert sets `flags.ignore_mandatory`;
  - (b) `DuplicateEntryError` is caught, and what `reference_name` results;
  - (c) contact auto-create failures are caught.

  If any of these is false, stop and report to the human before continuing. The design depends on them.
- [ ] **Step 1: Write the failing tests**

```python
class TestInbound(IntegrationTestCase):
	def test_open_request_receives_mail_and_no_lead(self):
		r = make_request(identifiers=[{"kind": "Email", "value": "marisol@sierrafoothills.example"}])
		c = make_communication(sender="Marisol@SierraFoothills.example", sent_or_received="Received",
			communication_medium="Email", email_account=make_email_account(create_lead_from_incoming_email=1))
		self.assertEqual(frappe.db.get_value("Communication", c, ["reference_doctype", "reference_name"]),
			("CRM Erasure Request", r.name))

	def test_inbound_style_lead_blocked_while_open(self):
		make_request(identifiers=[{"kind": "Email", "value": "marisol@sierrafoothills.example"}])
		lead = frappe.new_doc("CRM Lead"); lead.email = "marisol@sierrafoothills.example"
		lead.flags.ignore_mandatory = True
		with self.assertRaises(frappe.DuplicateEntryError):
			lead.insert(ignore_permissions=True)

	def test_after_close_mail_stored_unlinked_and_compliance_notified(self):
		officer = make_compliance_user()
		add_do_not_contact("Email", "marisol@sierrafoothills.example", "PDR-0001")
		c = make_communication(sender="marisol@sierrafoothills.example", sent_or_received="Received",
			communication_medium="Email", email_account=make_email_account(create_lead_from_incoming_email=1))
		self.assertTrue(frappe.db.exists("Communication", c))
		self.assertIsNone(frappe.db.get_value("Communication", c, "reference_name"))
		self.assertFalse(frappe.db.exists("CRM Lead", {"email": "marisol@sierrafoothills.example"}))
		frappe.db.after_commit.run()
		self.assertTrue(frappe.db.exists("CRM Notification", {"to_user": officer, "reference_name": c}))
```

Add `make_email_account(**fields)` to the factories: a non-enabled incoming Email Account with `email_id` `inbox@northpine.example`.

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_inbound`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify pass**, plus `--module crm.tests.test_email`.
- [ ] **Step 5: Commit** — `feat: route inbound email from erasure requesters and never create leads for them`

---

## Phase F — Lifecycle and reminders

### Task 14: Decline, close and wipe, retention purge, outcome template

**Files:**
- Create: `crm/privacy/lifecycle.py`
- Modify:
  - `crm/privacy/api.py`
  - `crm/privacy/install.py`: add `seed_outcome_template()` and call it from `after_migrate`
  - `crm/hooks.py`: add `"crm.privacy.lifecycle.purge_expired"` to `scheduler_events["daily"]`
- Test: `crm/privacy/tests/test_lifecycle.py`

**Interfaces:**
- Produces:
  - `api.decline_request(name: str, reason: str) -> dict`: Compliance; status in Logged / Awaiting Sign-off / On Hold; `reason.strip()` must be non-empty. Sets `Declined` and `decline_reason`.
  - `api.close_request(name: str, date_answered: str, outcome: str, denial_reason: str | None = None) -> dict`. Requirements:
    - the user is Compliance and the status is Erased or Declined;
    - `outcome` is in Completed / Partly completed / Denied; a Declined request allows only `Denied`;
    - `denial_reason` is required when the outcome is Denied (it defaults to `decline_reason`);
    - every checklist row is `done`;
    - `date_answered` is not before `date_received` and not in the future.

    It then calls `lifecycle.close(doc)`.
  - `lifecycle.close(doc) -> None`. It writes through `frappe.db` / child-table deletes only:
    - blanks `requester_name`, `other_names`, `original_message` and `contract_references`;
    - deletes all `identifiers` and `matches` rows;
    - sets each checklist `description` to `erased_content(name)`;
    - erases Communications referencing the request with `sweep.erase_communications(names, emails, phones, doc.name)`, taking the identifiers before deleting them;
    - sets Comment `content` on the request to C;
    - sets status `Closed`.
  - `lifecycle.purge_expired(today: date | None = None) -> None`: deletes Closed requests with `date_answered < add_months(today, -24)` (`frappe.delete_doc(..., ignore_permissions=True, delete_permanently=True)`), and CRM Retained Contract rows with `delete_after <= today`.
  - `install.seed_outcome_template() -> None`: creates the Email Template `Erasure outcome` (`enabled=1`, `reference_doctype="CRM Erasure Request"`) if it is missing, and never overwrites an existing one. Subject: `Your request to delete your personal information`. `response_html`:

```html
<p>Dear [name],</p>
<p>On [date received] you asked Northpine to delete the personal information we hold about you. We have completed our review.</p>
<p><strong>What we erased.</strong> We erased your contact details, your lead and deal records, emails, call records, notes and files from our CRM. [We also deleted copies held by our service providers: list them. / Copies held by our service providers were not affected: explain.]</p>
<p><strong>What we kept, and why.</strong> [Keep only what applies: Under the exception for signed contracts, we keep your name and the contract reference [reference] for [period]. / We did not erase [item] because [reason].]</p>
<p><strong>Our record of your request.</strong> As the law requires, we keep a record of this request for 24 months. It holds no contact details. We also keep a do-not-contact entry so your details are not added to our systems again.</p>
<p><strong>A known limitation.</strong> Passing mentions of you inside other people's records, for example a note on a deal, are not searched for or erased.</p>
<p>Sincerely,<br>[Compliance team member]</p>
```

- [ ] **Step 1: Write the failing tests**

```python
class TestLifecycle(IntegrationTestCase):
	def test_decline_requires_reason(self):
		officer = make_compliance_user(); r = make_request(); frappe.set_user(officer)
		with self.assertRaises(frappe.ValidationError):
			decline_request(r.name, "  ")
		self.assertEqual(decline_request(r.name, "Identity not verifiable")["status"], "Declined")

	def test_close_blocked_by_open_checklist(self):
		officer = make_compliance_user()
		r = make_request(checklist=[{"description": "Delete recordings at provider (Twilio)"}])
		frappe.db.set_value("CRM Erasure Request", r.name, "status", "Erased"); frappe.set_user(officer)
		with self.assertRaises(frappe.ValidationError):
			close_request(r.name, frappe.utils.today(), "Completed")

	def test_close_wipes_and_keeps_log_fields(self):
		officer = make_compliance_user()
		r = make_request(requester_name="Marisol Vega", original_message="Delete me", arrived_via="Email",
			date_received="2026-10-26", identifiers=[{"kind": "Email", "value": "marisol@sierrafoothills.example"}])
		c = make_communication(sender="marisol@sierrafoothills.example", reference=("CRM Erasure Request", r.name))
		frappe.db.set_value("CRM Erasure Request", r.name, "status", "Erased"); frappe.set_user(officer)
		close_request(r.name, "2026-11-20", "Completed")
		d = frappe.get_doc("CRM Erasure Request", r.name)
		self.assertEqual((d.requester_name, d.original_message, d.identifiers, d.matches), ("", "", [], []))
		self.assertEqual((str(d.date_received), d.request_type, d.arrived_via, str(d.date_answered), d.outcome, d.status),
			("2026-10-26", "Erasure", "Email", "2026-11-20", "Completed", "Closed"))
		self.assertEqual(frappe.db.get_value("Communication", c, "content"), f"Content erased {r.name}")

	def test_denied_needs_reason(self):
		officer = make_compliance_user(); r = make_request()
		frappe.db.set_value("CRM Erasure Request", r.name, "status", "Erased"); frappe.set_user(officer)
		with self.assertRaises(frappe.ValidationError):
			close_request(r.name, frappe.utils.today(), "Denied")

	def test_purge(self):
		r = make_request(date_received="2024-01-02")
		frappe.db.set_value("CRM Erasure Request", r.name, {"status": "Closed", "date_answered": "2024-01-10"})
		rc = frappe.get_doc({"doctype": "CRM Retained Contract", "person_name": "X", "delete_after": "2026-11-07"}).insert()
		purge_expired(getdate("2026-11-07"))
		self.assertFalse(frappe.db.exists("CRM Erasure Request", r.name))
		self.assertFalse(frappe.db.exists("CRM Retained Contract", rc.name))
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_name": r.name}))

	def test_outcome_template_seeded_once(self):
		seed_outcome_template()
		frappe.db.set_value("Email Template", "Erasure outcome", "subject", "Edited")
		seed_outcome_template()
		self.assertEqual(frappe.db.get_value("Email Template", "Erasure outcome", "subject"), "Edited")
```

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_lifecycle`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat: decline and close erasure requests, purge expired logs, seed outcome email template`

---

### Task 15: Daily reminders

**Files:**
- Modify:
  - `crm/privacy/reminders.py`
  - `crm/hooks.py`: add `"crm.privacy.reminders.send_reminders"` to `scheduler_events["daily"]`
- Test: `crm/privacy/tests/test_reminders.py`

**Interfaces:**
- Consumes: `reminder_dates`, `notify`, `compliance_users`.
- Produces: `send_reminders(today: date | None = None) -> None`. It runs for every request with status ≠ Closed:
  - **Acknowledgment:** if not `acknowledgment_sent`, not `ack_reminder_sent`, and `today >= dates["acknowledgment"]`, notify `compliance_users()` with `f"Erasure request {name}: acknowledge by {acknowledge_by}"`, then set the flag.
  - **Day 30:** if `today >= dates["day_30"]` and the flag isn't set, notify `compliance_users()` with `f"Erasure request {name}: {days_left} of 45 days left"`.
  - **Day 40:** if `today >= dates["day_40"]` and the flag isn't set, notify `[head_of_compliance]` with the same text. If `head_of_compliance` is not set, notify `compliance_users()` instead.
  - Each request is processed in its own try/except with `frappe.log_error(title=f"Erasure reminder failed for {name}")`, so one bad row doesn't stop the others.

- [ ] **Step 1: Write the failing tests**

```python
class TestReminders(IntegrationTestCase):
	def setUp(self):
		self.officer = make_compliance_user()
		self.r = make_request(date_received="2026-10-26")

	def count(self, user):
		return frappe.db.count("CRM Notification", {"to_user": user, "notification_type_doc": self.r.name})

	def test_ack_reminder_due_once(self):
		send_reminders(getdate("2026-11-03")); self.assertEqual(self.count(self.officer), 0)
		send_reminders(getdate("2026-11-04")); self.assertEqual(self.count(self.officer), 1)
		send_reminders(getdate("2026-11-05")); self.assertEqual(self.count(self.officer), 1)

	def test_ack_reminder_skipped_when_acknowledged(self):
		frappe.db.set_value("CRM Erasure Request", self.r.name, "acknowledgment_sent", 1)
		send_reminders(getdate("2026-11-04")); self.assertEqual(self.count(self.officer), 0)

	def test_late_logged_request_gets_all_due_reminders(self):
		head = make_user("head@example.com", ["Compliance"]).name
		frappe.db.set_single_value("CRM Privacy Settings", "head_of_compliance", head)
		send_reminders(getdate("2026-12-06"))
		self.assertEqual(self.count(self.officer), 2)   # acknowledgment + day 30
		self.assertEqual(self.count(head), 3)           # also a Compliance user, plus the day-40 alert

	def test_day40_falls_back_without_head(self):
		frappe.db.set_single_value("CRM Privacy Settings", "head_of_compliance", None)
		frappe.db.set_value("CRM Erasure Request", self.r.name, {"ack_reminder_sent": 1, "day30_reminder_sent": 1})
		send_reminders(getdate("2026-12-05")); self.assertEqual(self.count(self.officer), 1)

	def test_closed_requests_ignored(self):
		frappe.db.set_value("CRM Erasure Request", self.r.name, "status", "Closed")
		send_reminders(getdate("2026-12-06")); self.assertEqual(self.count(self.officer), 0)
```

- [ ] **Step 2: Run to verify failure** — `--module crm.privacy.tests.test_reminders`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `feat: send acknowledgment, day-30 and day-40 erasure reminders`

---

## Phase G — Frontend

### Task 16: Requests list and request page

**Files:**
- Create:
  - `frontend/src/utils/erasureRequest.js`
  - `frontend/src/pages/ErasureRequests.vue`
  - `frontend/src/pages/ErasureRequest.vue`
- Modify:
  - `frontend/src/router.js`: add `{ path: '/erasure-requests', name: 'Erasure Requests', component: () => import('@/pages/ErasureRequests.vue') }` and `{ path: '/erasure-requests/:requestId', name: 'Erasure Request', component: () => import('@/pages/ErasureRequest.vue'), props: true }`. Do **not** add them to the ViewControls lists at :222-231 / :241-250.
  - `frontend/src/utils/navigation.js`: append `{ label: 'Erasure requests', icon: LucideShieldOff, route: 'Erasure Requests' }`, importing `~icons/lucide/shield-off`.
  - `frontend/src/components/Notifications.vue` `getRoute`: when `route_name === 'Erasure Request'`, use params `{ requestId: notification.reference_name }`.
- Test: `frontend/tests/unit/erasureRequest.test.js`

**Interfaces:**
- Consumes: `crm.privacy.api.get_requests`, `get_request`, `save_request`, `refresh_request_matches`, `submit_request`, `decline_request`, `close_request` (Tasks 6, 7, 14), with the payload shapes defined there.
- Produces (`erasureRequest.js`):
  - `daysLeftLabel(daysLeft: number | null) -> string`:
    - `null` → `''`;
    - 0 or more → `` `${n} of 45 days left` ``;
    - negative → `` `Overdue by ${-n} days` ``, with singular "day" for 1.
  - `statusTheme(status: string) -> 'gray'|'orange'|'blue'|'green'|'red'`:
    - Logged → gray;
    - Awaiting Sign-off → blue;
    - On Hold → orange;
    - Erased and Closed → green;
    - Declined → red.
  - `confirmationMatches(typed: string, requestName: string) -> boolean`: `typed.trim() === requestName`, case-sensitive.
- **Page content:**
  - **List** (follow `Settings/EmailTemplate/EmailTemplatePage.vue`'s `createResource` + frappe-ui `ListView` pattern):
    - columns: request, requester (blank for summary rows), status badge, received, acknowledge by, days left label;
    - a "New request" button that calls `log_request` and routes to the result.
  - **Detail, summary access:** status badge, acknowledge-by and respond-by only.
  - **Detail, full access**, all of these sections, editable per `can`:
    - header: status, days left, deadlines;
    - requester details;
    - identifiers table, showing usage counts and an "Exclude" toggle;
    - matches table, with confirm checkboxes and links to records;
    - contract references (Compliance only);
    - checklist, with an add row and tick showing who and when;
    - acknowledgment checkbox and date;
    - attached emails.
  - **Detail, action buttons** (each shown per `can`): Submit, Approve (opens the Task 17 modal), Decline (dialog with reason), Close (dialog with date answered, outcome and denial reason).
  - **Detail, erasure state:** when `erasure_status` is `Queued`, show "Erasing…" and poll `get_request` every 3 s until it changes. When it is `Failed`, show `erasure_error` in an error banner.

- [ ] **Step 1: Write the failing test**

```js
import { describe, expect, it } from 'vitest'
import { confirmationMatches, daysLeftLabel, statusTheme } from '@/utils/erasureRequest'

describe('daysLeftLabel', () => {
  it('counts down', () => expect(daysLeftLabel(14)).toBe('14 of 45 days left'))
  it('shows zero', () => expect(daysLeftLabel(0)).toBe('0 of 45 days left'))
  it('shows overdue', () => {
    expect(daysLeftLabel(-1)).toBe('Overdue by 1 day')
    expect(daysLeftLabel(-3)).toBe('Overdue by 3 days')
  })
  it('is empty for closed', () => expect(daysLeftLabel(null)).toBe(''))
})

describe('statusTheme', () => {
  it('maps statuses', () => {
    expect(statusTheme('On Hold')).toBe('orange')
    expect(statusTheme('Declined')).toBe('red')
  })
})

describe('confirmationMatches', () => {
  it('requires the exact request number', () => {
    expect(confirmationMatches(' PDR-0001 ', 'PDR-0001')).toBe(true)
    expect(confirmationMatches('pdr-0001', 'PDR-0001')).toBe(false)
    expect(confirmationMatches('PDR-001', 'PDR-0001')).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify failure** — `cd frontend && yarn test:run tests/unit/erasureRequest.test.js`. Expected: FAIL, module not found.
- [ ] **Step 3: Implement the util, pages, routes, nav item and notification route.**
- [ ] **Step 4: Verify.** Run `yarn test:run`: all tests pass, including `navigation.test.js`'s unique-route check. Then run `yarn build`, which should succeed. Finally, in a running bench, log a request from the list, open it, confirm a match and submit. The rep should then see the summary view.
- [ ] **Step 5: Commit** — `feat: add erasure requests list and request page`

---

### Task 17: Approval modal, "Request erasure" entry points, Privacy settings tab

**Files:**
- Create:
  - `frontend/src/components/Privacy/ApproveErasureModal.vue`
  - `frontend/src/components/Privacy/RequestErasureButton.vue`
  - `frontend/src/components/Settings/PrivacySettings.vue`
- Modify:
  - `frontend/src/pages/ErasureRequest.vue`: wire the Approve button to the modal.
  - `Lead.vue`: put the button before the Convert button in `#right-header` (:39).
  - `Deal.vue`: after the status Dropdown (:10-39).
  - `Contact.vue`: before "New Deal" (:10-20).
  - `MobileLead.vue` (:39-67), `MobileDeal.vue` (:39-54), `MobileContact.vue` (:70-85).
  - `frontend/src/components/Settings/Settings.vue`: add a `Privacy` item in an existing group, with `condition: () => isAdmin()`.

**Interfaces:**
- Consumes: `get_erasure_preview`, `approve_request` and `log_request` (Tasks 6, 8, 9), and `confirmationMatches` (Task 16).
- Produces:
  - `<ApproveErasureModal v-model="show" :requestName="name" @approved="reload" />`. It renders the three preview sections:
    1. **Will be removed:** kind, count, record links.
    2. **Will be kept:** labels and links.
    3. **Warnings:** open checklist items and unlisted custom fields, shown in an amber callout.

    It also shows the line "This can't be undone." and a text input labelled `Type ${requestName} to confirm`. The red "Erase permanently" button is disabled until `confirmationMatches`. Server errors (wrong role, On Hold) show as toast messages. If the response status is On Hold, close the modal and show "The person is still on an open deal; the request is on hold."
  - `<RequestErasureButton :doctype="'CRM Lead'|'CRM Deal'|'Contact'" :docname="id" />`: a button labelled "Request erasure" (icon `lucide-shield-off`). On click it calls `log_request` and `router.push({ name: 'Erasure Request', params: { requestId } })`.
  - **PrivacySettings:** a `createDocumentResource` for `CRM Privacy Settings` (pattern: `DefaultsSettings.vue:154-173`), with:
    - Head of Compliance (user Link);
    - Contract retention period (months);
    - an editable personal fields table (document type select + fieldname), with add/remove rows and an explicit Save.

- [ ] **Step 1: Verify the shared util is reused.** The confirm button must be disabled via `confirmationMatches` (covered by the Task 16 tests). No new unit test.
- [ ] **Step 2: Verify in the browser** (bench running, `yarn dev` or `yarn build`):
  - (a) Click "Request erasure" on Marisol's lead page. You should land on a Logged request with the lead pre-confirmed.
  - (b) Approve as the logger: you get a permission toast.
  - (c) Approve as the Compliance user: the button stays disabled until `PDR-xxxx` is typed exactly; after confirming, the page shows "Erasing…" and then Erased.
  - (d) The Privacy settings tab is visible only to System Manager.
  - (e) Repeat (a) on desktop and on mobile width (<768px) for a deal and a contact.
- [ ] **Step 3: Run `cd frontend && yarn test:run && yarn build`.** Expected: all pass, and the build succeeds.
- [ ] **Step 4: Commit** — `feat: add erasure approval modal, request-erasure actions and privacy settings tab`

---

## Done when

- `bench --site $SITE run-tests --app crm` passes (the whole app, not only `crm.privacy`).
- `cd frontend && yarn test:run` passes.
- The browser walkthrough in Task 17 Step 2 succeeds end to end on Marisol's data.
- The dashboard shows the same numbers before and after.
