"""The end of a request's life: closing it (wiping what is left of her), and the retention purge.

`close` writes only through `frappe.db` (never `doc.save()`), so no Version or Deleted
Document keeps what it removes. Text written here never carries her name, email or phone.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import add_months, getdate

from crm.privacy.rules import erased_content
from crm.privacy.sweep import _reset_comment_caches, _wipe, erase_communications

DOCTYPE = "CRM Erasure Request"
RETAINED_CONTRACT = "CRM Retained Contract"
CHECKLIST_ITEM = "CRM Erasure Checklist Item"
IDENTIFIER = "CRM Erasure Identifier"
MATCH = "CRM Erasure Match"
RETENTION_MONTHS = 24

CLEARED_FIELDS = ("requester_name", "other_names", "original_message", "contract_references")


def _request_communications(request: str) -> list[str]:
	"""Mail attached to the request (inbound mail from her address while it was open)."""
	names = frappe.get_all(
		"Communication", filters={"reference_doctype": DOCTYPE, "reference_name": request}, pluck="name"
	)
	names += frappe.get_all(
		"Communication Link",
		filters={"link_doctype": DOCTYPE, "link_name": request, "parenttype": "Communication"},
		pluck="parent",
		parent_doctype="Communication",
	)
	return list(dict.fromkeys(names))


def close(doc: Document) -> None:
	"""Wipe what is left of her on the request and mark it Closed.

	The log fields (dates, type, channel, outcome, deadlines) stay; the identifiers and
	matches go, free text becomes a placeholder. Mail attached to the request is wiped with
	every identifier on the request, since all of them are hers.
	"""
	name = doc.name
	emails = {row.value for row in doc.identifiers if row.kind == "Email" and row.value}
	phones = {row.value for row in doc.identifiers if row.kind == "Phone" and row.value}
	content = erased_content(name)

	erase_communications(_request_communications(name), emails, phones, name)

	frappe.db.set_value(DOCTYPE, name, {field: "" for field in CLEARED_FIELDS}, update_modified=False)
	frappe.db.delete(IDENTIFIER, {"parent": name, "parenttype": DOCTYPE})
	frappe.db.delete(MATCH, {"parent": name, "parenttype": DOCTYPE})
	for row in doc.checklist:
		frappe.db.set_value(CHECKLIST_ITEM, row.name, "description", content, update_modified=False)

	comments = frappe.get_all(
		"Comment", filters={"reference_doctype": DOCTYPE, "reference_name": name}, pluck="name"
	)
	_wipe("Comment", comments, ("content", "subject"), content)
	_reset_comment_caches({DOCTYPE: [name]})

	frappe.db.set_value(DOCTYPE, name, "status", "Closed", update_modified=False)


def purge_expired(today=None) -> None:
	"""Daily: delete closed requests answered over 24 months ago and expired retained contracts.

	Deleted permanently, so no Deleted Document keeps a copy.
	"""
	today = getdate(today)
	cutoff = add_months(today, -RETENTION_MONTHS)
	for name in frappe.get_all(
		DOCTYPE, filters={"status": "Closed", "date_answered": ["<", cutoff]}, pluck="name"
	):
		_delete(DOCTYPE, name)
	for name in frappe.get_all(RETAINED_CONTRACT, filters={"delete_after": ["<=", today]}, pluck="name"):
		_delete(RETAINED_CONTRACT, name)


def _delete(doctype: str, name: str) -> None:
	frappe.delete_doc(doctype, name, ignore_permissions=True, delete_permanently=True, force=True)
