# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The outcome email (design 5.10): Compliance answers the requester from the request.

Compliance holds no permission on Communication (that would open every mailbox), so the standard `make` refuses
them. This is the one narrow way through: the caller is Compliance by an explicit role row, the request is Erased or
Declined and not frozen, and every recipient is one of the request's own non-excluded email identifiers. The
Communication is linked to the request, and only to it, so closing scrubs it and waits for its Email Queue row
(phase 06) while no Contact, Lead or Deal timeline shows it.
"""

import frappe
from frappe import _
from frappe.core.doctype.communication.email import _make

from crm.privacy.erasure.approval import load, require_compliance
from crm.privacy.identifiers import normalize_email
from crm.privacy.request_status import DECLINED, ERASED, assert_not_frozen
from crm.privacy.request_visibility import DOCTYPE


def allowed_recipients(doc) -> set[str]:
	return {
		normalize_email(row.normalized or row.value)
		for row in doc.identifiers
		if row.kind == "Email" and not row.excluded
	}


def checked_recipients(doc, recipients) -> list[str]:
	"""The recipients as clean addresses; anything that is not one of the request's own addresses is refused."""
	if not isinstance(recipients, list) or not recipients:
		frappe.throw(_("Choose at least one recipient"))
	allowed = allowed_recipients(doc)
	cleaned = []
	for recipient in recipients:
		address = normalize_email(recipient) if isinstance(recipient, str) else ""
		if address not in allowed:
			frappe.throw(_("The outcome email can only go to the requester's own email addresses"))
		if address not in cleaned:
			cleaned.append(address)
	return cleaned


def drop_other_timeline_links(communication: str, request: str) -> None:
	"""Saving the email links it to every Contact (and through it Lead or Deal) that holds a recipient's address, and
	to the sender's own Contact. Their timelines would show the answer to a person who is not Compliance, and on a
	Declined request the requester's Contact still exists. Only the link to the request stays."""
	frappe.db.delete(
		"Communication Link",
		{
			"parent": communication,
			"parenttype": "Communication",
			"link_doctype": ["!=", DOCTYPE],
		},
	)
	frappe.db.delete(
		"Communication Link",
		{"parent": communication, "parenttype": "Communication", "link_name": ["!=", request]},
	)


def send(name: str, subject: str, content: str, recipients, user: str) -> dict:
	"""Create the email on the request and queue it. Returns `{name}` of the Communication."""
	require_compliance(user, _("send the outcome email of"))
	doc = load(name)
	if doc.status not in (ERASED, DECLINED):
		frappe.throw(_("The outcome email is sent once the request is Erased or Declined"))
	assert_not_frozen(doc.erasure_job_status)
	to = checked_recipients(doc, recipients)
	if not (subject or "").strip() or not (content or "").strip():
		frappe.throw(_("The outcome email needs a subject and a message"))
	result = _make(
		doctype=DOCTYPE,
		name=name,
		subject=subject.strip(),
		content=content,
		recipients=to,
		sender_full_name=frappe.db.get_value("User", user, "full_name"),
		send_email=True,
		add_signature=False,
	)
	drop_other_timeline_links(result["name"], name)
	return {"name": result["name"]}
