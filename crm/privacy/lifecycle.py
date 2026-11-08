"""The end of a request's life: closing it (wiping what is left of her), and the retention purge.

`close` writes only through `frappe.db` (never `doc.save()`), so no Version or Deleted
Document keeps what it removes. Text written here never carries her name, email or phone.
"""

from collections.abc import Callable

import frappe
from frappe.model.document import Document
from frappe.utils import add_months, getdate

from crm.privacy.rules import erased_content
from crm.privacy.sweep import _reset_comment_caches, _wipe, delete_files, erase_communications, guarded

DOCTYPE = "CRM Erasure Request"
RETAINED_CONTRACT = "CRM Retained Contract"
CHECKLIST_ITEM = "CRM Erasure Checklist Item"
IDENTIFIER = "CRM Erasure Identifier"
MATCH = "CRM Erasure Match"
RETENTION_MONTHS = 24

CLEARED_FIELDS = (
	"requester_name",
	"other_names",
	"original_message",
	"contract_references",
	"decline_reason",
	"erasure_error",  # not a log field (spec 5.8)
)


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
	every identifier on the request, since all of them are hers. Files attached to that mail
	or to the request are deleted, and their stored bytes removed from disk after the commit.
	"""
	name = doc.name
	emails = {row.value for row in doc.identifiers if row.kind == "Email" and row.value}
	phones = {row.value for row in doc.identifiers if row.kind == "Phone" and row.value}
	content = erased_content(name)

	communications = _request_communications(name)
	erase_communications(communications, emails, phones, name)
	# Attachments on her mail and on the request are hers; the purge would not reach the mail's.
	disk_removals: list[Callable] = []
	if communications:
		delete_files(
			{"attached_to_doctype": "Communication", "attached_to_name": ["in", communications]},
			name,
			disk_removals,
		)
	delete_files({"attached_to_doctype": DOCTYPE, "attached_to_name": name}, name, disk_removals)
	for fn in disk_removals:
		frappe.db.after_commit.add(guarded(name, fn))

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
	"""Delete one row. A failure is logged (by name only) and skipped, so one bad row
	does not stop the daily job."""
	savepoint = "erasure_purge"
	frappe.db.savepoint(savepoint)
	try:
		frappe.delete_doc(doctype, name, ignore_permissions=True, delete_permanently=True, force=True)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		# An explicit message keeps the traceback (and its local variables, which can hold a
		# retained contract's name) out of the Error Log.
		frappe.log_error(
			title=f"Erasure purge failed for {name}",
			message="The record could not be deleted. It stays until the next daily run.",
			reference_doctype=doctype,
			reference_name=name,
		)
	else:
		frappe.db.release_savepoint(savepoint)
