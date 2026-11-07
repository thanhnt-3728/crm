# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The activity half of the Marisol scenario (phase 05 step 1): what hangs off her records.

`add_activity(p)` runs after the records exist and BEFORE the request is logged, because a request that is open
re-routes the mail that arrives afterwards (phase 04). It returns the names it made as a dict.
"""

import frappe

from crm.api.contact import add_deal_version
from crm.privacy.tests.erasure_fixture_extras import add_extras
from crm.privacy.tests.erasure_fixture_files import file_doc, jpeg
from crm.privacy.tests.erasure_fixture_mail import calls, communications
from crm.privacy.tests.erasure_fixture_misc import misc_rows


def notes_and_tasks(p) -> dict:
	"""A note, a task, a comment and a to-do on her lead, contact and Won deal, and on the two deals kept."""
	out = frappe._dict()
	for key, doctype, name in (
		("lead", "CRM Lead", p.lead),
		("contact", "Contact", p.contact),
		("won", "CRM Deal", p.won),
		("removed", "CRM Deal", p.removed),
		("copy", "CRM Deal", p.copy_deal),
	):
		out[f"note_{key}"] = (
			frappe.get_doc(
				{
					"doctype": "FCRM Note",
					"title": f"Note on {key}",
					"content": f"Marisol likes Tuesdays ({key})",
					"reference_doctype": doctype,
					"reference_docname": name,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		out[f"task_{key}"] = (
			frappe.get_doc(
				{
					"doctype": "CRM Task",
					"title": f"Task on {key}",
					"description": f"Call Marisol ({key})",
					"status": "Todo",
					"reference_doctype": doctype,
					"reference_docname": name,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		out[f"comment_{key}"] = (
			frappe.get_doc(doctype, name).add_comment("Comment", f"Marisol agreed ({key})").name
		)
		out[f"todo_{key}"] = (
			frappe.get_doc(
				{
					"doctype": "ToDo",
					"description": f"Send Marisol the quote ({key})",
					"allocated_by": "Administrator",
					"allocated_to": p.rep,
					"reference_type": doctype,
					"reference_name": name,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return out


def files_and_history(p) -> dict:
	"""Files on her lead, Won deal, contact (photo) and the removed-from deal; Versions and a deleted lead."""
	out = frappe._dict(
		photo=file_doc("Contact", p.contact, "marisol.jpg", private=0, content=jpeg()).name,
		file_lead=file_doc("CRM Lead", p.lead, "lead-card.txt").name,
		file_won=file_doc("CRM Deal", p.won, "proposal-for-marisol.txt").name,
		file_removed=file_doc("CRM Deal", p.removed, "price-list.txt").name,
	)
	frappe.db.set_value("Contact", p.contact, "image", frappe.db.get_value("File", out.photo, "file_url"))
	add_deal_version(p.won, [["email", "old@example.com", p.email], ["mobile_no", "", p.phone]])
	add_deal_version(p.removed, [["email", "", p.email]])
	out.version_won_status = _version("CRM Deal", p.won, {"changed": [["status", "Qualification", "Won"]]})
	out.version_lead = _version(
		"CRM Lead", p.lead, {"changed": [["job_title", "Manager", "Practice manager"]]}
	)
	out.version_contact = _version(
		"Contact", p.contact, {"added": [["email_ids", {"email_id": p.email, "idx": 1}]]}
	)
	second = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": "Marisol",
			"last_name": "Vega",
			"email": p.email,
			"mobile_no": p.phone,
		}
	).insert(ignore_permissions=True)
	frappe.delete_doc("CRM Lead", second.name, force=True, ignore_permissions=True)
	out.deleted_lead = second.name
	return out


def _version(doctype: str, name: str, data: dict) -> str:
	return (
		frappe.get_doc(
			{"doctype": "Version", "ref_doctype": doctype, "docname": name, "data": frappe.as_json(data)}
		)
		.insert(ignore_permissions=True)
		.name
	)


def add_activity(p) -> frappe._dict:
	out = frappe._dict(communications=communications(p), calls=calls(p))
	out.notes = notes_and_tasks(p)
	out.history = files_and_history(p)
	out.misc = misc_rows(p)
	out.extras = add_extras(p, out)
	return out
