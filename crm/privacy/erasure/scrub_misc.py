# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Step 8: rows outside the records that name her, and the notices about the request itself (design 5.6, RT-10).

Free text becomes the content placeholder; her identifiers inside structured data become the person placeholder;
WhatsApp rows lose their link to her records; the On Hold notices and their queued mail are deleted.
"""

import frappe

from crm.privacy.erasure import scrub_traces
from crm.privacy.erasure.plan import ErasurePlan
from crm.privacy.erasure.scrub_context import ScrubContext, blank, put
from crm.privacy.erasure.scrub_json import blank_text_values
from crm.privacy.erasure.text_mentions import mentions_identifier
from crm.privacy.erasure.value_matcher import (
	has_address,
	holds_her_value,
	replace_addresses,
	same_phone,
)

HER_RECORDS = (("CRM Lead", "leads"), ("Contact", "contacts"), ("CRM Deal", "deals_on"),
	("CRM Deal", "deals_copy"), ("CRM Deal", "deals_removed"))  # fmt: skip


def scrub_notifications(plan: ErasurePlan, ctx: ScrubContext) -> None:
	for name in plan.targets["crm_notifications"]:
		put("CRM Notification", name, {"message": ctx.content, "notification_text": ctx.content})
	for name in plan.targets["notification_logs"]:
		fields = ("subject", "title", "description", "email_content")
		put("Notification Log", name, dict.fromkeys(fields, ctx.content))


def scrub_queued_mail(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""The message text, inline attachments (print attachments are stored in the row) and the SMTP error text; her
	address as sender, as a recipient and inside the CC list (other addresses of the list stay)."""
	emails = list(plan.identifiers.emails)
	for name in plan.targets["email_queues"]:
		row = frappe.db.get_value("Email Queue", name, ["sender", "show_as_cc", "error"], as_dict=True)
		values = {"message": ctx.content, **blank("attachments")}
		if row.sender in emails:
			values["sender"] = ctx.person
		if has_address(row.show_as_cc, emails):
			values["show_as_cc"] = replace_addresses(row.show_as_cc, emails, ctx.person)
		if row.error:
			values["error"] = ctx.content
		put("Email Queue", name, values)
		if emails:
			frappe.db.set_value(
				"Email Queue Recipient",
				{"parent": name, "recipient": ["in", emails]},
				"recipient",
				ctx.person,
				update_modified=False,
			)


def scrub_whatsapp(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""Messages lose their text, her number and any reference to her records (the WhatsApp app would otherwise
	re-link the number to her old lead); profiles lose their name, number and links."""
	her = {(doctype, name) for doctype, kind in HER_RECORDS for name in plan.targets[kind]}
	for name in plan.targets["wa_messages"]:
		row = frappe.db.get_value(
			"WA Message", name, ["from", "reference_doctype", "reference_docname"], as_dict=True
		)
		values = {"message": ctx.content, **blank("attach", "media_url", "template_body_parameters")}
		if same_phone(row["from"], plan.identifiers.phones):
			values["from"] = ctx.person
		if (row.reference_doctype, row.reference_docname) in her:
			values.update(blank("reference_doctype", "reference_docname"))
		put("WA Message", name, values)
	for name in plan.targets["wa_profiles"]:
		put("WA Profile", name, {"profile_name": ctx.person, "phone_number": ctx.person, "wa_id": None})
	if plan.targets["wa_profiles"]:
		frappe.db.delete(
			"Dynamic Link", {"parenttype": "WA Profile", "parent": ["in", plan.targets["wa_profiles"]]}
		)


def scrub_structured(plan: ErasurePlan, ctx: ScrubContext) -> None:
	"""Event participants lose their address (blank: a placeholder is not an address a reminder could mail); a failed
	sync log is one rejected lead, hers, so every text in it goes (her name sits beside her email); enrichment
	changes lose her identifiers wherever they are a whole value."""
	for name in plan.targets["event_participants"]:
		put("Event Participants", name, blank("email"))
	for name in plan.targets["failed_sync_logs"]:
		data, trace = frappe.db.get_value("Failed Lead Sync Log", name, ["lead_data", "traceback"])
		values = {"lead_data": blank_text_values(data, ctx.person)}
		if mentions_identifier(trace, plan.identifiers):
			values["traceback"] = ctx.content
		put("Failed Lead Sync Log", name, values)
	for name in plan.targets["enrichment_changes"]:
		old, new = frappe.db.get_value("CRM Enrichment Run Change", name, ["old_value", "new_value"])
		values = {
			field: ctx.person for field, value in (("old_value", old), ("new_value", new))
			if holds_her_value(value, plan.identifiers)
		}  # fmt: skip
		put("CRM Enrichment Run Change", name, values)


def delete_notices(plan: ErasurePlan) -> None:
	"""Rows the privacy module wrote about this request (RT-10): the owner notices name her in their context."""
	if plan.targets["hold_notifications"]:
		frappe.db.delete("CRM Notification", {"name": ["in", plan.targets["hold_notifications"]]})
	if plan.targets["hold_notification_logs"]:
		frappe.db.delete("Notification Log", {"name": ["in", plan.targets["hold_notification_logs"]]})
	queued = plan.targets["hold_emails"]
	if queued:
		frappe.db.delete("Email Queue Recipient", {"parent": ["in", queued]})
		frappe.db.delete("Email Queue", {"name": ["in", queued]})


def scrub(plan: ErasurePlan, ctx: ScrubContext) -> None:
	scrub_notifications(plan, ctx)
	scrub_queued_mail(plan, ctx)
	scrub_whatsapp(plan, ctx)
	scrub_structured(plan, ctx)
	scrub_traces.scrub(plan, ctx)
	delete_notices(plan)
