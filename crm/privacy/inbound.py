import frappe
from frappe import _
from frappe.query_builder.functions import Function

from crm.privacy import compliance_users
from crm.privacy.identifiers import extract_emails, is_do_not_contact
from crm.privacy.notify import notify

REQUEST = "CRM Erasure Request"


def _senders(email: str | None) -> list[str]:
	"""Normalized addresses in a sender string, which may carry a display name."""
	return extract_emails(email)


def _open_request_for(addresses: list[str]) -> str | None:
	"""The non-closed request, if any, whose active email identifiers include one of
	`addresses`. One query over the identifier table, not one document per request."""
	if not addresses:
		return None
	identifier = frappe.qb.DocType("CRM Erasure Identifier")
	request = frappe.qb.DocType(REQUEST)
	rows = (
		frappe.qb.from_(identifier)
		.join(request)
		.on(identifier.parent == request.name)
		.select(request.name)
		.where(identifier.parenttype == REQUEST)
		.where(identifier.kind == "Email")
		.where(identifier.excluded == 0)
		.where(request.status != "Closed")
		.where(Function("LOWER", Function("TRIM", identifier.value)).isin(addresses))
		.orderby(request.creation)
		.limit(1)
		.run()
	)
	return rows[0][0] if rows else None


def is_erased_sender(email: str | None) -> bool:
	"""Whether `email` belongs to a person who asked to be erased: on the do-not-contact
	list, or an active identifier of a request that is not closed yet."""
	addresses = _senders(email)
	if any(is_do_not_contact("Email", address) for address in addresses):
		return True
	return bool(_open_request_for(addresses))


def on_communication_insert(doc, method=None) -> None:
	"""Route mail from an erased person. Incoming mail is never rejected, since that would
	break mailbox sync.

	While her request is open the email is attached to it. Otherwise, if her address is on
	the do-not-contact list, it stays unlinked and Compliance is told to decide."""
	if doc.sent_or_received != "Received" or doc.communication_type != "Communication":
		return

	addresses = _senders(doc.sender)
	if not addresses:
		return

	request = _open_request_for(addresses)
	if request:
		doc.reference_doctype = REQUEST
		doc.reference_name = request
		doc.db_set({"reference_doctype": REQUEST, "reference_name": request}, update_modified=False)
		return

	if any(is_do_not_contact("Email", address) for address in addresses):
		notify(
			compliance_users(),
			_("Email received from an erased person"),
			_("An email arrived from a person who asked to be erased. It was not attached to anything."),
			reference_doctype="Communication",
			reference_name=doc.name,
		)
