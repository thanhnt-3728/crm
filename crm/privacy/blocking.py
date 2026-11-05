import frappe
from frappe import _

from crm.privacy.identifiers import is_do_not_contact


class ErasedPersonError(frappe.ValidationError):
	"""Raised when a save would add an erased person's details to the CRM. Paths that
	create records in bulk or in the background (lead sync, incoming messages) catch it to
	skip the record quietly, without logging the details they were given."""


# Fields on the document itself, by identifier kind.
_FIELDS = {
	"CRM Lead": (("Email", "email"), ("Phone", "mobile_no"), ("Phone", "phone")),
	"Contact": (("Email", "email_id"), ("Phone", "mobile_no"), ("Phone", "phone")),
}

# Child tables whose rows carry identifiers: doctype -> ((table fieldname, ((kind, fieldname), ...)), ...).
_TABLES = {
	"CRM Deal": (("contacts", (("Email", "email"), ("Phone", "mobile_no"), ("Phone", "phone"))),),
	"Contact": (
		("email_ids", (("Email", "email_id"),)),
		("phone_nos", (("Phone", "phone"),)),
	),
}


def validate(doc, method=None) -> None:
	"""Refuse to add an erased person's email or phone to the CRM.

	New documents are checked on every identifier field. Existing documents only on fields
	that changed, so a record that already holds a value (judged "not her") keeps saving."""
	blocked = _blocked_fields(doc) or _blocked_rows(doc)
	if blocked:
		frappe.throw(
			_(
				"This person asked to be erased under a privacy request. Their details can't be added to the CRM."
			),
			ErasedPersonError,
		)


def _blocked_fields(doc) -> bool:
	for kind, fieldname in _FIELDS.get(doc.doctype, ()):
		if not doc.get(fieldname):
			continue
		if not doc.is_new() and not doc.has_value_changed(fieldname):
			continue
		if is_do_not_contact(kind, doc.get(fieldname)):
			return True
	return False


def _blocked_rows(doc) -> bool:
	tables = _TABLES.get(doc.doctype, ())
	before = None if doc.is_new() else doc.get_doc_before_save()
	for table, fields in tables:
		old_rows = {}
		if before is not None:
			old_rows = {row.name: row for row in before.get(table) or [] if row.name}
		for row in doc.get(table) or []:
			old_row = old_rows.get(row.name) if row.name else None
			for kind, fieldname in fields:
				value = row.get(fieldname)
				if not value:
					continue
				if old_row is not None and (old_row.get(fieldname) or "") == value:
					continue
				if is_do_not_contact(kind, value):
					return True
	return False
