"""What an erasure request would remove, worked out from its confirmed matches and identifiers.

`plan_erasure` only reads. The erasure job runs the plan and the approval screen shows
`preview(plan)`. Error text here never carries the person's name, email or phone.
"""

from dataclasses import dataclass
from email.utils import getaddresses

import frappe
from frappe.query_builder import Criterion

from crm.privacy.identifiers import normalize_email, normalize_identifier, personal_fields
from crm.privacy.matching import (
	CONTACT,
	DEAL,
	LEAD,
	addresses_in_text,
	confirmed_names,
	identifier_values,
	like_escape,
	phone_rows,
	record_title,
)

DOCTYPE = "CRM Erasure Request"
EMAIL_COLUMNS = ("sender", "recipients", "cc", "bcc")
RECORDINGS_ITEM = "Delete recordings at provider (Twilio)"

# What her_values reads from a confirmed lead and contact. Keys line up with
# rules.DEAL_FIELD_SOURCES, which compares deal fields against them.
LEAD_VALUE_FIELDS = (
	"first_name",
	"last_name",
	"middle_name",
	"salutation",
	"gender",
	"linkedin",
	"twitter",
	"facebook",
	"lead_name",
	"job_title",
)
CONTACT_VALUE_FIELDS = (
	"first_name",
	"last_name",
	"middle_name",
	"salutation",
	"gender",
	"full_name",
	"designation",
)

CUSTOM_FIELD_DOCTYPES = (LEAD, DEAL, CONTACT)
CUSTOM_FIELD_TYPES = ("Data", "Small Text", "Text", "Long Text", "Phone", "Attach", "Attach Image", "Text Editor")


@dataclass
class ErasurePlan:
	request: str
	emails: set[str]  # confirmed, non-excluded, normalized
	phones: set[str]
	leads: list[str]  # confirmed
	contacts: list[str]  # confirmed
	deals_on: list[str]  # confirmed deals listing a confirmed contact, or whose email/mobile/phone is hers
	deals_removed: list[str]  # other confirmed deals
	addresses: list[str]  # Address linked (Dynamic Link or Contact.address) to confirmed contacts
	communications: list[str]
	call_logs: list[str]
	notes: list[str]  # on records + notes linked from those call logs
	tasks: list[str]
	comments: list[str]
	files: list[str]  # File names
	has_recordings: bool
	her_values: dict[str, set[str]]  # case-folded name/title/social values from confirmed leads+contacts


def _unique(names) -> list[str]:
	"""`names` as strings, without duplicates, in first-seen order."""
	return list(dict.fromkeys(str(name) for name in names if name not in (None, "")))


def _on_records(doctype: str, doctype_field: str, name_field: str, records: dict[str, list[str]]) -> list[str]:
	"""Names of `doctype` rows pointing at any of `records` ({doctype: [names]})."""
	found: list[str] = []
	for record_doctype, names in records.items():
		if names:
			found += frappe.get_all(
				doctype, filters={doctype_field: record_doctype, name_field: ["in", names]}, pluck="name"
			)
	return found


def _parents_linked(parent_doctype: str, child_doctype: str, doctype_field: str, name_field: str, records) -> list[str]:
	"""Parents of `child_doctype` link rows (doctype_field, name_field) that point at `records`."""
	found: list[str] = []
	for record_doctype, names in records.items():
		if names:
			found += frappe.get_all(
				child_doctype,
				filters={
					"parenttype": parent_doctype,
					doctype_field: record_doctype,
					name_field: ["in", names],
				},
				pluck="parent",
				parent_doctype=parent_doctype,
			)
	return found


def _header_has_email(header: str | None, emails: set[str]) -> bool:
	"""True when one of the addresses in the header is in `emails`, as `replace_addresses` reads it."""
	parsed = [addr for name, addr in getaddresses([header or ""]) if name or addr]
	if not parsed:
		return bool(addresses_in_text(header) & emails)
	return any(normalize_email(addr) in emails for addr in parsed)


def _communications_with_emails(emails: set[str]) -> list[str]:
	table = frappe.qb.DocType("Communication")
	found: list[str] = []
	for email in sorted(emails):
		rows = (
			frappe.qb.from_(table)
			.select(table.name, *[getattr(table, column) for column in EMAIL_COLUMNS])
			.where(Criterion.any([getattr(table, column).like(f"%{like_escape(email)}%") for column in EMAIL_COLUMNS]))
			.run(as_dict=True)
		)
		found += [
			row.name for row in rows if any(_header_has_email(row.get(column), {email}) for column in EMAIL_COLUMNS)
		]
	return found


def _her_values(leads: list[str], contacts: list[str]) -> dict[str, set[str]]:
	values: dict[str, set[str]] = {}
	for doctype, names, fields in ((LEAD, leads, LEAD_VALUE_FIELDS), (CONTACT, contacts, CONTACT_VALUE_FIELDS)):
		for name in names:
			row = frappe.db.get_value(doctype, name, list(fields), as_dict=True) or {}
			for field in fields:
				value = row.get(field)
				if isinstance(value, str) and value.strip():
					values.setdefault(field, set()).add(value.strip().casefold())
	return values


def _deals_split(
	deals: list[str], contacts: list[str], emails: set[str], phones: set[str]
) -> tuple[list[str], list[str]]:
	"""(deals she is still on, other deals), each in the order of `deals`."""
	if not deals:
		return [], []
	on: set[str] = set()
	if contacts:
		on.update(
			frappe.get_all(
				"CRM Contacts",
				filters={"parenttype": DEAL, "parent": ["in", deals], "contact": ["in", contacts]},
				pluck="parent",
				parent_doctype=DEAL,
			)
		)
	for row in frappe.get_all(DEAL, filters={"name": ["in", deals]}, fields=["name", "email", "mobile_no", "phone"]):
		if normalize_identifier("Email", row.email) in emails or any(
			normalize_identifier("Phone", row.get(column)) in phones for column in ("mobile_no", "phone")
		):
			on.add(row.name)
	return [d for d in deals if d in on], [d for d in deals if d not in on]


def _contact_addresses(contacts: list[str]) -> list[str]:
	if not contacts:
		return []
	found = _parents_linked("Address", "Dynamic Link", "link_doctype", "link_name", {CONTACT: contacts})
	found += [a for a in frappe.get_all(CONTACT, filters={"name": ["in", contacts]}, pluck="address") if a]
	return [a for a in _unique(found) if frappe.db.exists("Address", a)]


def plan_erasure(request) -> ErasurePlan:
	"""The plan for a request, given as a document or its name."""
	doc = request if hasattr(request, "matches") else frappe.get_doc(DOCTYPE, request)

	emails: set[str] = set()
	phones: set[str] = set()
	for kind, value in identifier_values(doc):
		(emails if kind == "Email" else phones).add(value)

	leads = _unique(confirmed_names(doc, LEAD))
	contacts = _unique(confirmed_names(doc, CONTACT))
	deals_on, deals_removed = _deals_split(_unique(confirmed_names(doc, DEAL)), contacts, emails, phones)
	records = {LEAD: leads, CONTACT: contacts, DEAL: deals_on}

	communications = _on_records("Communication", "reference_doctype", "reference_name", records)
	communications += _parents_linked("Communication", "Communication Link", "link_doctype", "link_name", records)
	communications += _communications_with_emails(emails)
	communications = _unique(communications)

	call_logs = _on_records("CRM Call Log", "reference_doctype", "reference_docname", records)
	call_logs += _parents_linked("CRM Call Log", "Dynamic Link", "link_doctype", "link_name", records)
	for phone in sorted(phones):
		call_logs += [row.name for row in phone_rows("CRM Call Log", ["from", "to"], phone)]
	call_logs = _unique(call_logs)

	notes = _on_records("FCRM Note", "reference_doctype", "reference_docname", records)
	has_recordings = False
	if call_logs:
		logs = frappe.get_all("CRM Call Log", filters={"name": ["in", call_logs]}, fields=["note", "recording_url"])
		notes += [log.note for log in logs]
		has_recordings = any((log.recording_url or "").strip() for log in logs)

	files = _on_records("File", "attached_to_doctype", "attached_to_name", {**records, "Communication": communications})
	images = [
		image
		for doctype, names in ((LEAD, leads), (CONTACT, contacts))
		if names
		for image in frappe.get_all(doctype, filters={"name": ["in", names]}, pluck="image")
		if image
	]
	if images:
		# Stored files are shared by content hash, so a File with her image URL may belong to
		# another record (an organization logo, a stock avatar). Only unattached ones are hers;
		# those attached to her leads and contacts are already in `files` above.
		files += frappe.get_all(
			"File",
			filters={"file_url": ["in", _unique(images)], "attached_to_doctype": ["is", "not set"]},
			pluck="name",
		)

	return ErasurePlan(
		request=doc.name,
		emails=emails,
		phones=phones,
		leads=leads,
		contacts=contacts,
		deals_on=deals_on,
		deals_removed=deals_removed,
		addresses=_contact_addresses(contacts),
		communications=communications,
		call_logs=call_logs,
		notes=_unique(notes),
		tasks=_unique(_on_records("CRM Task", "reference_doctype", "reference_docname", records)),
		comments=_unique(_on_records("Comment", "reference_doctype", "reference_name", records)),
		files=_unique(files),
		has_recordings=has_recordings,
		her_values=_her_values(leads, contacts),
	)


def unlisted_custom_fields() -> list[dict]:
	"""Text-like custom fields on lead, deal and contact that the personal fields list does not cover."""
	listed = personal_fields()
	rows = frappe.get_all(
		"Custom Field",
		filters={"dt": ["in", CUSTOM_FIELD_DOCTYPES], "fieldtype": ["in", CUSTOM_FIELD_TYPES]},
		fields=["dt", "fieldname", "label"],
		order_by="dt asc, fieldname asc",
	)
	return [
		{"dt": row.dt, "fieldname": row.fieldname, "label": row.label}
		for row in rows
		if row.fieldname not in listed.get(row.dt, set())
	]


def _links(doctype: str, names: list[str]) -> list[dict]:
	return [{"doctype": doctype, "name": name, "title": record_title(doctype, name)} for name in names]


def _address_links(names: list[str]) -> list[dict]:
	return [
		{"doctype": "Address", "name": name, "title": frappe.db.get_value("Address", name, "address_title") or name}
		for name in names
	]


def _organization_links(plan: ErasurePlan) -> list[dict]:
	organizations: list[str] = []
	if plan.leads:
		organizations += frappe.get_all(LEAD, filters={"name": ["in", plan.leads]}, pluck="organization")
	deals = plan.deals_on + plan.deals_removed
	if deals:
		organizations += frappe.get_all(DEAL, filters={"name": ["in", deals]}, pluck="organization")
	links = []
	for name in _unique(organizations):
		title = frappe.db.get_value("CRM Organization", name, "organization_name")
		if title is not None:
			links.append({"doctype": "CRM Organization", "name": name, "title": title or name})
	return links


def preview(plan: ErasurePlan) -> dict:
	"""What the approver sees: what goes, what stays, and what needs a second look."""
	remove = [
		{"kind": "Leads", "count": len(plan.leads), "links": _links(LEAD, plan.leads)},
		{"kind": "Contacts", "count": len(plan.contacts), "links": _links(CONTACT, plan.contacts)},
		{"kind": "Deals (still on)", "count": len(plan.deals_on), "links": _links(DEAL, plan.deals_on)},
		{"kind": "Addresses", "count": len(plan.addresses), "links": _address_links(plan.addresses)},
		{"kind": "Emails", "count": len(plan.communications)},
		{"kind": "Calls", "count": len(plan.call_logs)},
		{"kind": "Notes", "count": len(plan.notes)},
		{"kind": "Tasks", "count": len(plan.tasks)},
		{"kind": "Comments", "count": len(plan.comments)},
		{"kind": "Files", "count": len(plan.files)},
	]

	keep = [
		{"label": "Organizations", "links": _organization_links(plan)},
		{"label": "Deal values, status and stage", "links": []},
		{
			"label": "Open deals she was removed from (their notes, tasks, comments and files stay)",
			"links": _links(DEAL, plan.deals_removed),
		},
		{"label": "Lead and deal records as anonymized shells", "links": []},
		{"label": "Email, call and note records as placeholders", "links": []},
	]
	if frappe.db.get_value(DOCTYPE, plan.request, "contract_references"):
		keep.append({"label": "Retained-contract entry", "links": []})

	items = frappe.get_all(
		"CRM Erasure Checklist Item",
		filters={"parent": plan.request, "parenttype": DOCTYPE},
		fields=["description", "done"],
		order_by="idx asc",
		parent_doctype=DOCTYPE,
	)
	open_checklist = [item.description for item in items if not item.done]
	# The erasure adds this item when recordings exist, so show it before approval.
	if plan.has_recordings and RECORDINGS_ITEM not in [item.description for item in items]:
		open_checklist.append(RECORDINGS_ITEM)
	return {
		"remove": remove,
		"keep": keep,
		"warnings": {"open_checklist": open_checklist, "unlisted_custom_fields": unlisted_custom_fields()},
	}
