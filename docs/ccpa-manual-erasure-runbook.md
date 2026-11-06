# CCPA manual erasure runbook

<!-- Generated from crm/erasure/registry.py by crm.erasure.runbook. Do not edit by hand: run `bench --site <site> execute crm.erasure.runbook.write_runbook`. -->

## Before you start

- A **System Manager** runs every step, in `bench --site <site> console` or the Desk System Console.
  The Privacy team alone cannot: the steps touch Version, Deleted Document, `__global_search`,
  Email Queue and logs.
- Take a fresh backup (`bench --site <site> backup --with-files`) and keep it access-restricted.
  Her data stays in it until it rotates out.
- Book a maintenance window: nobody edits her records while the steps run.
- **Never paste her identifiers into tickets or chat.** Type them only into the console below.
  Tickets name the request number (`<REQ>` below) and nothing else.
- Statements are MariaDB. Every search is parameterised: `%(email)s` is one of her addresses,
  `%(phone_digits)s` the national digits of one of her numbers (no country code, digits only).
- A search is loose (a longer address that contains hers also hits): open each row it returns
  and drop the ones that are not hers from `found` before you change anything.
- A step may use names found by any earlier step. Steps 1 to 4 also feed each other (a deal
  leads to its lead): run their `find(...)` lines until no new name turns up, then
  `her_names = capture_her_names()` (the rename step needs them), and only then their changes.

Start the console with this helper, then run the steps in order:

```python
import json
emails = []        # her addresses, lower-case
phone_digits = []  # her numbers, national digits only
full_names = []    # her full names, lower-case (the final check only)
found = {}         # doctype -> names (or "<doctype>::<name>" keys) of her rows


def names(doctype):
	return tuple(found.get(doctype, ())) or ("",)


def keys(*doctypes):
	pairs = [(d, n) for d, ns in found.items() if not doctypes or d in doctypes for n in ns]
	return tuple(n if "::" in n else f"{d}::{n}" for d, n in pairs) or ("",)


def find(doctype, sql, params=None):
	runs = [{"email": e, "phone_digits": ""} for e in emails]
	runs += [{"email": "", "phone_digits": d} for d in phone_digits]
	hits = set(found.get(doctype, ()))
	for run in runs:
		hits.update(frappe.db.sql(sql, {**run, **(params or {})}, pluck=True))
	found[doctype] = sorted(hits)
	return found[doctype]


def capture_her_names():
	"""Her names as stored before anything is changed (the rename step needs them)"""
	sources = (('Contact', 'full_name'), ('CRM Lead', 'lead_name'), ('CRM Deal', 'lead_name'))
	return {v.strip() for d, f in sources for v in frappe.get_all(d, {"name": ("in", names(d))}, pluck=f) if v and v.strip()}
```

## Her records and activity

### 1. CRM Lead

**Where:** The request's source; email, mobile_no or phone is hers; the lead of one of her deals.

- Desk: `/app/crm-lead`, filter on `email`, `mobile_no`, `phone`.

**What to change:** Keep the record; change the fields below.

- `salutation`: clear it.
- `first_name`: set to `Erased <REQ>`.
- `middle_name`: clear it.
- `last_name`: clear it.
- `lead_name`: set to `Erased <REQ>`.
- `email`: clear it.
- `mobile_no`: clear it.
- `phone`: clear it.
- `gender`: clear it.
- `job_title`: clear it.
- `image`: clear it.
- `linkedin`: clear it.
- `twitter`: clear it.
- `facebook`: clear it.
- `facebook_lead_id`: clear it.
- `lost_notes`: set to `Content erased <REQ>`.

**Keep as they are:** `status`, `source`, `lead_owner`, `territory`, `organization`, `annual_revenue`, `total`, `net_total`, `converted`, `lost_reason`.

**Console:**

```python
find("CRM Lead", """
select `name` from `tabCRM Lead`
where (%(email)s <> '' and (locate(%(email)s, lower(`email`)) > 0))
   or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`mobile_no`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`phone`, '[^0-9]', '')) > 0))
   or `name` in (select `lead` from `tabCRM Deal` where `name` in %(crm_deal_names)s)
""", {"crm_deal_names": names('CRM Deal')})
for name in found["CRM Lead"]:
	frappe.db.set_value("CRM Lead", name, {"salutation": None, "first_name": 'Erased <REQ>', "middle_name": None, "last_name": None, "lead_name": 'Erased <REQ>', "email": None, "mobile_no": None, "phone": None, "gender": None, "job_title": None, "image": None, "linkedin": None, "twitter": None, "facebook": None, "facebook_lead_id": None, "lost_notes": 'Content erased <REQ>'}, update_modified=False)
```

### 2. CRM Deal

**Where:** Deals converted from her lead; deal contact is her Contact; email, mobile_no or phone is hers. A deal where she is only one of the contacts is not hers: only her contact row is scrubbed.

- Desk: `/app/crm-deal`, filter on `email`, `mobile_no`, `phone`.

**What to change:** Keep the record; change the fields below.

- `salutation`: clear it.
- `first_name`: set to `Erased <REQ>`.
- `last_name`: clear it.
- `lead_name`: set to `Erased <REQ>`.
- `email`: clear it.
- `mobile_no`: clear it.
- `phone`: clear it.
- `gender`: clear it.
- `job_title`: clear it.
- `lost_notes`: set to `Content erased <REQ>`.

**Keep as they are:** `status`, `deal_value`, `expected_deal_value`, `probability`, `expected_closure_date`, `closed_date`, `deal_owner`, `organization`, `lost_reason`.

**Console:**

```python
find("CRM Deal", """
select `name` from `tabCRM Deal`
where `lead` in %(crm_lead_names)s
   or `contact` in %(contact_names)s
   or (%(email)s <> '' and (locate(%(email)s, lower(`email`)) > 0))
   or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`mobile_no`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`phone`, '[^0-9]', '')) > 0))
""", {"crm_lead_names": names('CRM Lead'), "contact_names": names('Contact')})
for name in found["CRM Deal"]:
	frappe.db.set_value("CRM Deal", name, {"salutation": None, "first_name": 'Erased <REQ>', "last_name": None, "lead_name": 'Erased <REQ>', "email": None, "mobile_no": None, "phone": None, "gender": None, "job_title": None, "lost_notes": 'Content erased <REQ>'}, update_modified=False)
```

### 3. CRM Contacts

**Where:** Contact rows of any deal whose contact is her Contact, or whose email or phone is hers.

- Desk: `/app/crm-contacts`, filter on `email`, `mobile_no`, `phone`.

**What to change:** Keep the record; change the fields below.

- `full_name`: set to `Erased <REQ>`.
- `email`: clear it.
- `mobile_no`: clear it.
- `phone`: clear it.
- `gender`: clear it.

**Keep as they are:** `contact`, `is_primary`.

**Console:**

```python
find("CRM Contacts", """
select `name` from `tabCRM Contacts`
where `contact` in %(contact_names)s
   or (%(email)s <> '' and (locate(%(email)s, lower(`email`)) > 0))
   or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`mobile_no`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`phone`, '[^0-9]', '')) > 0))
""", {"contact_names": names('Contact')})
for name in found["CRM Contacts"]:
	frappe.db.set_value("CRM Contacts", name, {"full_name": 'Erased <REQ>', "email": None, "mobile_no": None, "phone": None, "gender": None}, update_modified=False)
```

### 4. Contact

**Where:** The request's source; email_id, phone or mobile_no is hers; any Contact Email or Contact Phone row is hers.

- Desk: `/app/contact`, filter on `email_id`, `phone`, `mobile_no`.
- Also its `Contact Email` rows: `email_id`.
- Also its `Contact Phone` rows: `phone`.

**What to change:** Keep the record; change the fields below.

- `salutation`: clear it.
- `first_name`: set to `Erased <REQ>`.
- `middle_name`: clear it.
- `last_name`: clear it.
- `full_name`: set to `Erased <REQ>`.
- `email_id`: clear it.
- `phone`: clear it.
- `mobile_no`: clear it.
- `image`: clear it.
- `gender`: clear it.
- `designation`: clear it.
- `department`: clear it.
- `user`: clear it.
- `google_contacts_id`: clear it.
- `email_ids`: delete all its child rows.
- `phone_nos`: delete all its child rows.

**Keep as they are:** `links`, `company_name`, `status`.

**Console:**

```python
find("Contact", """
select `name` from `tabContact`
where (%(email)s <> '' and (locate(%(email)s, lower(`email_id`)) > 0))
   or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`phone`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`mobile_no`, '[^0-9]', '')) > 0))
   or `name` in (select `parent` from `tabContact Email` where `parenttype` = 'Contact' and ((%(email)s <> '' and (locate(%(email)s, lower(`email_id`)) > 0))))
   or `name` in (select `parent` from `tabContact Phone` where `parenttype` = 'Contact' and ((%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`phone`, '[^0-9]', '')) > 0))))
""")
for name in found["Contact"]:
	frappe.db.set_value("Contact", name, {"salutation": None, "first_name": 'Erased <REQ>', "middle_name": None, "last_name": None, "full_name": 'Erased <REQ>', "email_id": None, "phone": None, "mobile_no": None, "image": None, "gender": None, "designation": None, "department": None, "user": None, "google_contacts_id": None}, update_modified=False)
	frappe.db.delete(frappe.get_meta("Contact").get_field("email_ids").options, {"parenttype": "Contact", "parent": name, "parentfield": "email_ids"})
	frappe.db.delete(frappe.get_meta("Contact").get_field("phone_nos").options, {"parenttype": "Contact", "parent": name, "parentfield": "phone_nos"})
```

### 5. Address

**Where:** Addresses whose links point at her Lead, Deal or Contact. Scrubbed when linked only to her, else her link is removed.

- Desk: `/app/address`.

**What to change:** Keep the record; change the fields below.

- `address_title`: set to `Erased <REQ>`.
- `address_line1`: set to `Content erased <REQ>`.
- `address_line2`: clear it.
- `city`: set to `Content erased <REQ>`.
- `county`: clear it.
- `state`: clear it.
- `pincode`: clear it.
- `email_id`: clear it.
- `phone`: clear it.
- `fax`: clear it.
- `links`: delete the link rows pointing at her Lead, Deal or Contact.
- When the record also links to records that are not hers: delete only her link rows, change nothing else.

**Keep as they are:** `address_type`, `country`.

**Console:**

```python
find("Address", """
select `name` from `tabAddress`
where `name` in (select `parent` from `tabDynamic Link` where `parenttype` = 'Address' and (concat(`link_doctype`, '::', `link_name`) in %(subject_keys)s))
""", {"subject_keys": keys('CRM Lead', 'CRM Deal', 'Contact')})
shared = []  # rows that also link to records that are not hers: fill in by hand
for name in found["Address"]:
	if name not in shared:
		frappe.db.set_value("Address", name, {"address_title": 'Erased <REQ>', "address_line1": 'Content erased <REQ>', "address_line2": None, "city": 'Content erased <REQ>', "county": None, "state": None, "pincode": None, "email_id": None, "phone": None, "fax": None}, update_modified=False)
	frappe.db.delete(frappe.get_meta("Address").get_field("links").options, {"parenttype": "Address", "parent": name, "parentfield": "links", "link_name": ("in", names("CRM Lead") + names("CRM Deal") + names("Contact"))})
```

### 6. Dynamic Link

**Where:** Link rows of any record whose link_name is her Lead, Deal or Contact (link_title caches her name).

- Desk: `/app/dynamic-link`.

**What to change:** Keep the record; change the fields below.

- `link_title`: set to `Erased <REQ>`.

**Keep as they are:** `link_doctype`, `link_name`.

**Console:**

```python
find("Dynamic Link", """
select `name` from `tabDynamic Link`
where concat(`link_doctype`, '::', `link_name`) in %(subject_keys)s
""", {"subject_keys": keys('CRM Lead', 'CRM Deal', 'Contact')})
for name in found["Dynamic Link"]:
	frappe.db.set_value("Dynamic Link", name, {"link_title": 'Erased <REQ>'}, update_modified=False)
```

### 7. Communication Link

**Where:** Timeline links of any Communication whose link_name is her Lead, Deal or Contact.

- Desk: `/app/communication-link`.

**What to change:** Keep the record; change the fields below.

- `link_title`: set to `Erased <REQ>`.

**Keep as they are:** `link_doctype`, `link_name`.

**Console:**

```python
find("Communication Link", """
select `name` from `tabCommunication Link`
where concat(`link_doctype`, '::', `link_name`) in %(subject_keys)s
""", {"subject_keys": keys('CRM Lead', 'CRM Deal', 'Contact')})
for name in found["Communication Link"]:
	frappe.db.set_value("Communication Link", name, {"link_title": 'Erased <REQ>'}, update_modified=False)
```

### 8. Communication

**Where:** Emails and SMS referencing or timeline-linked to her records; her address in sender, recipients, cc or bcc; phone_no is hers.

- Desk: `/app/communication`, filter on `sender`, `recipients`, `cc`, `bcc`, `phone_no`.

**What to change:** Keep the row (dashboards count it); replace its content as below.

- `subject`: set to `Content erased <REQ>`.
- `content`: set to `Content erased <REQ>`.
- `text_content`: set to `Content erased <REQ>`.
- `sender`: remove her addresses from the list, keep everyone else's; clear it when none is left.
- `sender_full_name`: clear it, only on rows where `sender` is hers.
- `recipients`: remove her addresses from the list, keep everyone else's; clear it when none is left.
- `cc`: remove her addresses from the list, keep everyone else's; clear it when none is left.
- `bcc`: remove her addresses from the list, keep everyone else's; clear it when none is left.
- `phone_no`: clear it, only on rows where `phone_no` is hers.

**Keep as they are:** `communication_type`, `communication_medium`, `sent_or_received`, `communication_date`, `status`.

**Console:**

```python
find("Communication", """
select `name` from `tabCommunication`
where concat(`reference_doctype`, '::', `reference_name`) in %(subject_keys)s
   or `name` in (select `parent` from `tabCommunication Link` where `parenttype` = 'Communication' and (concat(`link_doctype`, '::', `link_name`) in %(subject_keys)s))
   or (%(email)s <> '' and (locate(%(email)s, lower(`sender`)) > 0 or locate(%(email)s, lower(`recipients`)) > 0 or locate(%(email)s, lower(`cc`)) > 0 or locate(%(email)s, lower(`bcc`)) > 0))
   or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`phone_no`, '[^0-9]', '')) > 0))
""", {"subject_keys": keys('CRM Lead', 'CRM Deal', 'Contact')})
for name in found["Communication"]:
	frappe.db.set_value("Communication", name, {"subject": 'Content erased <REQ>', "content": 'Content erased <REQ>', "text_content": 'Content erased <REQ>'}, update_modified=False)
	# then, row by row, the fields above that depend on whose value it is
```

### 9. CRM Call Log

**Where:** Calls referencing or linked to her records; from or to is her number.

- Desk: `/app/crm-call-log`, filter on `from`, `to`.

**What to change:** Keep the record; change the fields below.

- `from`: set to `Erased <REQ>`, only on rows where `from` is hers.
- `to`: set to `Erased <REQ>`, only on rows where `to` is hers.
- `recording_url`: clear it.

**Keep as they are:** `duration`, `status`, `type`, `start_time`, `end_time`, `caller`, `receiver`.

**Console:**

```python
find("CRM Call Log", """
select `name` from `tabCRM Call Log`
where concat(`reference_doctype`, '::', `reference_docname`) in %(subject_keys)s
   or `name` in (select `parent` from `tabDynamic Link` where `parenttype` = 'CRM Call Log' and (concat(`link_doctype`, '::', `link_name`) in %(subject_keys)s))
   or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`from`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`to`, '[^0-9]', '')) > 0))
""", {"subject_keys": keys('CRM Lead', 'CRM Deal', 'Contact')})
for name in found["CRM Call Log"]:
	frappe.db.set_value("CRM Call Log", name, {"recording_url": None}, update_modified=False)
	# then, row by row, the fields above that depend on whose value it is
```

### 10. FCRM Note

**Where:** Notes referencing her records; the note of one of her calls.

- Desk: `/app/fcrm-note`.

**What to change:** Keep the row (dashboards count it); replace its content as below.

- `title`: set to `Content erased <REQ>`.
- `content`: set to `Content erased <REQ>`.

**Keep as they are:** `pinned`, `pinned_by`, `reference_doctype`, `reference_docname`.

**Console:**

```python
find("FCRM Note", """
select `name` from `tabFCRM Note`
where concat(`reference_doctype`, '::', `reference_docname`) in %(subject_keys)s
   or `name` in (select `note` from `tabCRM Call Log` where `name` in %(crm_call_log_names)s)
   or `name` in (select `link_name` from `tabDynamic Link` where `parenttype` = 'CRM Call Log' and `parent` in %(crm_call_log_names)s and `link_doctype` = 'FCRM Note')
""", {"subject_keys": keys('CRM Lead', 'CRM Deal', 'Contact'), "crm_call_log_names": names('CRM Call Log')})
for name in found["FCRM Note"]:
	frappe.db.set_value("FCRM Note", name, {"title": 'Content erased <REQ>', "content": 'Content erased <REQ>'}, update_modified=False)
```

### 11. CRM Task

**Where:** Tasks referencing her records or linked to one of her calls.

- Desk: `/app/crm-task`.

**What to change:** Keep the row (dashboards count it); replace its content as below.

- `title`: set to `Content erased <REQ>`.
- `description`: set to `Content erased <REQ>`.

**Keep as they are:** `status`, `priority`, `due_date`, `assigned_to`.

**Console:**

```python
find("CRM Task", """
select `name` from `tabCRM Task`
where concat(`reference_doctype`, '::', `reference_docname`) in %(subject_keys)s
   or `name` in (select `link_name` from `tabDynamic Link` where `parenttype` = 'CRM Call Log' and `parent` in %(crm_call_log_names)s and `link_doctype` = 'CRM Task')
""", {"subject_keys": keys('CRM Lead', 'CRM Deal', 'Contact'), "crm_call_log_names": names('CRM Call Log')})
for name in found["CRM Task"]:
	frappe.db.set_value("CRM Task", name, {"title": 'Content erased <REQ>', "description": 'Content erased <REQ>'}, update_modified=False)
```

### 12. WA Profile

**Where:** WhatsApp profiles whose phone_number or wa_id is her number, or linked to her records.

- Only when the `whatsapp` app is installed; skip this step otherwise.
- Desk: `/app/wa-profile`, filter on `phone_number`, `wa_id`.

**What to change:** Keep the record; change the fields below.

- `phone_number`: set to `Erased <REQ>`.
- `wa_id`: clear it.
- `profile_name`: set to `Erased <REQ>`.
- `links`: delete the link rows pointing at her Lead, Deal or Contact.

**Keep as they are:** `whatsapp_account`, `status`, `message_count`, `last_message_at`.

**Console:**

```python
find("WA Profile", """
select `name` from `tabWA Profile`
where (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`phone_number`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`wa_id`, '[^0-9]', '')) > 0))
   or `name` in (select `parent` from `tabDynamic Link` where `parenttype` = 'WA Profile' and (concat(`link_doctype`, '::', `link_name`) in %(subject_keys)s))
""", {"subject_keys": keys('CRM Lead', 'CRM Deal', 'Contact')})
for name in found["WA Profile"]:
	frappe.db.set_value("WA Profile", name, {"phone_number": 'Erased <REQ>', "wa_id": None, "profile_name": 'Erased <REQ>'}, update_modified=False)
	frappe.db.delete(frappe.get_meta("WA Profile").get_field("links").options, {"parenttype": "WA Profile", "parent": name, "parentfield": "links", "link_name": ("in", names("CRM Lead") + names("CRM Deal") + names("Contact"))})
```

### 13. WA Message

**Where:** WhatsApp messages to one of her profiles or referencing her records; from is her number.

- Only when the `whatsapp` app is installed; skip this step otherwise.
- Desk: `/app/wa-message`, filter on `from`.

**What to change:** Keep the row (dashboards count it); replace its content as below.

- `message`: set to `Content erased <REQ>`.
- `reaction`: clear it.
- `template_body_parameters`: clear it.
- `template_header_parameters`: clear it.
- `interactive_buttons`: delete all its child rows.
- `interactive_list_items`: delete all its child rows.
- `media_url`: clear it.
- `media_id`: clear it.
- `attach`: clear it.
- `from`: clear it, only on rows where `from` is hers.

**Keep as they are:** `direction`, `status`, `timestamp`, `whatsapp_account`, `to`, `message_id`.

**Console:**

```python
find("WA Message", """
select `name` from `tabWA Message`
where `to` in %(wa_profile_names)s
   or concat(`reference_doctype`, '::', `reference_docname`) in %(subject_keys)s
   or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`from`, '[^0-9]', '')) > 0))
""", {"wa_profile_names": names('WA Profile'), "subject_keys": keys('CRM Lead', 'CRM Deal', 'Contact')})
for name in found["WA Message"]:
	frappe.db.set_value("WA Message", name, {"message": 'Content erased <REQ>', "reaction": None, "template_body_parameters": None, "template_header_parameters": None, "media_url": None, "media_id": None, "attach": None}, update_modified=False)
	frappe.db.delete(frappe.get_meta("WA Message").get_field("interactive_buttons").options, {"parenttype": "WA Message", "parent": name, "parentfield": "interactive_buttons"})
	frappe.db.delete(frappe.get_meta("WA Message").get_field("interactive_list_items").options, {"parenttype": "WA Message", "parent": name, "parentfield": "interactive_list_items"})
	# then, row by row, the fields above that depend on whose value it is
```

### 14. Comment

**Where:** Comments on her records or on any of her activity; comment_email is hers.

- Desk: `/app/comment`, filter on `comment_email`.

**What to change:** Keep the row (dashboards count it); replace its content as below.

- `content`: set to `Content erased <REQ>`.
- `subject`: set to `Content erased <REQ>`.
- `comment_email`: clear it, only on rows where `comment_email` is hers.
- `comment_by`: clear it, only on rows where `comment_email` is hers.
- `ip_address`: clear it, only on rows where `comment_email` is hers.

**Keep as they are:** `comment_type`, `reference_doctype`, `reference_name`.

**Console:**

```python
find("Comment", """
select `name` from `tabComment`
where concat(`reference_doctype`, '::', `reference_name`) in %(match_keys)s
   or (%(email)s <> '' and (locate(%(email)s, lower(`comment_email`)) > 0))
""", {"match_keys": keys()})
for name in found["Comment"]:
	frappe.db.set_value("Comment", name, {"content": 'Content erased <REQ>', "subject": 'Content erased <REQ>'}, update_modified=False)
	# then, row by row, the fields above that depend on whose value it is
```

### 15. ToDo

**Where:** ToDos (assignments) on her records or on her CRM Tasks.

- Desk: `/app/todo`.

**What to change:** Keep the row (dashboards count it); replace its content as below.

- `description`: set to `Content erased <REQ>`.

**Keep as they are:** `status`, `allocated_to`, `date`, `reference_type`, `reference_name`.

**Console:**

```python
find("ToDo", """
select `name` from `tabToDo`
where concat(`reference_type`, '::', `reference_name`) in %(crm_lead_crm_deal_contact_crm_task_keys)s
""", {"crm_lead_crm_deal_contact_crm_task_keys": keys('CRM Lead', 'CRM Deal', 'Contact', 'CRM Task')})
for name in found["ToDo"]:
	frappe.db.set_value("ToDo", name, {"description": 'Content erased <REQ>'}, update_modified=False)
```

### 16. CRM Notification

**Where:** CRM notifications whose reference, notification document or comment is a match.

- Desk: `/app/crm-notification`.

**What to change:** Keep the row (dashboards count it); replace its content as below.

- `message`: set to `Content erased <REQ>`.
- `notification_text`: set to `Content erased <REQ>`.

**Keep as they are:** `type`, `to_user`, `from_user`, `read`.

**Console:**

```python
find("CRM Notification", """
select `name` from `tabCRM Notification`
where concat(`reference_doctype`, '::', `reference_name`) in %(match_keys)s
   or concat(`notification_type_doctype`, '::', `notification_type_doc`) in %(match_keys)s
   or `comment` in %(comment_names)s
""", {"match_keys": keys(), "comment_names": names('Comment')})
for name in found["CRM Notification"]:
	frappe.db.set_value("CRM Notification", name, {"message": 'Content erased <REQ>', "notification_text": 'Content erased <REQ>'}, update_modified=False)
```

### 17. Notification Log

**Where:** Desk notifications whose document is a match.

- Desk: `/app/notification-log`.

**What to change:** Keep the row (dashboards count it); replace its content as below.

- `title`: set to `Content erased <REQ>`.
- `subject`: set to `Content erased <REQ>`.
- `description`: set to `Content erased <REQ>`.
- `email_content`: set to `Content erased <REQ>`.

**Keep as they are:** `type`, `for_user`, `read`, `document_type`, `document_name`.

**Console:**

```python
find("Notification Log", """
select `name` from `tabNotification Log`
where concat(`document_type`, '::', `document_name`) in %(match_keys)s
""", {"match_keys": keys()})
for name in found["Notification Log"]:
	frappe.db.set_value("Notification Log", name, {"title": 'Content erased <REQ>', "subject": 'Content erased <REQ>', "description": 'Content erased <REQ>', "email_content": 'Content erased <REQ>'}, update_modified=False)
```

### 18. File

**Where:** File rows attached to any match (her lead or contact image is the File row attached to that record). The row is deleted; the file on disk only after commit and only when no File row outside her matches shares its file_url (uploads are deduplicated by content).

- Desk: `/app/file`.

**What to change:** Delete the row without a Deleted Document copy.

- Note each row's full path first: `frappe.get_doc("File", name).get_full_path()`.
- Delete the row raw, never with `delete_doc` (its `on_trash` adds an "Attachment Removed" comment naming the file).
- After `frappe.db.commit()`, delete the file on disk only when no other File row has the same `file_url`.
- With the feature installed the job does the same (rows in the transaction, disk files after the commit); disk files it could not delete are retried, also once the request is Closed, with `bench --site <site> execute crm.erasure.post_commit.finish_files --kwargs "{'name': 'CRM-ERQ-...'}"`.

**Console:**

```python
find("File", """
select `name` from `tabFile`
where concat(`attached_to_doctype`, '::', `attached_to_name`) in %(match_keys)s
""", {"match_keys": keys()})
frappe.db.delete("File", {"name": ("in", found["File"])})
```

## Hidden copies

### 19. Version

**Where:** Change history of any match, or whose data mentions her identifiers. Purged; rows of CRM Deal and of records that are not matches are filtered (entries naming her fields or identifiers dropped).

- Desk: `/app/version`, filter on `data`.

**What to change:** Delete the rows.

- Rows of CRM Deal are filtered, not deleted (below).
- Versions found only by their `data` (not of a record found above) are filtered too. Filtering: edit `data`, dropping every change of a field listed in the sections above and every entry naming her identifiers; delete the Version when nothing is left. A Version whose `data` is not valid JSON is never deleted as empty: look at it by hand (the product keeps it and counts it under `skipped` in the outcome).

**Console:**

```python
find("Version", """
select `name` from `tabVersion`
where concat(`ref_doctype`, '::', `docname`) in %(match_keys)s
   or (%(email)s <> '' and (locate(%(email)s, lower(`data`)) > 0)) or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`data`, '[^0-9]', '')) > 0))
""", {"match_keys": keys()})
for name in found["Version"]:
	ref = frappe.db.get_value("Version", name, ["ref_doctype", "docname"], as_dict=True)
	if ref.ref_doctype in ('CRM Deal',) or f"{ref.ref_doctype}::{ref.docname}" not in keys():
		continue  # filter its `data` by hand (above)
	frappe.db.delete("Version", name)
```

### 20. Deleted Document

**Where:** Copies of deleted records whose data mentions her identifiers.

- Desk: `/app/deleted-document`, filter on `data`.

**What to change:** Delete the rows.

**Console:**

```python
find("Deleted Document", """
select `name` from `tabDeleted Document`
where (%(email)s <> '' and (locate(%(email)s, lower(`data`)) > 0)) or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`data`, '[^0-9]', '')) > 0))
""")
frappe.db.delete("Deleted Document", {"name": ("in", found["Deleted Document"])})
```

### 21. __global_search

**Where:** Search index rows of any match, or whose content mentions her identifiers. Deleted, then re-indexed.

- Not a DocType: console only.

**What to change:** Delete the rows.

- Afterwards re-index each record found above: `update_global_search(frappe.get_doc(doctype, name))` per record, then `sync_global_search()` (both from `frappe.utils.global_search`).

**Console:**

```python
find("__global_search", """
select concat(`doctype`, '::', `name`) from `__global_search`
where concat(`doctype`, '::', `name`) in %(match_keys)s
   or (%(email)s <> '' and (locate(%(email)s, lower(`content`)) > 0)) or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`content`, '[^0-9]', '')) > 0))
""", {"match_keys": keys()})
frappe.db.sql("delete from `__global_search` where concat(`doctype`, '::', `name`) in %(keys)s", {"keys": tuple(found["__global_search"]) or ("",)})
```

### 22. Email Queue

**Where:** Queued emails to her address, or referencing a match or one of her Communications (with recipients).

- Desk: `/app/email-queue`.
- Also its `Email Queue Recipient` rows: `recipient`.

**What to change:** Delete the rows.

- Delete their Email Queue Recipient rows first (below).

**Console:**

```python
find("Email Queue", """
select `name` from `tabEmail Queue`
where concat(`reference_doctype`, '::', `reference_name`) in %(match_keys)s
   or `communication` in %(communication_names)s
   or `name` in (select `parent` from `tabEmail Queue Recipient` where `parenttype` = 'Email Queue' and ((%(email)s <> '' and (locate(%(email)s, lower(`recipient`)) > 0))))
   or (%(email)s <> '' and (locate(%(email)s, lower(`message`)) > 0)) or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`message`, '[^0-9]', '')) > 0))
""", {"match_keys": keys(), "communication_names": names('Communication')})
frappe.db.delete("Email Queue Recipient", {"parenttype": "Email Queue", "parent": ("in", found["Email Queue"])})
frappe.db.delete("Email Queue", {"name": ("in", found["Email Queue"])})
```

### 23. WA Log

**Where:** WhatsApp webhook logs referencing a match, or whose payload or message mentions her identifiers.

- Only when the `whatsapp` app is installed; skip this step otherwise.
- Desk: `/app/wa-log`, filter on `message`, `request_data`, `response_data`, `traceback`.

**What to change:** Delete the rows.

**Console:**

```python
find("WA Log", """
select `name` from `tabWA Log`
where concat(`reference_doctype`, '::', `reference_docname`) in %(match_keys)s
   or (%(email)s <> '' and (locate(%(email)s, lower(`message`)) > 0 or locate(%(email)s, lower(`request_data`)) > 0 or locate(%(email)s, lower(`response_data`)) > 0 or locate(%(email)s, lower(`traceback`)) > 0)) or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`message`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`request_data`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`response_data`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`traceback`, '[^0-9]', '')) > 0))
""", {"match_keys": keys()})
frappe.db.delete("WA Log", {"name": ("in", found["WA Log"])})
```

### 24. Error Log

**Where:** Error logs referencing a match, or whose error text mentions her identifiers.

- Desk: `/app/error-log`, filter on `error`, `method`.

**What to change:** Delete the rows.

**Console:**

```python
find("Error Log", """
select `name` from `tabError Log`
where concat(`reference_doctype`, '::', `reference_name`) in %(match_keys)s
   or (%(email)s <> '' and (locate(%(email)s, lower(`error`)) > 0 or locate(%(email)s, lower(`method`)) > 0)) or (%(phone_digits)s <> '' and (locate(%(phone_digits)s, regexp_replace(`error`, '[^0-9]', '')) > 0 or locate(%(phone_digits)s, regexp_replace(`method`, '[^0-9]', '')) > 0))
""", {"match_keys": keys()})
frappe.db.delete("Error Log", {"name": ("in", found["Error Log"])})
```

### 25. _comments

**Where:** The _comments cache column of her Lead, Deal and Contact rows, rewritten to name-only entries.

- Not a DocType: console only.

**What to change:** Rewrite the column, keeping only the `name` of each cached comment.

**Console:**

```python
# her records found above, and the records her Comments and Communications sit on
targets = {tuple(key.split("::", 1)) for key in keys()}
for doctype in ("Comment", "Communication"):
	rows = frappe.get_all(doctype, {"name": ("in", names(doctype))}, ["reference_doctype", "reference_name"])
	targets |= {(r.reference_doctype, r.reference_name) for r in rows if r.reference_name}
for doctype, name in sorted(targets):
	if frappe.get_meta(doctype).istable or doctype == "CRM Erasure Request":
		continue
	stored = frappe.db.get_value(doctype, name, "_comments")
	if stored:
		kept = [{"name": e["name"]} for e in json.loads(stored) if isinstance(e, dict) and e.get("name")]
		frappe.db.set_value(doctype, name, "_comments", json.dumps(kept), update_modified=False)
```

## Rename records named after her

The product does this last, after the hidden copies. Contact and Address IDs are often made of
her name ("<first> <last>", "<title>-Billing"). Rename, via Desk Rename (never merge):

- every Contact and Address in `found` that was scrubbed;
- a shared Address (only her link was removed) only when titled after her: its `address_title`
  is one of `her_names`, or its ID is one of them or starts with "<name>-". Set its
  `address_title` to `Erased <REQ>` first.

The new ID is `Erased <REQ>`, or `Erased <REQ>-1`, `Erased <REQ>-2`, ... when that is taken. Skip records
already named so. Desk refuses the rename while an erasure request for her is open in the CRM:
then run the product's job instead. After each rename, clean what the rename left behind and
replace the old ID in `found`:

```python
# doctype ("Contact" or "Address"), old and new: the IDs of one renamed record
comments = frappe.get_all("Comment", {"reference_doctype": doctype, "reference_name": new,
	"comment_type": "Edit", "content": ("like", f"%{old}%")}, pluck="name")  # "renamed from <old> to <new>"
frappe.db.delete("Version", {"ref_doctype": "Comment", "docname": ("in", comments or [""])})
frappe.db.delete("Comment", {"name": ("in", comments or [""])})


def swap(value):
	if isinstance(value, dict):
		return {k: swap(v) for k, v in value.items()}
	if isinstance(value, list):
		return [swap(v) for v in value]
	return new if value == old else value


for version, data in frappe.db.sql("select name, data from `tabVersion` where data like %s", (f"%{old}%",)):
	fixed = swap(json.loads(data or "{}"))
	if fixed != json.loads(data or "{}"):  # Version values holding the old ID (a deal's `contact`)
		frappe.db.set_value("Version", version, "data", frappe.as_json(fixed), update_modified=False)
frappe.db.delete("__global_search", {"doctype": doctype, "name": old})
base, _dash, suffix = old.rpartition("-")
for stem in {f"{old}-", *([f"{base}-"] if base and suffix.isdigit() else [])}:  # naming-series counters
	if not frappe.db.exists(doctype, {"name": ("like", f"{stem}%")}):
		frappe.db.sql("delete from `tabSeries` where name = %s", (stem,))
```

## Verify: nothing of hers is left

With the feature installed, run the same check the product runs:

```
bench --site <site> execute crm.erasure.verify.full_scan_request --kwargs "{'name': 'CRM-ERQ-...'}"
```

For a manual run, the console runs the conditions `full_scan` runs (`verify.column_conditions`) on
every text column of every table but the request's own: each address (whole address only), each
number (digits only) and, as an extra check, her full name. First the conditions (`{column}` is
filled in per column):

```python
EMAIL_SQL = '((lower(`{column}`) like %s and lower(`{column}`) regexp %s) or (lower(`{column}`) like %s and lower(`{column}`) regexp %s) or (lower(`{column}`) like %s and lower(`{column}`) regexp %s))'
DIGITS_SQL = "(regexp_replace(`{column}`, '[^0-9]', '') like %s)"
TOKEN_SQL = '(lower(`{column}`) like %s)'
```

then the search:

```python
import re
BEFORE, AFTER = "(?<![\\w!#$%&*+/=?^`{|}~.-])(?<!\\w')", '(?![\\w-]|\\.[\\w-])'
ENCODINGS, ENCODED_BEFORE = ('%40', '&#64;'), "(?<![\\w.%+'-])"  # '@' written as %40 or &#64;


def like(value):
	return "%" + value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def email_values(email):
	spellings = [(email, BEFORE)] + [(email.replace("@", c), ENCODED_BEFORE) for c in ENCODINGS]
	return [v for spelling, before in spellings for v in (like(spelling), before + re.escape(spelling) + AFTER)]


searches = [(EMAIL_SQL, email_values(e)) for e in emails]
searches += [(DIGITS_SQL, ["%" + d + "%"]) for d in phone_digits]
searches += [(TOKEN_SQL, [like(n)]) for n in full_names]
columns = frappe.db.sql(
	"select table_name, column_name from information_schema.columns "
	"where table_schema = database() and lower(data_type) in %(types)s and table_name not in %(skip)s "
	"and table_name in (select table_name from information_schema.tables "
	"where table_schema = database() and table_type = 'BASE TABLE')",
	{"types": ('char', 'varchar', 'tinytext', 'text', 'mediumtext', 'longtext', 'json', 'character', 'character varying', 'jsonb'), "skip": ('tabCRM Erasure Request', 'tabCRM Erasure Identifier', 'tabCRM Erasure Match')},
)
left = set()
for table, column in columns:
	for condition, values in searches:
		if frappe.db.sql(f"select 1 from `{table}` where {condition.format(column=column)} limit 1", values):
			left.add(table)
print(sorted(left))
```

It must print `[]`. A table listed only because of rows you
deliberately kept (a record that is not hers, or a namesake that only shares her name) passes; any
other table means a step was missed: fix it and run the check again. Then `frappe.db.commit()`, and
only then delete the File paths you noted from disk.

## Known limitations

- Database backups and binary logs keep her data until they rotate out (backups are out of scope).
- Emails already delivered to mailboxes outside the CRM and WhatsApp chats on phones cannot be recalled.
- Her name alone never matches: a record that mentions only her name, with no link to her records and none of her emails or phones, is not found.
- Text that spells an identifier unusually (an address split across lines, a number written in words with more than three separators between digit groups, or with its last four digits split) is not found by discovery.
- Files are matched by what they are attached to, not by their content. A file on disk shared with a record that is not hers (uploads are deduplicated by content) is kept; only her File rows go.
- A phone identifier without an extension matches that number with any extension (a colleague on the same switchboard number); give the extension when the number is shared.
- An Email Queue row is purged whole when any of its recipients is hers, including the copies queued for other recipients of the same email.
- Copies held by other systems (ERPNext customer sync, the telephony provider's recordings, the email provider) are not erased by the CRM.
- The final residual check reads phone numbers as digits only, so unrelated digits that happen to run together into her number in a long text block stop the erasure with an error naming the table; it needs a manual look before the job is run again.
- If an erasure run fails and is rolled back, the Error Log rows it purged stay deleted (that table does not take part in transactions); search index rows are rebuilt.
- A Lead, Deal or Contact form left open during the erasure is told to reload, but saving it without reloading writes the old values back; run the erasure again after such a save.
- Queued email bodies encoded as base64 (attachments, some HTML mail) are not read for her address; queued mail to her or about her records is purged by recipient and reference.
- Renaming her Contact and Address away from her name clears the site cache once, so the CRM is a little slower for a moment after the erasure.
