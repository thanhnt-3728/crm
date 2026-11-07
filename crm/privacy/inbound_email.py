# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Inbound email from a person who asked to be erased (design 5.9). Mail is never rejected: that would
break mailbox sync. It only changes what the mail is attached to and whether it may start a lead.

Routing runs in the Communication `before_insert` hook (`route_before_insert`), so the reference is final before
Frappe stamps the status and pushes the mail to the reference's page in realtime. `finish_routing`, called from
`on_communication_insert`, stops the lead and sends the Compliance notice (it needs the saved name).

* While her request is open (anything but Declined or Closed) the mail is attached to the request,
  found by the request's confirmed email identifiers. This replaces an existing reference too: Frappe
  threads a reply onto the old lead by In-Reply-To.
* Afterwards the do-not-contact list decides: the mail is attached to nothing and Compliance is told.
"""

from email.utils import parseaddr

import frappe
from frappe import _
from frappe.query_builder import Order

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import DncSecretUnavailableError
from crm.privacy.do_not_contact import (
	digest_of,
	is_blocked,
	notify_compliance,
	report_secret_unavailable,
)
from crm.privacy.identifiers import normalize_email
from crm.privacy.on_hold import _isolated
from crm.privacy.request_status import CLOSED, DECLINED
from crm.privacy.request_visibility import DOCTYPE

TITLE = "Inbound email privacy check"
NOTICE_KEY = "crm_dnc_inbound_notice"  # + the sender's hash: one Compliance notice per sender per day
NOTICE_SECONDS = 24 * 60 * 60
REQUEST, DETACHED, UNCHECKED = "request", "detached", "unchecked"


def sender_address(doc) -> str:
	"""The normalized address in `Name <address>`, or "" when the sender holds none."""
	address = parseaddr(doc.sender or "")[1]
	return normalize_email(address) if "@" in address else ""


def open_request_for(email: str) -> str | None:
	"""The newest request that is not Declined or Closed and lists `email` as a confirmed identifier."""
	Identifier, Request = frappe.qb.DocType("CRM Erasure Identifier"), frappe.qb.DocType(DOCTYPE)
	query = (
		frappe.qb.from_(Identifier)
		.join(Request)
		.on(Identifier.parent == Request.name)
		.select(Request.name)
		.where((Identifier.parenttype == DOCTYPE) & (Identifier.parentfield == "identifiers"))
		.where((Identifier.kind == "Email") & (Identifier.normalized == email) & (Identifier.excluded == 0))
		.where(Request.status.notin([CLOSED, DECLINED]))
		.orderby(Request.creation, order=Order.desc)
		.limit(1)
	)
	request = next(iter(query.run(pluck=True)), None)
	return request if request and still_open(request) else None


def still_open(request: str) -> bool:
	"""The request's status read under its row lock. A close holds that lock until it commits, so mail arriving
	while one runs waits here and then sees Closed, instead of being attached to a request that was just scrubbed."""
	return frappe.db.get_value(DOCTYPE, request, "status", for_update=True) not in (CLOSED, DECLINED)


def _route(doc) -> str | None:
	"""Where the mail goes: REQUEST (attached to an open request), DETACHED (a blocked address: attached to
	nothing), UNCHECKED (the secret is missing, nothing is known) or None (an ordinary mail)."""
	email = sender_address(doc)
	if not email:
		return None
	if request := open_request_for(email):
		_relink(doc, DOCTYPE, request)
		return REQUEST
	queued = len(frappe.local.message_log)
	try:
		if not is_blocked("email", email):
			return None
	except DncSecretUnavailableError:
		del frappe.local.message_log[queued:]  # what Frappe said while failing to decrypt the key
		report_secret_unavailable("inbound email")  # RT-15: the mail stays as it is, but starts no lead
		return UNCHECKED
	_relink(doc, None, None)
	return DETACHED


def _relink(doc, doctype: str | None, name: str | None) -> None:
	"""Point the mail at `doctype`/`name`, or at nothing. The row is not written yet, so `validate_reference`,
	`set_status` and the realtime push all see the new target."""
	doc.update({"reference_doctype": doctype, "reference_name": name, "reference_owner": None})


def route_before_insert(doc, method=None) -> None:
	"""`before_insert` hook on Communication. Never raises: an error is logged (class name only) and treated
	as UNCHECKED, so a failed check cannot let her back in as a lead."""
	if doc.sent_or_received != "Received" or doc.communication_type != "Communication":
		return
	route = UNCHECKED
	with _isolated(TITLE):
		route = _route(doc)
	doc.flags.privacy_route = route


def finish_routing(doc) -> bool:
	"""Called first from `on_communication_insert`. True when the mail was routed and must not start a lead.
	A detached mail also tells Compliance, at most once a day per sender."""
	route = doc.flags.get("privacy_route")
	if route == DETACHED:
		with _isolated(f"{TITLE}: notice"):
			_notify_once(doc)
	return route is not None


def _notify_once(doc) -> None:
	key = f"{NOTICE_KEY}::{digest_of('email', sender_address(doc))}"
	if frappe.cache.get_value(key):
		return
	notify_compliance(
		_("An email from an erased person arrived. Open it to decide what to do."), "Communication", doc.name
	)
	frappe.cache.set_value(key, 1, expires_in_sec=NOTICE_SECONDS)
