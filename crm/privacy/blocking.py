import sys

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


# -- Leads Frappe would create from inbound mail -------------------------------------------


class InboundLeadSkipped(frappe.DuplicateEntryError):
	"""Raised from CRM Lead `before_insert` to stop Frappe's inbound mail from creating a
	lead for a person who asked to be erased.

	An Email Account whose `append_to` is CRM Lead makes `InboundMail` insert a lead before
	the Communication exists (`frappe.email.receive.InboundMail._create_reference_document`).
	That method catches only `DuplicateEntryError` (inside a savepoint on newer Frappe) and
	then looks for an existing lead with the sender's address; any other error fails the
	whole mail, and Frappe keeps the raw message, address and text, as an Unhandled Email.
	Raised as a DuplicateEntryError, the lead is skipped and the mail is still imported: as
	a Communication on no record (or on the person's existing lead while the request is
	open), which `crm.privacy.inbound.on_communication_insert` then routes."""


INBOUND_MAIL_METHOD = "_create_reference_document"


def _inserted_by_inbound_mail(doc) -> bool:
	"""Whether `doc` is being inserted by Frappe's inbound mail, as the reference document
	of an incoming email. Frappe passes no flag for this, so the call stack is read: a frame
	of `InboundMail._create_reference_document` whose new document (`parent`) is `doc`."""
	try:
		from frappe.email.receive import InboundMail
	except ImportError:
		return False
	frame = sys._getframe(1)
	while frame is not None:
		if frame.f_code.co_name == INBOUND_MAIL_METHOD:
			f_locals = frame.f_locals
			if isinstance(f_locals.get("self"), InboundMail) and f_locals.get("parent") is doc:
				return True
		frame = frame.f_back
	return False


def before_lead_insert(doc, method=None) -> None:
	"""CRM Lead before_insert hook. Inbound mail creates no lead for a sender on the
	do-not-contact list or an active identifier of a request that is not closed (spec 5.9);
	the mail itself is still imported. Other ways of creating a lead are left to `validate`,
	which refuses the do-not-contact list with a message."""
	if not _inserted_by_inbound_mail(doc):
		return
	from crm.privacy.inbound import is_erased_sender

	try:
		erased = is_erased_sender(doc.get("email"))
	except Exception:
		# Never fail an incoming email over this check; `validate` still blocks the list.
		frappe.log_error(title="Erased-sender check failed", message="Inbound mail lead check failed.")
		return
	if erased:
		raise InboundLeadSkipped
