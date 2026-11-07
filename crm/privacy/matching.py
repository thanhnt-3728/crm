# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Find the records that may belong to the requester (design 5.3).

Reads only: callers append the returned hits to the request and save it. Values are compared for
equality (email) or by their digits after normalizing (phone), never with a pattern built from what
the user typed, so a `%` or `_` in an identifier cannot widen a match (RT-4).
"""

import frappe
from frappe import _
from pypika.functions import Replace

from crm.privacy.identifiers import PHONE_REGION, normalize_email
from crm.privacy.request_visibility import is_compliance
from crm.utils import normalize_phone, phone_search_digits

LEAD, DEAL, CONTACT = "CRM Lead", "CRM Deal", "Contact"
# (table, column, doctype of the record that owns the row, what the reason calls it)
EMAIL_COLUMNS = (
	(LEAD, "email", LEAD, "lead"),
	(DEAL, "email", DEAL, "deal"),
	("Contact Email", "email_id", CONTACT, "contact"),
	("CRM Contacts", "email", DEAL, "deal contact row"),
)
PHONE_COLUMNS = (
	(LEAD, "mobile_no", LEAD, "lead"),
	(LEAD, "phone", LEAD, "lead"),
	(DEAL, "mobile_no", DEAL, "deal"),
	(DEAL, "phone", DEAL, "deal"),
	("Contact Phone", "phone", CONTACT, "contact"),
	("CRM Contacts", "mobile_no", DEAL, "deal contact row"),
	("CRM Contacts", "phone", DEAL, "deal contact row"),
)
# Personal-field tables whose rows belong to a matchable record.
OWNER_OF = {LEAD: LEAD, DEAL: DEAL, CONTACT: CONTACT, "Contact Email": CONTACT, "CRM Contacts": DEAL}
STALE_RELATIONS = ("Direct", "Linked")


def digits_only(column):
	"""The column with the punctuation phones are typed with removed, for the SQL prefilter on digits."""
	for mark in (" ", "-", "(", ")", "+", ".", "/"):
		column = Replace(column, mark, "")
	return column


def can_read(user: str, doctype: str, name: str) -> bool:
	"""Whether `user` may open the record. A missing record is not readable (a match row can outlive it)."""
	if is_compliance(user):
		return True
	try:
		return bool(frappe.has_permission(doctype, "read", name, user=user))
	except frappe.DoesNotExistError:
		return False


def _email_columns() -> list[tuple]:
	"""The fixed email columns plus any email-typed field on the personal-fields list (design 5.3)."""
	columns = list(EMAIL_COLUMNS)
	known = {(table, column) for table, column, *_rest in columns}
	for row in frappe.get_single("CRM Privacy Settings").personal_fields:
		owner = OWNER_OF.get(row.document_type)
		field = frappe.get_meta(row.document_type).get_field(row.fieldname) if owner else None
		if field and field.options == "Email" and (row.document_type, row.fieldname) not in known:
			known.add((row.document_type, row.fieldname))
			columns.append((row.document_type, row.fieldname, owner, f"personal field {row.fieldname}"))
	return columns


def _rows(table: str, column: str, owner: str):
	"""A query yielding the owning record's name and the column value for every row of `table`."""
	Table = frappe.qb.DocType(table)
	owner_name = Table.name if table == owner else Table.parent
	query = frappe.qb.from_(Table).select(owner_name, Table[column])
	return query if table == owner else query.where(Table.parenttype == owner)


def find_by_email(email: str) -> list[dict]:
	"""Records holding exactly this address: `{doctype, name, reason}` each, one per record."""
	email = normalize_email(email)
	hits = {}
	for table, column, owner, what in _email_columns() if email else []:
		Table = frappe.qb.DocType(table)
		for name, _value in _rows(table, column, owner).where(Table[column] == email).run():
			hits.setdefault((owner, name), _("email {0} on {1}").format(email, _(what)))
	return [{"doctype": d, "name": n, "reason": reason} for (d, n), reason in hits.items()]


def same_number(stored: str | None, target: str) -> bool:
	"""Whether a stored free-text phone is the E.164 `target`, read as a US number or in the site's region."""
	return bool(stored) and target in (normalize_phone(stored, region=PHONE_REGION), normalize_phone(stored))


def find_by_phone(value: str) -> list[dict]:
	"""Records holding this number in any format. The SQL only prefilters on the digits."""
	target = normalize_phone(value, region=PHONE_REGION)
	digits = phone_search_digits(value, region=PHONE_REGION)
	if not (target and digits):
		return []
	hits = {}
	for table, column, owner, what in PHONE_COLUMNS:
		query = _rows(table, column, owner).where(
			digits_only(frappe.qb.DocType(table)[column]).like(f"%{digits}%")
		)
		for name, stored in query.run():
			if same_number(stored, target):
				hits.setdefault((owner, name), _("phone {0} on {1}").format(value, _(what)))
	return [{"doctype": d, "name": n, "reason": reason} for (d, n), reason in hits.items()]


def linked_hits(doc) -> list[dict]:
	"""Deals that follow from a confirmed match: converted from a confirmed lead, or listing a confirmed contact."""
	hits = []
	for row in doc.matches:
		if not (row.confirmed and frappe.db.exists(row.reference_doctype, row.reference_name)):
			continue
		if row.reference_doctype == LEAD:
			deals = frappe.get_all(DEAL, {"lead": row.reference_name}, pluck="name")
			reason = _("Converted from the confirmed lead {0}").format(row.reference_name)
		elif row.reference_doctype == CONTACT:
			Contacts = frappe.qb.DocType("CRM Contacts")
			query = frappe.qb.from_(Contacts).select(Contacts.parent)
			deals = query.where((Contacts.contact == row.reference_name) & (Contacts.parenttype == DEAL)).run(
				pluck=True
			)
			reason = _("Lists the confirmed contact {0}").format(row.reference_name)
		else:
			continue
		hits += [{"doctype": DEAL, "name": deal, "reason": reason} for deal in deals]
	return hits


def _label(doctype: str, name: str) -> str:
	field = {LEAD: "lead_name", CONTACT: "full_name", DEAL: "organization"}[doctype]
	return (frappe.db.get_value(doctype, name, field) or name)[:140]


def _append_missing(doc, found: dict, user: str) -> bool:
	"""Append every found record the user can read and the request does not list yet, unconfirmed."""
	listed = {(m.reference_doctype, m.reference_name) for m in doc.matches}
	added = False
	for (doctype, name), (reason, relation) in found.items():
		if (doctype, name) in listed or not can_read(user, doctype, name):
			continue
		doc.append(
			"matches",
			{
				"reference_doctype": doctype,
				"reference_name": name,
				"label": _label(doctype, name),
				"reason": reason,
				"confirmed": 0,
				"relation": relation,
			},
		)
		added = True
	return added


def add_linked_suggestions(doc, user: str) -> bool:
	"""Re-run only the suggestions that follow from confirmed records. Returns True when a row was added."""
	found = {(h["doctype"], h["name"]): (h["reason"], "Linked") for h in linked_hits(doc)}
	return _append_missing(doc, found, user)


def refresh_suggestions(doc, user: str) -> bool:
	"""Bring the unconfirmed suggestions in line with the non-excluded identifiers and confirmed records:
	drop unconfirmed rows nothing supports any more, add what is new and readable by `user` (RT-5).
	Confirmed and starting rows are never removed. Returns True when the rows changed."""
	found = {}
	for identifier in doc.identifiers:
		if identifier.excluded:
			continue
		finder = find_by_email if identifier.kind == "Email" else find_by_phone
		for hit in finder(identifier.value):
			found.setdefault((hit["doctype"], hit["name"]), (hit["reason"], "Direct"))
	for hit in linked_hits(doc):
		found.setdefault((hit["doctype"], hit["name"]), (hit["reason"], "Linked"))
	stale = [
		row
		for row in doc.matches
		if not row.confirmed
		and not row.is_source
		and row.relation in STALE_RELATIONS
		and (row.reference_doctype, row.reference_name) not in found
	]
	for row in stale:
		doc.remove(row)
	return _append_missing(doc, found, user) or bool(stale)
