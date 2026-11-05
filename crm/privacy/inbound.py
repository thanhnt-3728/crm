import frappe
from frappe import _
from frappe.query_builder.functions import Function

from crm.privacy import compliance_users
from crm.privacy.identifiers import extract_emails, is_do_not_contact
from crm.privacy.notify import notify

REQUEST = "CRM Erasure Request"
ERASED_SENDER_FLAG = "erased_sender"


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
	break mailbox sync: any failure here is logged and the email is kept as it came.

	While their request is open the email is attached to it and Compliance is told.
	Otherwise, if the address is on the do-not-contact list, it stays unlinked and
	Compliance is told to decide."""
	try:
		_route_communication(doc)
	except Exception:
		# No document in the log: it would carry the sender's address.
		frappe.log_error(title="Erased-sender routing failed")


def _route_communication(doc) -> None:
	if doc.sent_or_received != "Received" or doc.communication_type != "Communication":
		return

	addresses = _senders(doc.sender)
	if not addresses:
		return

	request = _open_request_for(addresses)
	if request:
		attach_to_request(doc, request)
		notify(
			compliance_users(),
			_("Email received for erasure request {0}").format(request),
			_(
				"An email arrived from the requester of erasure request {0}. It is attached to the request."
			).format(request),
			request=request,
		)
		return

	if any(is_do_not_contact("Email", address) for address in addresses):
		notify(
			compliance_users(),
			_("Email received from an erased person"),
			_("An email arrived from a person who asked to be erased. It was not attached to anything."),
			reference_doctype="Communication",
			reference_name=doc.name,
		)


def attach_to_request(doc, request: str) -> None:
	"""Attach the email to the request without taking it off what it is already on: an
	email that references a record (a reply on a lead's thread, say) gets a timeline link to
	the request; one that references nothing gets the request as its reference. The request
	finds both at close (`crm.api.erasure._linked_communications`)."""
	if doc.reference_doctype == REQUEST and doc.reference_name == request:
		return
	if doc.reference_doctype and doc.reference_name:
		if any(
			link.link_doctype == REQUEST and link.link_name == request
			for link in doc.get("timeline_links") or []
		):
			return
		# Inserted as a row of its own: saving the email again here would run its hooks twice.
		row = doc.append("timeline_links", {"link_doctype": REQUEST, "link_name": request})
		row.db_insert()
		return
	doc.reference_doctype = REQUEST
	doc.reference_name = request
	doc.db_set({"reference_doctype": REQUEST, "reference_name": request}, update_modified=False)


def on_whatsapp_insert(doc, method=None) -> None:
	"""Tell Compliance about a WhatsApp message from an erased number. The message was saved
	without a lead (see `crm.api.whatsapp._resolve_reference`, which sets the flag); this
	runs once, after the message exists, so the notification can link it."""
	if not doc.flags.get(ERASED_SENDER_FLAG):
		return
	try:
		notify(
			compliance_users(),
			_("WhatsApp message received from an erased person"),
			_("A WhatsApp message arrived from a person who asked to be erased. No lead was created."),
			reference_doctype="WA Message",
			reference_name=doc.name,
		)
	except Exception:
		frappe.log_error(title="Erased-sender WhatsApp notice failed")
