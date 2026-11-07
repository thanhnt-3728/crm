"""Incoming email from people with an open or finished erasure request.

Incoming email is never rejected, since that would break mailbox sync. Instead:
- no lead is created from it;
- while her request is open, the email is attached to the request;
- after close (her email is on the do-not-contact list) it is attached to nothing and
  Compliance is notified.

Nothing here may raise for an ordinary inbound email: an exception in a Communication
hook makes `EmailAccount.receive` roll the mail back and park it as an Unhandled Email.
Messages and log titles never contain the sender's address.
"""

from email.utils import parseaddr
from functools import partial

import frappe
from frappe import _
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


def notify_blocked_inbound(doc, method=None) -> None:
	"""Communication `after_insert`: after commit, tell Compliance an email arrived from an erased person."""
	if not doc.flags.erasure_blocked_sender:
		return
	request = blocking_request("Email", _address(doc.sender))
	frappe.db.after_commit.add(partial(_notify_compliance, doc.name, request))


def _notify_compliance(communication: str, request: str | None) -> None:
	# The request log entry is deleted 24 months after its answer; the block is permanent.
	if request and not frappe.db.exists(DOCTYPE, request):
		request = None
	notify(
		compliance_users(),
		BLOCKED_INBOUND_SUBJECT,
		request=request,
		reference_doctype="Communication",
		reference_name=communication,
	)


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
