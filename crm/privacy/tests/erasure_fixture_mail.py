# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Her emails and calls in the Marisol scenario: five emails and three calls are hers, the rest are not."""

import frappe

from crm.privacy.tests.erasure_fixture_files import file_doc
from crm.privacy.tests.inbound_helpers import incoming_email, make_email_account

REC_URL = "https://api.twilio.example/Recordings/RE0001"


def mail(p, sender, reference=None, **values):
	doc = incoming_email(sender, p.account, recipients=values.pop("recipients", p.rep_email), **values)
	if reference:
		doc.reference_doctype, doc.reference_name = reference
	doc.insert(ignore_permissions=True)
	return doc.name


def communications(p) -> dict:
	"""Five emails that are hers (by link or by address) and three that are not."""
	account = p.account = make_email_account(create_lead=0)
	del account
	c = frappe._dict()
	c.mail_lead = mail(
		p,
		"Marisol Vega <M.Vega@example.com>",
		("CRM Lead", p.lead),
		cc=p.colleague_email,
		subject="Proposal for Sierra Foothills",
		content="Marisol here, number is 530 555 0101.",
	)
	c.mail_contact = mail(
		p,
		p.rep_email,
		("Contact", p.contact),
		sent_or_received="Sent",
		recipients="Marisol Vega <marisol.vega@gmail.example>",
		subject="Follow up",
		content="Hi Marisol",
	)
	c.mail_won = mail(p, "m.vega@example.com", ("CRM Deal", p.won), subject="Contract", content="Signed")
	c.mail_removed = mail(
		p, "m.vega@example.com", ("CRM Deal", p.removed), subject="Pricing", content="Question"
	)
	c.mail_loose = mail(p, "marisol.vega@gmail.example", subject="Hello", content="Anyone there?")
	c.mail_colleague = mail(p, p.colleague_email, ("CRM Deal", p.removed), subject="Internal", content="FYI")
	c.mail_lookalike = mail(p, "adam.vega@example.com", subject="Different person", content="Hello")
	c.mail_shared = mail(p, p.shared_email, subject="Shared inbox", content="Office mail")
	c.mail_copy_deal = mail(
		p, p.colleague_email, ("CRM Deal", p.copy_deal), subject="Deal copy", content="Kept"
	)
	c.attachment = file_doc("Communication", c.mail_lead, "proposal-email.txt").name
	return c


def calls(p) -> dict:
	"""Two calls that are hers, one on the removed-from deal, one lookalike number; the first has a recording and a note."""
	note = frappe.get_doc(
		{"doctype": "FCRM Note", "title": "Call note", "content": "<p>She asked about the dental plan</p>"}
	).insert(ignore_permissions=True)

	def log(number, direction="Incoming", **values):
		values[("from" if direction == "Incoming" else "to")] = number
		values[("to" if direction == "Incoming" else "from")] = "+15305559999"
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Call Log",
					"id": frappe.generate_hash(length=10),
					"type": direction,
					"status": "Completed",
					"telephony_medium": "Manual",
					**values,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	return frappe._dict(
		call_note=note.name,
		call_recorded=log(
			p.phone,
			reference_doctype="CRM Lead",
			reference_docname=p.lead,
			recording_url=REC_URL,
			note=note.name,
		),
		call_by_number=log("530-555-0103"),
		call_removed=log(p.phone, "Outgoing", reference_doctype="CRM Deal", reference_docname=p.removed),
		call_lookalike=log(p.lookalike_phone),
	)
