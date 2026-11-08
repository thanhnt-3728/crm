"""Incoming email from people with an open or finished erasure request.

Incoming email is never rejected, since that would break mailbox sync. Instead:
- no lead is created from it;
- while her request is open, the email is attached to the request;
- after close (her email is on the do-not-contact list) it is attached to nothing and
  Compliance is notified. Compliance reads it through `crm.privacy.api.get_blocked_email`
  (`blocked_email` decides which mail that is); there is no general Communication grant.

Nothing here may raise for an ordinary inbound email: an exception in a Communication
hook makes `EmailAccount.receive` roll the mail back and park it as an Unhandled Email.
Messages and log titles never contain the sender's address.
"""

from email.utils import parseaddr

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Order

from crm.privacy.blocking import ErasedPersonError
from crm.privacy.identifiers import blocking_request, compliance_users, is_blocked, normalize_email
from crm.privacy.reminders import notify

DOCTYPE = "CRM Erasure Request"
IDENTIFIER = "CRM Erasure Identifier"
BLOCKED_INBOUND_SUBJECT = "An email arrived from a person whose data was erased. Decide what to do with it."


def _address(email: str | None) -> str:
	"""The bare, normalized address of `email`, which may be `Name <address>`."""
	return normalize_email(parseaddr(email or "")[1] or email)


def open_request_for_email(email: str | None) -> str | None:
	"""The newest non-Closed request with a non-excluded email identifier equal to `email`."""
	value = _address(email)
	if not value:
		return None
	request = frappe.qb.DocType(DOCTYPE)
	identifier = frappe.qb.DocType(IDENTIFIER)
	rows = (
		frappe.qb.from_(identifier)
		.join(request)
		.on(identifier.parent == request.name)
		.select(request.name)
		.where(identifier.parenttype == DOCTYPE)
		.where(identifier.parentfield == "identifiers")
		.where(identifier.kind == "Email")
		.where(identifier.value == value)
		.where(identifier.excluded == 0)
		.where(request.status != "Closed")
		.orderby(request.creation, order=Order.desc)
		.orderby(request.name, order=Order.desc)
		.limit(1)
		.run()
	)
	return rows[0][0] if rows else None


def is_erasure_address(email: str | None) -> bool:
	"""True when `email` belongs to an open request or is on the do-not-contact list."""
	return bool(open_request_for_email(email)) or is_blocked("Email", _address(email))


def _is_inbound_email(doc) -> bool:
	return doc.sent_or_received == "Received" and doc.communication_medium == "Email"


def route_inbound_email(doc, method=None) -> None:
	"""Communication `before_insert`: attach her email to her open request, or to nothing
	once she is on the do-not-contact list."""
	if not _is_inbound_email(doc):
		return

	request = open_request_for_email(doc.sender)
	if request:
		doc.reference_doctype = DOCTYPE
		doc.reference_name = request
		doc.reference_owner = None  # recomputed for the request by Communication.validate_reference
		doc.set("timeline_links", [])
	elif is_blocked("Email", _address(doc.sender)):
		doc.reference_doctype = None
		doc.reference_name = None
		doc.reference_owner = None
		doc.set("timeline_links", [])
		doc.flags.erasure_blocked_sender = True


def keep_off_timelines(doc, method=None) -> None:
	"""Communication `validate`: drop the timeline links that `Communication.validate`
	(`set_timeline_links`, `parse_email_for_timeline_links`) re-adds after `before_insert`,
	so her email doesn't show on her lead, deal or contact. Runs on every save."""
	if not _is_inbound_email(doc):
		return
	if doc.flags.erasure_blocked_sender:
		doc.reference_doctype = None
		doc.reference_name = None
		doc.set("timeline_links", [])
	elif doc.reference_doctype == DOCTYPE:
		doc.set("timeline_links", [])


def request_blocking(sender: str | None) -> str | None:
	"""The request whose do-not-contact entry blocks `sender`, while that request still exists.

	The request log entry is deleted 24 months after its answer; the block is permanent.
	"""
	request = blocking_request("Email", _address(sender))
	return request if request and frappe.db.exists(DOCTYPE, request) else None


def blocked_email(name: str | None) -> Document | None:
	"""The Communication `name` when it is mail that arrived from a do-not-contact address
	and was attached to nothing (what `route_inbound_email` does after close), else None.

	Judged from stored state only: `flags.erasure_blocked_sender` lives only in memory, and
	the CRM Notification is just navigation (Compliance users added later get none).
	"""
	if not name or not isinstance(name, str):
		return None
	row = frappe.db.get_value(
		"Communication",
		name,
		["name", "sent_or_received", "communication_medium", "reference_doctype", "sender"],
		as_dict=True,
	)
	if not row or not _is_inbound_email(row) or row.reference_doctype:
		return None
	if frappe.db.exists("Communication Link", {"parenttype": "Communication", "parent": row.name}):
		return None
	if not is_blocked("Email", _address(row.sender)):
		return None
	return frappe.get_doc("Communication", row.name)


def notify_blocked_inbound(doc, method=None) -> None:
	"""Communication `after_insert`: tell Compliance an email arrived from an erased person.

	Written in the Communication's own transaction. A failure is logged and rolled back to
	a savepoint instead of raised, so the email is still stored."""
	if not doc.flags.erasure_blocked_sender:
		return
	request = request_blocking(doc.sender)

	save_point = "erasure_blocked_inbound"
	frappe.db.savepoint(save_point)
	try:
		notify(
			compliance_users(),
			BLOCKED_INBOUND_SUBJECT,
			request=request,
			reference_doctype="Communication",
			reference_name=doc.name,
		)
	except Exception:
		frappe.db.rollback(save_point=save_point)
		# A fixed message: without one the traceback (and its local variables, which hold
		# the sender) would be stored in the Error Log.
		frappe.log_error(
			title="Could not notify Compliance of an email from an erased person",
			message="Compliance could not be notified.",
			reference_doctype="Communication",
			reference_name=doc.name,
		)
	else:
		frappe.db.release_savepoint(save_point)


def guard_inbound_lead(doc, method=None) -> None:
	"""CRM Lead `before_insert`: refuse the lead Frappe's inbound mail creates for a sender
	with an open request. Inbound mail sets `ignore_mandatory` on it and swallows
	`DuplicateEntryError`, so the email is still stored. Do-not-contact addresses are
	already refused by `crm.privacy.blocking.check_doc`."""
	if not doc.flags.ignore_mandatory or frappe.flags.in_import:
		return
	if open_request_for_email(doc.email):
		frappe.throw(
			_(
				"This person has an open request to erase their personal data. A lead can't be created for them."
			),
			ErasedPersonError,
		)
