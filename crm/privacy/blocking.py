"""Stop erased people being added back to the CRM.

After an erasure, a person's emails and phone numbers survive only as keyed hashes in
`CRM Do Not Contact`. `check_doc` is registered as a `validate` hook on every record
that holds an identifier, so any creation path (forms, API, imports, mail ingest,
integrations) is refused. Messages never contain the blocked value.
"""

import frappe
from frappe import _

from crm.privacy.identifiers import is_blocked, normalize_identifier, personal_fields


class ErasedPersonError(frappe.DuplicateEntryError):
	"""A subclass of DuplicateEntryError because Frappe's inbound-mail code swallows that
	one, so a blocked sender never aborts mail ingest."""


IDENTIFIER_FIELDS = {
	"CRM Lead": {
		"fields": {"email": "Email", "mobile_no": "Phone", "phone": "Phone"},
		"tables": {},
	},
	"CRM Deal": {
		"fields": {"email": "Email", "mobile_no": "Phone", "phone": "Phone"},
		"tables": {"contacts": {"email": "Email", "mobile_no": "Phone", "phone": "Phone"}},
	},
	"Contact": {
		"fields": {"email_id": "Email", "mobile_no": "Phone", "phone": "Phone"},
		"tables": {
			"email_ids": {"email_id": "Email"},
			"phone_nos": {"phone": "Phone"},
		},
	},
}


def identifier_fields(doctype: str) -> dict:
	"""The doctype's identifier fields: the built-in ones plus any personal-field-list
	custom field that is an email or phone."""
	base = IDENTIFIER_FIELDS.get(doctype)
	if not base:
		return {"fields": {}, "tables": {}}
	fields = dict(base["fields"])
	tables = {table: dict(columns) for table, columns in base["tables"].items()}
	custom = personal_fields().get(doctype)
	if custom:
		meta = frappe.get_meta(doctype)
		for fieldname in custom:
			df = meta.get_field(fieldname)
			if not df or fieldname in fields:
				continue
			if df.fieldtype == "Phone" or df.options == "Phone":
				fields[fieldname] = "Phone"
			elif df.options == "Email":
				fields[fieldname] = "Email"
	return {"fields": fields, "tables": tables}


def _stored_row_values(doc, table: str, column: str) -> list:
	child_doctype = frappe.get_meta(doc.doctype).get_field(table).options
	return frappe.get_all(
		child_doctype,
		filters={"parent": doc.name, "parenttype": doc.doctype, "parentfield": table},
		pluck=column,
		parent_doctype=doc.doctype,
	)


def new_identifier_values(doc) -> list[tuple[str, str]]:
	"""`(kind, value)` for each identifier the save would add: all of them on a new
	record; on an existing one only changed fields and child rows not already stored."""
	spec = identifier_fields(doc.doctype)
	is_new = doc.is_new()
	values: list[tuple[str, str]] = []

	for fieldname, kind in spec["fields"].items():
		value = doc.get(fieldname)
		if value and (is_new or doc.has_value_changed(fieldname)):
			values.append((kind, value))

	for table, columns in spec["tables"].items():
		rows = doc.get(table) or []
		if not rows:
			continue
		for column, kind in columns.items():
			current = [row.get(column) for row in rows if row.get(column)]
			if not current:
				continue
			stored = (
				set()
				if is_new
				else {normalize_identifier(kind, v) for v in _stored_row_values(doc, table, column)}
			)
			values.extend((kind, v) for v in current if normalize_identifier(kind, v) not in stored)

	return values


def blocked_values(doc) -> bool:
	return any(is_blocked(kind, value) for kind, value in new_identifier_values(doc))


def data_is_blocked(doctype: str, data: dict) -> bool:
	"""Whether a not-yet-saved record's field values (a dict) hold a blocked identifier."""
	return any(
		data.get(fieldname) and is_blocked(kind, data[fieldname])
		for fieldname, kind in identifier_fields(doctype)["fields"].items()
	)


def check_doc(doc, method=None) -> None:
	"""`validate` hook: refuse a record that would add a blocked email or phone."""
	if blocked_values(doc):
		frappe.throw(
			_(
				"This person asked for their personal data to be erased. Their email address or phone number can't be added to the CRM."
			),
			ErasedPersonError,
		)
