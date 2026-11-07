# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What the phase 05 review found missing from the Marisol scenario: a colleague on the deals with history, words
that coincide with hers, Versions of notes/to-dos/events, search rows, route history, user settings, a deleted
note, mail and WhatsApp leftovers. Part of `add_activity`."""

import frappe

from crm.privacy.tests.erasure_fixture_files import file_doc

COLLEAGUE_NAME = "Jon Park"


def version(doctype: str, name: str, data: dict) -> str:
	doc = frappe.get_doc(
		{"doctype": "Version", "ref_doctype": doctype, "docname": name, "data": frappe.as_json(data)}
	)
	return doc.insert(ignore_permissions=True).name


def coincidences(p) -> None:
	"""Her gender, salutation and job title are also the colleague's deal's: words, not her."""
	for doctype, name in (("Gender", "Female"), ("Salutation", "Ms")):
		if not frappe.db.exists(doctype, name):
			frappe.get_doc({"doctype": doctype, doctype.lower(): name}).insert(ignore_permissions=True)
	frappe.db.set_value("CRM Lead", p.lead, {"gender": "Female", "salutation": "Ms"})
	same = {"gender": "Female", "salutation": "Ms", "job_title": "Practice manager"}
	for deal in (p.copy_deal, p.won):
		frappe.db.set_value("CRM Deal", deal, same)


def colleague_history(p) -> dict:
	"""Versions of the deals she is on or was removed from, with the colleague and her in the contacts table."""
	k = {
		"contact": p.colleague,
		"full_name": COLLEAGUE_NAME,
		"email": p.colleague_email,
		"mobile_no": "+15305550177",
	}
	hers = {"contact": p.contact, "full_name": "Marisol Vega", "email": p.email, "mobile_no": p.phone}
	data = {
		"changed": [["email", "jon.old@sierra.example.com", p.colleague_email], ["email", "", p.email]],
		"added": [["contacts", {**k, "idx": 2}], ["contacts", {**hers, "idx": 1}]],
		"removed": [["contacts", {**hers, "idx": 1}]],
		"row_changed": [
			["contacts", 2, "colleague-row", [["email", "jon.p@sierra.example.com", p.colleague_email]]]
		],
	}
	return {"colleague_version_removed": version("CRM Deal", p.removed, data),
		"colleague_version_won": version("CRM Deal", p.won, data)}  # fmt: skip


def activity_versions(p, notes, misc) -> dict:
	return {
		"version_note": version("FCRM Note", notes.note_lead, {"changed": [["content", "Marisol (+1 530 555 0101) asked", "x"]]}),
		"version_todo": version("ToDo", notes.todo_lead, {"changed": [["description", f"Send {p.email} the quote", "x"]]}),
		"version_event": version("Event", misc.event, {"changed": [["subject", "Call with Marisol Vega", "Call"]]}),
	}  # fmt: skip


def search_rows(p, notes, misc) -> list[tuple]:
	"""Frappe's global search holds name and email of a contact, an address, a to-do and an event."""
	rows = [
		("Contact", p.contact, "Marisol Vega ||| m.vega@example.com"),
		("Address", p.address, "Marisol Vega ||| 1 Foothill Road ||| Chico"),
		("ToDo", notes.todo_lead, "Send Marisol the quote"),
		("Event", misc.event, "Call with Marisol Vega"),
		("Contact", p.colleague, "Jon Park ||| jon.park@sierra.example.com"),
	]
	for doctype, name, content in rows:
		frappe.db.sql(
			"replace into `__global_search` (doctype, name, title, content, route, published) values (%s, %s, %s, %s, '', 0)",
			(doctype, name, name, content),
		)
	return [(d, n) for d, n, _c in rows]


def route_and_settings(p) -> dict:
	for route in ("app/contact/Marisol%20Vega", "Form/Contact/Marisol Vega", "app/contact/Jon%20Park"):
		frappe.get_doc({"doctype": "Route History", "route": route, "user": p.rep}).insert(
			ignore_permissions=True
		)
	filters = '{"filters": [["CRM Lead", "email", "=", "m.vega@example.com"]]}'
	for user, data in (
		(p.rep, filters),
		("Administrator", '{"filters": [["CRM Lead", "status", "=", "New"]]}'),
	):
		frappe.db.sql(
			"insert into `__UserSettings` (`user`, `doctype`, `data`) values (%s, 'CRM Lead', %s)",
			(user, data),
		)
	return {"settings_user": p.rep}


def deleted_note(p) -> str:
	"""A note a rep wrote about her and deleted: Frappe kept a copy that names no email and no phone."""
	note = frappe.get_doc({"doctype": "FCRM Note", "title": "Gone", "content": "She said no to the plan",
		"reference_doctype": "CRM Lead", "reference_docname": p.lead}).insert(ignore_permissions=True)  # fmt: skip
	frappe.delete_doc("FCRM Note", note.name, force=True, ignore_permissions=True)
	return frappe.get_all("Deleted Document", {"deleted_name": note.name}, pluck="name")[0]


def leftovers(p, misc) -> dict:
	"""Queued mail with her address in `show_as_cc`, `attachments` and `error`; a WhatsApp message with media."""
	frappe.db.set_value("Email Queue", misc.email_queue, {
		"show_as_cc": f"{p.email}, {p.colleague_email}",
		"attachments": '[{"fname": "quote-for-marisol.pdf", "fcontent": "AAAA"}]',
		"error": f"550 5.1.1 <{p.email}>: mailbox full",
	})  # fmt: skip
	frappe.db.set_value("WA Message", misc.wa_message, {
		"attach": "/private/files/voice-marisol.ogg",
		"media_url": "https://wa.example/media/123",
		"template_body_parameters": '["Marisol"]',
	})  # fmt: skip
	return {"wa_file": file_doc("WA Message", misc.wa_message, "voice-marisol.txt").name}


def add_extras(p, out) -> dict:
	coincidences(p)
	extras = {**colleague_history(p), **activity_versions(p, out.notes, out.misc)}
	extras["search"] = search_rows(p, out.notes, out.misc)
	extras.update(route_and_settings(p), deleted_note=deleted_note(p), **leftovers(p, out.misc))
	return frappe._dict(extras)
