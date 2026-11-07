# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Rows outside the CRM records that name her (phase 05 step 1): notification, queued mail, WhatsApp, event,
failed sync log, data import. Part of `add_activity`."""

import frappe
from frappe.utils import now


def misc_rows(p) -> dict:
	"""Rows outside the CRM records that name her: notification, queued mail, WhatsApp, event, sync log, import."""
	out = frappe._dict()
	out.notification = (
		frappe.get_doc(
			{
				"doctype": "CRM Notification",
				"type": "Mention",
				"to_user": p.rep,
				"from_user": "Administrator",
				"message": "Marisol Vega (m.vega@example.com) replied",
				"notification_text": "Marisol Vega replied",
				"reference_doctype": "CRM Lead",
				"reference_name": p.lead,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
	out.email_queue = (
		frappe.get_doc(
			{
				"doctype": "Email Queue",
				"sender": p.rep_email,
				"message": "Hello Marisol Vega at m.vega@example.com",
				"status": "Not Sent",
				"recipients": [{"recipient": p.email}],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
	out.wa_message = _whatsapp(p)
	out.event = (
		frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Call with Marisol Vega",
				"description": "Discuss the plan with Marisol Vega",
				"starts_on": now(),
				"event_type": "Private",
				"event_participants": [
					{"reference_doctype": "Contact", "reference_docname": p.contact, "email": p.email}
				],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
	out.failed_sync = (
		frappe.get_doc(
			{
				"doctype": "Failed Lead Sync Log",
				"type": "Failure",
				"lead_data": frappe.as_json({"full_name": "Marisol Vega", "email": p.email}),
			}
		)
		.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)
		.name
	)
	out.data_import = (
		frappe.get_doc(
			{"doctype": "Data Import", "reference_doctype": "CRM Lead", "import_type": "Insert New Records"}
		)
		.insert(ignore_permissions=True)
		.name
	)
	return out


def _whatsapp(p) -> str:
	account = frappe.get_doc(
		{
			"doctype": "WA Account",
			"account_name": f"Fixture {frappe.generate_hash(length=5)}",
			"status": "Active",
			"phone_id": frappe.generate_hash(length=8),
		}
	).insert(ignore_permissions=True)
	profile = frappe.get_doc(
		{
			"doctype": "WA Profile",
			"whatsapp_account": account.name,
			"phone_number": p.phone,
			"profile_name": "Marisol",
			"links": [{"link_doctype": "CRM Lead", "link_name": p.lead}],
		}
	).insert(ignore_permissions=True)
	return (
		frappe.get_doc(
			{
				"doctype": "WA Message",
				"direction": "Incoming",
				"whatsapp_account": account.name,
				"to": profile.name,
				"from": p.phone,
				"message": "Hi, it is Marisol on +1 530 555 0101",
				"reference_doctype": "CRM Lead",
				"reference_docname": p.lead,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
