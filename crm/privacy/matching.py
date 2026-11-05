"""Finding the records that belong to an erasure requester, and holding the request while
she is a contact on an open deal (spec 5.2, 5.3).

`suggest_matches` and `refresh_identifiers` change the request in memory and leave saving
to the caller, so one save carries the logger's other edits as well.
"""

import frappe
from frappe import _
from pypika import Criterion
from pypika.functions import Function

from crm.privacy import personal_fields, system_write
from crm.privacy.identifiers import extract_emails, normalize, normalize_email
from crm.privacy.notify import notify
from crm.utils import normalize_phone, phone_search_digits

REQUEST = "CRM Erasure Request"
OPEN_DEAL_TYPES = ("Open", "Ongoing", "On Hold")

EMAIL_FIELDS = ("email", "email_id")
PHONE_FIELDS = ("mobile_no", "phone")

# Where each record type keeps personal emails and phones:
# (table, column holding the record's name, parenttype, doctype the personal-fields list
# is keyed by, columns to look in).
SOURCES = {
	"CRM Lead": [("CRM Lead", "name", None, "CRM Lead", ("email", "mobile_no", "phone"))],
	"CRM Deal": [
		("CRM Deal", "name", None, "CRM Deal", ("email", "mobile_no", "phone")),
		("CRM Contacts", "parent", "CRM Deal", "CRM Contacts", ("email", "mobile_no", "phone")),
	],
	"Contact": [
		("Contact", "name", None, "Contact", ("email_id", "mobile_no", "phone")),
		("Contact Email", "parent", "Contact", "Contact", ("email_id",)),
		("Contact Phone", "parent", "Contact", "Contact", ("phone",)),
	],
}


# -- Reading a request -------------------------------------------------------------------


def confirmed(request, doctype: str) -> list[str]:
	"""Names of the confirmed matches of `doctype`."""
	return [
		row.reference_name
		for row in request.matches
		if row.confirmed and row.reference_doctype == doctype and row.reference_name
	]


def active_identifiers(request, kind: str) -> list[str]:
	"""Normalized, non-excluded identifiers of `kind` ("Email" or "Phone"), without repeats."""
	values = []
	for row in request.identifiers:
		if row.kind != kind or row.excluded:
			continue
		value = normalize(kind, row.value)
		if value and value not in values:
			values.append(value)
	return values


# -- Finding records ---------------------------------------------------------------------


def _wildcard_digits(phone: str) -> str | None:
	"""LIKE pattern that matches a phone number however it is punctuated: the digits in
	order with anything between them. A superset of the real matches, so every hit is
	compared again after normalizing."""
	digits = phone_search_digits(phone)
	if not digits:
		return None
	return "%" + "%".join(digits) + "%"


def _lower(column):
	return Function("LOWER", Function("TRIM", column))


def _scan(table, name_column, parenttype, columns, emails, phones) -> set[str]:
	"""Names of the parent records of `table` rows whose `columns` hold one of the
	normalized `emails` or `phones`."""
	email_columns = [c for c in columns if c in EMAIL_FIELDS]
	phone_columns = [c for c in columns if c in PHONE_FIELDS]
	table_ = frappe.qb.DocType(table)

	conditions = []
	if emails:
		conditions += [_lower(table_[c]).isin(emails) for c in email_columns]
	if phones:
		patterns = [pattern for pattern in map(_wildcard_digits, phones) if pattern]
		conditions += [table_[c].like(pattern) for c in phone_columns for pattern in patterns]
	if not conditions:
		return set()

	query = (
		frappe.qb.from_(table_)
		.select(table_[name_column].as_("record"), *[table_[c] for c in columns])
		.where(Criterion.any(conditions))
	)
	if parenttype:
		query = query.where(table_.parenttype == parenttype)

	email_set, phone_set = set(emails), set(phones)
	found = set()
	for row in query.run(as_dict=True):
		if any(normalize_email(row[c]) in email_set for c in email_columns) or any(
			normalize_phone(row[c]) in phone_set for c in phone_columns
		):
			found.add(row.record)
	return found


def records_matching(doctype: str, emails: list[str], phones: list[str]) -> set[str]:
	"""Names of the `doctype` records (CRM Lead, CRM Deal or Contact) whose personal-field
	emails or phones equal one of the given normalized values."""
	found = set()
	for table, name_column, parenttype, personal_doctype, columns in SOURCES[doctype]:
		allowed = personal_fields(personal_doctype)
		columns = [c for c in columns if c in allowed]
		found |= _scan(table, name_column, parenttype, columns, emails, phones)
	return found


def communications_matching(emails: list[str], phones: list[str]) -> set[str]:
	"""Names of the Communications that name one of the emails in sender, recipients, cc or
	bcc (any case, any display name), or carry one of the phones."""
	headers = ("sender", "recipients", "cc", "bcc")
	table = frappe.qb.DocType("Communication")

	conditions = [_lower(table[c]).like(f"%{email}%") for email in emails for c in headers]
	patterns = [pattern for pattern in map(_wildcard_digits, phones) if pattern]
	conditions += [table.phone_no.like(pattern) for pattern in patterns]
	if not conditions:
		return set()

	query = (
		frappe.qb.from_(table)
		.select(table.name, table.phone_no, *[table[c] for c in headers])
		.where(Criterion.any(conditions))
	)
	email_set, phone_set = set(emails), set(phones)
	found = set()
	for row in query.run(as_dict=True):
		if any(email_set.intersection(extract_emails(row[c])) for c in headers) or (
			row.phone_no and normalize_phone(row.phone_no) in phone_set
		):
			found.add(row.name)
	return found


def call_logs_matching(phones: list[str]) -> set[str]:
	"""Names of the CRM Call Logs made from or to one of the phones."""
	patterns = [pattern for pattern in map(_wildcard_digits, phones) if pattern]
	if not patterns:
		return set()
	table = frappe.qb.DocType("CRM Call Log")
	query = (
		frappe.qb.from_(table)
		.select(table.name, table["from"], table["to"])
		.where(Criterion.any([table[c].like(pattern) for c in ("from", "to") for pattern in patterns]))
	)
	phone_set = set(phones)
	return {
		row.name
		for row in query.run(as_dict=True)
		if normalize_phone(row["from"]) in phone_set or normalize_phone(row["to"]) in phone_set
	}


def _match_count(kind: str, value: str) -> int:
	"""How many leads, contacts, deals, Communications and call logs contain the normalized
	identifier."""
	emails, phones = ([value], []) if kind == "Email" else ([], [value])
	count = sum(len(records_matching(doctype, emails, phones)) for doctype in SOURCES)
	count += len(communications_matching(emails, phones))
	if kind == "Phone":
		count += len(call_logs_matching(phones))
	return count


# -- Building the match and identifier lists ---------------------------------------------


def _add_match(request, existing: set, doctype: str, name: str, source: str) -> None:
	if (doctype, name) in existing:
		return
	existing.add((doctype, name))
	request.append(
		"matches",
		{"reference_doctype": doctype, "reference_name": name, "confirmed": 0, "source": source},
	)


def suggest_matches(request) -> None:
	"""Append unconfirmed match rows for records that look like the requester.

	Leads, contacts and deals whose personal emails or phones equal a non-excluded
	identifier come in as `Identifier match`; deals of a confirmed lead, and deals that
	list a confirmed contact, as `Linked record`. Rows already on the request are kept
	and never repeated."""
	emails = active_identifiers(request, "Email")
	phones = active_identifiers(request, "Phone")
	existing = {(row.reference_doctype, row.reference_name) for row in request.matches}

	for doctype in SOURCES:
		for name in sorted(records_matching(doctype, emails, phones)):
			_add_match(request, existing, doctype, name, "Identifier match")

	linked_deals = set()
	leads = confirmed(request, "CRM Lead")
	if leads:
		linked_deals.update(frappe.get_all("CRM Deal", filters={"lead": ["in", leads]}, pluck="name"))
	contacts = confirmed(request, "Contact")
	if contacts:
		linked_deals.update(
			frappe.get_all(
				"CRM Contacts",
				filters={"parenttype": "CRM Deal", "contact": ["in", contacts]},
				pluck="parent",
			)
		)
	for name in sorted(linked_deals):
		_add_match(request, existing, "CRM Deal", name, "Linked record")


def _identifiers_of_confirmed(request) -> list[tuple[str, str]]:
	"""(kind, raw value) for every email and phone on the confirmed leads and contacts."""
	found = []

	for lead in confirmed(request, "CRM Lead"):
		values = frappe.db.get_value("CRM Lead", lead, ["email", "mobile_no", "phone"], as_dict=True)
		if values:
			found.append(("Email", values.email))
			found += [("Phone", values.mobile_no), ("Phone", values.phone)]

	contacts = confirmed(request, "Contact")
	if contacts:
		for table, column, kind in (
			("Contact Email", "email_id", "Email"),
			("Contact Phone", "phone", "Phone"),
		):
			values = frappe.get_all(
				table,
				filters={"parenttype": "Contact", "parent": ["in", contacts]},
				pluck=column,
				parent_doctype="Contact",
			)
			found += [(kind, value) for value in values]

	return found


def refresh_identifiers(request) -> None:
	"""Add the emails and phones of the confirmed leads and contacts to the identifier list,
	then recount what each identifier matches. Existing rows, excluded ones included, are
	never repeated or re-enabled."""
	known = {(row.kind, normalize(row.kind, row.value)) for row in request.identifiers}

	for kind, value in _identifiers_of_confirmed(request):
		normalized = normalize(kind, value)
		if not normalized or (kind, normalized) in known:
			continue
		known.add((kind, normalized))
		request.append("identifiers", {"kind": kind, "value": value.strip(), "excluded": 0})

	for row in request.identifiers:
		normalized = normalize(row.kind, row.value)
		row.match_count = _match_count(row.kind, normalized) if normalized else 0


# -- On Hold -----------------------------------------------------------------------------


def open_deals_with_person(request) -> list[str]:
	"""Open deals (status type Open, Ongoing or On Hold) that list a confirmed contact."""
	contacts = confirmed(request, "Contact")
	if not contacts:
		return []
	statuses = frappe.get_all("CRM Deal Status", filters={"type": ["in", OPEN_DEAL_TYPES]}, pluck="name")
	if not statuses:
		return []
	deals = frappe.get_all(
		"CRM Contacts",
		filters={"parenttype": "CRM Deal", "contact": ["in", contacts]},
		pluck="parent",
		distinct=True,
	)
	if not deals:
		return []
	return frappe.get_all(
		"CRM Deal",
		filters={"name": ["in", deals], "status": ["in", statuses]},
		pluck="name",
		order_by="name",
	)


def _notify_deal_owners(request, deals: list[str]) -> None:
	"""Ask each open deal's owner to take the requester off the deal or close it."""
	contacts = confirmed(request, "Contact")
	rows = frappe.get_all(
		"CRM Contacts",
		filters={"parenttype": "CRM Deal", "parent": ["in", deals], "contact": ["in", contacts]},
		fields=["parent", "contact", "full_name"],
	)
	for deal in deals:
		owner = frappe.db.get_value("CRM Deal", deal, "deal_owner")
		if not owner:
			continue
		names = list(dict.fromkeys(row.full_name or row.contact for row in rows if row.parent == deal))
		who = ", ".join(names)
		subject = _("Remove {0} from {1} or close it — erasure request {2}").format(who, deal, request.name)
		message = _(
			"{0} has asked for personal data to be erased (request {1}). Remove them from deal {2} "
			"or close the deal so the request can go ahead."
		).format(who, request.name, deal)
		notify(
			[owner],
			subject,
			message,
			request=request.name,
			reference_doctype="CRM Deal",
			reference_name=deal,
		)


def submit_request(request_name: str) -> str:
	"""Hand a logged request to Compliance. Needs at least one confirmed match. The request
	goes On Hold, and each open deal's owner is asked to act, when a confirmed contact is on
	an open deal; otherwise it awaits sign-off. Returns the new status."""
	request = frappe.get_doc(REQUEST, request_name)
	request.check_permission("write")

	if request.status != "Logged":
		frappe.throw(_("Only a request in Logged status can be submitted."))
	if not any(row.confirmed for row in request.matches):
		frappe.throw(_("Confirm at least one matched record before submitting."))

	deals = open_deals_with_person(request)
	request.status = "On Hold" if deals else "Awaiting Sign-off"
	with system_write():
		request.save(ignore_permissions=True)

	if deals:
		_notify_deal_owners(request, deals)
	return request.status


def on_deal_update(doc, method=None) -> None:
	"""Deal on_update hook. For each request On Hold, note the match row when the
	requester was taken off this deal, and release the hold once no confirmed contact is on
	an open deal any more."""
	if not frappe.db.table_exists(REQUEST):
		return
	held = frappe.get_all(REQUEST, filters={"status": "On Hold"}, pluck="name")
	if not held:
		return

	before = doc.get_doc_before_save()
	was_on = {row.contact for row in before.contacts} if before else set()
	is_on = {row.contact for row in doc.contacts}

	for name in held:
		request = frappe.get_doc(REQUEST, name)
		contacts = set(confirmed(request, "Contact"))

		if contacts & was_on and not contacts & is_on:
			for row in request.matches:
				if row.reference_doctype == "CRM Deal" and row.reference_name == doc.name:
					frappe.db.set_value(
						"CRM Erasure Match", row.name, "removed_from_open_deal", 1, update_modified=False
					)

		if not open_deals_with_person(request):
			with system_write():
				frappe.db.set_value(REQUEST, name, "status", "Awaiting Sign-off")
