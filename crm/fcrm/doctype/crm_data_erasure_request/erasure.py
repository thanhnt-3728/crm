# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Erase one person's personal data from the CRM.

The person is identified from a Lead and/or a Contact. Their footprint is resolved to
every lead, contact and deal that belongs to them, then:

- Leads and Deals are kept and de-identified in place, so every dashboard number
  (lead counts, conversion, time to close, pipeline, revenue) stays the same.
- Every note, comment, task, email, WhatsApp message, notification and assignment on
  those leads and deals keeps its record, but its text is replaced with
  "Content erased <request>".
- Contacts are personal records (their name is the docname), so they are deleted
  permanently, without a copy in Deleted Document.
- Organizations are never touched.

Everything runs in the caller's transaction, so a failure leaves nothing half-erased.
"""

from dataclasses import dataclass, field

import frappe
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Lower

ERASED_EMAIL = "erased@erased.invalid"

# Lead fields that describe the person. Company fields (organization, website,
# industry, company_description, ...) stay, because the company is not the subject.
LEAD_PERSONAL_FIELDS = (
	"salutation",
	"middle_name",
	"last_name",
	"gender",
	"email",
	"mobile_no",
	"phone",
	"image",
	"job_title",
	"linkedin",
	"twitter",
	"facebook",
	"facebook_lead_id",
	"facebook_form_id",
)

# Deal fields copied from the person when the deal was created from their lead.
DEAL_PERSONAL_FIELDS = (
	"salutation",
	"first_name",
	"last_name",
	"gender",
	"job_title",
)

# Child rows in Version.data can hold old personal values, so versions of these
# activity records are removed together with their content.
ACTIVITY_DOCTYPES = ("FCRM Note", "CRM Task", "Comment", "Communication", "CRM Call Log")


@dataclass
class Subject:
	leads: set[str] = field(default_factory=set)
	contacts: set[str] = field(default_factory=set)
	deals: set[str] = field(default_factory=set)
	emails: set[str] = field(default_factory=set)
	phones: set[str] = field(default_factory=set)
	names: set[str] = field(default_factory=set)

	@property
	def parents(self) -> list[tuple[str, str]]:
		"""(doctype, name) of every lead and deal whose activity belongs to the person."""
		return [("CRM Lead", n) for n in sorted(self.leads)] + [("CRM Deal", n) for n in sorted(self.deals)]


def resolve_subject(lead: str | None = None, contact: str | None = None) -> Subject:
	"""Find every lead, contact and deal that belongs to the person.

	Starts from the given lead/contact, collects their email addresses and phone numbers,
	then pulls in the other leads and contacts that share one of those email addresses
	(for example the contact created when the lead was converted). Deals are the ones
	created from those leads or that list one of those contacts.
	"""
	subject = Subject()
	if lead:
		subject.leads.add(lead)
	if contact:
		subject.contacts.add(contact)

	_collect_identifiers(subject)

	if subject.emails:
		subject.leads.update(_leads_with_emails(subject.emails))
		subject.contacts.update(
			frappe.get_all(
				"Contact Email",
				filters={"email_id": ("in", list(subject.emails)), "parenttype": "Contact"},
				pluck="parent",
			)
		)
		_collect_identifiers(subject)

	subject.deals = _deals_for(subject)
	return subject


def _collect_identifiers(subject: Subject) -> None:
	for row in frappe.get_all(
		"CRM Lead",
		filters={"name": ("in", list(subject.leads))},
		fields=["email", "mobile_no", "phone", "lead_name", "first_name", "last_name"],
	):
		_add(subject.emails, row.email, lower=True)
		_add(subject.phones, row.mobile_no, row.phone)
		_add(subject.names, row.lead_name, _join(row.first_name, row.last_name))

	for row in frappe.get_all(
		"Contact",
		filters={"name": ("in", list(subject.contacts))},
		fields=["name", "email_id", "mobile_no", "phone", "full_name", "first_name", "last_name"],
	):
		_add(subject.emails, row.email_id, lower=True)
		_add(subject.phones, row.mobile_no, row.phone)
		_add(subject.names, row.full_name, _join(row.first_name, row.last_name))

	if subject.contacts:
		contacts = list(subject.contacts)
		_add(
			subject.emails,
			*frappe.get_all(
				"Contact Email", filters={"parent": ("in", contacts), "parenttype": "Contact"}, pluck="email_id"
			),
			lower=True,
		)
		_add(
			subject.phones,
			*frappe.get_all(
				"Contact Phone", filters={"parent": ("in", contacts), "parenttype": "Contact"}, pluck="phone"
			),
		)


def _leads_with_emails(emails: set[str]) -> list[str]:
	Lead = frappe.qb.DocType("CRM Lead")
	return (
		frappe.qb.from_(Lead)
		.select(Lead.name)
		.where(Lower(Lead.email).isin(list(emails)))
		.run(pluck=True)
	)


def _deals_for(subject: Subject) -> set[str]:
	deals = set()
	if subject.leads:
		deals.update(frappe.get_all("CRM Deal", filters={"lead": ("in", list(subject.leads))}, pluck="name"))
	if subject.contacts:
		contacts = list(subject.contacts)
		deals.update(frappe.get_all("CRM Deal", filters={"contact": ("in", contacts)}, pluck="name"))
		deals.update(
			frappe.get_all(
				"CRM Contacts",
				filters={"contact": ("in", contacts), "parenttype": "CRM Deal"},
				pluck="parent",
			)
		)
	return deals


def preview(subject: Subject) -> dict:
	"""Counts of what an erasure would touch, for the approver to check before running it."""
	activity = _activity_names(subject)
	return {
		"leads": sorted(subject.leads),
		"deals": sorted(subject.deals),
		"contacts": sorted(subject.contacts),
		"counts": {doctype: len(names) for doctype, names in activity.items()},
	}


def erase(subject: Subject, request: str) -> dict:
	"""Erase the person's data. Returns how many records of each kind were changed."""
	marker = f"Content erased {request}"
	summary: dict[str, int] = {}
	activity = _activity_names(subject)

	# Activity first: the deal/lead fields used to find it are wiped below.
	summary.update(_erase_activity(activity, subject, marker))
	summary["Version"] = _delete_versions(subject, activity)
	summary["CRM Deal"] = _anonymize_deals(subject, marker)
	summary["CRM Lead"] = _anonymize_leads(subject, marker)
	summary["Contact"] = _delete_contacts(subject)
	summary["Email Queue"] = _delete_email_queue(subject)
	summary["Deleted Document"] = _purge_deleted_documents(subject)

	_reindex_search_after_commit(activity)
	return {k: v for k, v in summary.items() if v}


# Activity -------------------------------------------------------------------------


def _activity_names(subject: Subject) -> dict[str, list[str]]:
	parents = subject.parents
	parent_names = [name for _, name in parents]

	def on_parents(doctype, dt_field, dn_field):
		if not parents:
			return []
		return frappe.get_all(
			doctype,
			filters={dt_field: ("in", ["CRM Lead", "CRM Deal"]), dn_field: ("in", parent_names)},
			pluck="name",
		)

	activity = {
		"FCRM Note": on_parents("FCRM Note", "reference_doctype", "reference_docname"),
		"CRM Task": on_parents("CRM Task", "reference_doctype", "reference_docname"),
		"Comment": on_parents("Comment", "reference_doctype", "reference_name"),
		"Communication": sorted(
			set(on_parents("Communication", "reference_doctype", "reference_name"))
			| _emails_with_person(subject)
		),
		"CRM Call Log": sorted(
			set(on_parents("CRM Call Log", "reference_doctype", "reference_docname"))
			| _call_logs_linked_to(parent_names)
			| _call_logs_with_phones(subject.phones)
		),
		"CRM Notification": on_parents("CRM Notification", "reference_doctype", "reference_name"),
		"ToDo": on_parents("ToDo", "reference_type", "reference_name"),
	}
	if frappe.db.exists("DocType", "WA Message"):
		activity["WA Message"] = on_parents("WA Message", "reference_doctype", "reference_docname")
	return activity


def _emails_with_person(subject: Subject) -> set[str]:
	"""Emails on the person's contacts, or that they sent or received anywhere in the CRM."""
	names: set[str] = set()
	if subject.contacts:
		contacts = list(subject.contacts)
		names.update(
			frappe.get_all(
				"Communication",
				filters={"reference_doctype": "Contact", "reference_name": ("in", contacts)},
				pluck="name",
			)
		)
		names.update(
			frappe.get_all(
				"Communication Link",
				filters={"link_doctype": "Contact", "link_name": ("in", contacts), "parenttype": "Communication"},
				pluck="parent",
			)
		)
	if subject.emails:
		Comm = frappe.qb.DocType("Communication")
		conditions = [Lower(Comm.sender).isin(list(subject.emails))]
		for email in subject.emails:
			pattern = f"%{email}%"
			conditions += [Comm.recipients.like(pattern), Comm.cc.like(pattern), Comm.bcc.like(pattern)]
		names.update(frappe.qb.from_(Comm).select(Comm.name).where(Criterion.any(conditions)).run(pluck=True))
	return names


def _call_logs_linked_to(parent_names: list[str]) -> set[str]:
	if not parent_names:
		return set()
	return set(
		frappe.get_all(
			"Dynamic Link",
			filters={
				"parenttype": "CRM Call Log",
				"link_doctype": ("in", ["CRM Lead", "CRM Deal"]),
				"link_name": ("in", parent_names),
			},
			pluck="parent",
		)
	)


def _call_logs_with_phones(phones: set[str]) -> set[str]:
	if not phones:
		return set()
	numbers = list(phones)
	return set(frappe.get_all("CRM Call Log", filters={"from": ("in", numbers)}, pluck="name")) | set(
		frappe.get_all("CRM Call Log", filters={"to": ("in", numbers)}, pluck="name")
	)


def _erase_activity(activity: dict[str, list[str]], subject: Subject, marker: str) -> dict[str, int]:
	text_fields = {
		"FCRM Note": {"title": marker, "content": marker},
		"CRM Task": {"title": marker, "description": marker},
		"Comment": {"subject": marker, "content": marker},
		"CRM Notification": {"message": marker, "notification_text": marker},
		"ToDo": {"description": marker},
		"WA Message": {
			"message": marker,
			"attach": None,
			"media_url": None,
			"template_body_parameters": None,
			"template_header_parameters": None,
		},
	}
	for doctype, values in text_fields.items():
		_set(doctype, activity.get(doctype), values)

	_erase_communications(activity["Communication"], subject, marker)
	_erase_call_logs(activity["CRM Call Log"], subject)
	return {doctype: len(names) for doctype, names in activity.items()}


def _erase_communications(names: list[str], subject: Subject, marker: str) -> None:
	if not names:
		return
	_set(
		"Communication",
		names,
		{"subject": marker, "content": marker, "text_content": None, "has_attachment": 0},
	)

	# The records stay, but the person's address must not.
	rows = frappe.get_all(
		"Communication",
		filters={"name": ("in", names)},
		fields=["name", "sender", "sender_full_name", "recipients", "cc", "bcc", "phone_no"],
	)
	for row in rows:
		values = {}
		if row.sender and row.sender.strip().lower() in subject.emails:
			values.update(sender=ERASED_EMAIL, sender_full_name=None)
		for fieldname in ("recipients", "cc", "bcc"):
			scrubbed = scrub_addresses(row.get(fieldname), subject.emails)
			if scrubbed != row.get(fieldname):
				values[fieldname] = scrubbed
		if row.phone_no and row.phone_no in subject.phones:
			values["phone_no"] = None
		if values:
			frappe.db.set_value("Communication", row.name, values, update_modified=False)

	_delete_files_attached_to("Communication", names)


def _erase_call_logs(names: list[str], subject: Subject) -> None:
	if not names:
		return
	_set("CRM Call Log", names, {"recording_url": None})
	for fieldname in ("from", "to"):
		frappe.db.set_value(
			"CRM Call Log",
			{"name": ("in", names), fieldname: ("in", list(subject.phones) or [""])},
			fieldname,
			None,
			update_modified=False,
		)


def scrub_addresses(value: str | None, emails: set[str]) -> str | None:
	"""Replace the person's addresses in a comma-separated address list."""
	if not value:
		return value
	out = []
	for part in value.split(","):
		address = part.strip()
		if not address:
			continue
		bare = address.rsplit("<", 1)[-1].rstrip(">").strip().lower()
		out.append(ERASED_EMAIL if bare in emails else address)
	return ", ".join(out)


# Versions -------------------------------------------------------------------------


def _delete_versions(subject: Subject, activity: dict[str, list[str]]) -> int:
	Version = frappe.qb.DocType("Version")
	conditions = []
	if subject.leads:
		conditions.append((Version.ref_doctype == "CRM Lead") & Version.docname.isin(list(subject.leads)))
	for doctype in ACTIVITY_DOCTYPES:
		if activity.get(doctype):
			conditions.append((Version.ref_doctype == doctype) & Version.docname.isin(activity[doctype]))

	# Deal history is kept for everything except the changes that recorded the person's details.
	needles = [v for v in subject.emails | subject.phones | subject.names if v]
	if subject.deals and needles:
		conditions.append(
			(Version.ref_doctype == "CRM Deal")
			& Version.docname.isin(list(subject.deals))
			& Criterion.any([Version.data.like(f"%{n}%") for n in needles])
		)

	if not conditions:
		return 0
	names = frappe.qb.from_(Version).select(Version.name).where(Criterion.any(conditions)).run(pluck=True)
	if names:
		frappe.db.delete("Version", {"name": ("in", names)})
	return len(names)


# Deals, leads, contacts -----------------------------------------------------------


def _anonymize_deals(subject: Subject, marker: str) -> int:
	contacts = subject.contacts
	for name in sorted(subject.deals):
		deal = frappe.db.get_value(
			"CRM Deal", name, ["lead", "email", "lost_notes", "next_step"], as_dict=True
		)
		values = {}

		if contacts:
			frappe.db.delete(
				"CRM Contacts",
				{"parent": name, "parenttype": "CRM Deal", "contact": ("in", list(contacts))},
			)
		values.update(_primary_contact_values(name))

		copied_from_person = deal.lead in subject.leads or (deal.email or "").lower() in subject.emails
		if copied_from_person:
			values.update(dict.fromkeys(DEAL_PERSONAL_FIELDS))
			values["lead_name"] = marker
		if deal.lost_notes:
			values["lost_notes"] = marker
		if deal.next_step:
			values["next_step"] = marker

		frappe.db.set_value("CRM Deal", name, values, update_modified=False)
	return len(subject.deals)


def _primary_contact_values(deal: str) -> dict:
	"""Re-derive the deal's primary contact from the contacts left on it."""
	rows = frappe.get_all(
		"CRM Contacts",
		filters={"parent": deal, "parenttype": "CRM Deal"},
		fields=["name", "contact", "email", "mobile_no", "phone", "is_primary"],
		order_by="idx asc",
	)
	if not rows:
		return {"contact": None, "email": None, "mobile_no": None, "phone": None}

	primary = next((r for r in rows if r.is_primary), None)
	if not primary:
		primary = rows[0]
		frappe.db.set_value("CRM Contacts", primary.name, "is_primary", 1, update_modified=False)
	return {
		"contact": primary.contact,
		"email": (primary.email or "").strip(),
		"mobile_no": (primary.mobile_no or "").strip(),
		"phone": (primary.phone or "").strip(),
	}


def _anonymize_leads(subject: Subject, marker: str) -> int:
	leads = sorted(subject.leads)
	for name in leads:
		lost_notes = frappe.db.get_value("CRM Lead", name, "lost_notes")
		values = dict.fromkeys(LEAD_PERSONAL_FIELDS)
		# first_name is mandatory, and lead_name is the title shown in lists and search.
		values.update(first_name="Erased", lead_name=marker)
		if lost_notes:
			values["lost_notes"] = marker
		frappe.db.set_value("CRM Lead", name, values, update_modified=False)
	_delete_files_attached_to("CRM Lead", leads)
	return len(leads)


def _delete_contacts(subject: Subject) -> int:
	contacts = sorted(subject.contacts)
	if not contacts:
		return 0

	# Addresses that belong to nobody else go with the person.
	addresses = set(
		frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Address", "link_doctype": "Contact", "link_name": ("in", contacts)},
			pluck="parent",
		)
	)
	shared = set(
		frappe.get_all(
			"Dynamic Link",
			filters={
				"parenttype": "Address",
				"parent": ("in", list(addresses) or [""]),
				"link_name": ("not in", contacts),
			},
			pluck="parent",
		)
	)

	_delete_files_attached_to("Contact", contacts)
	for name in contacts:
		frappe.delete_doc(
			"Contact", name, force=True, ignore_permissions=True, delete_permanently=True
		)
	for name in sorted(addresses - shared):
		frappe.delete_doc("Address", name, force=True, ignore_permissions=True, delete_permanently=True)
	return len(contacts)


def _delete_files_attached_to(doctype: str, names: list[str]) -> None:
	if not names:
		return
	for file in frappe.get_all(
		"File", filters={"attached_to_doctype": doctype, "attached_to_name": ("in", names)}, pluck="name"
	):
		frappe.delete_doc("File", file, force=True, ignore_permissions=True, delete_permanently=True)


def _delete_email_queue(subject: Subject) -> int:
	"""Queued and sent outgoing mail keeps the full message, so drop the person's."""
	if not subject.emails:
		return 0
	queue = set(
		frappe.get_all(
			"Email Queue Recipient",
			filters={"recipient": ("in", list(subject.emails))},
			pluck="parent",
		)
	)
	if not queue:
		return 0
	frappe.db.delete("Email Queue Recipient", {"parent": ("in", list(queue))})
	frappe.db.delete("Email Queue", {"name": ("in", list(queue))})
	return len(queue)


def _purge_deleted_documents(subject: Subject) -> int:
	"""Copies of the person's records deleted earlier (a duplicate lead, say) live on here."""
	Deleted = frappe.qb.DocType("Deleted Document")
	conditions = [Deleted.data.like(f"%{email}%") for email in subject.emails]
	if subject.contacts:
		conditions.append(
			(Deleted.deleted_doctype == "Contact") & Deleted.deleted_name.isin(list(subject.contacts))
		)
	if not conditions:
		return 0
	names = frappe.qb.from_(Deleted).select(Deleted.name).where(Criterion.any(conditions)).run(pluck=True)
	if names:
		frappe.db.delete("Deleted Document", {"name": ("in", names)})
	return len(names)


# Search ---------------------------------------------------------------------------


def _reindex_search_after_commit(activity: dict[str, list[str]]) -> None:
	"""The writes above skip document hooks, so refresh the search index by hand."""
	docs = [(dt, n) for dt in ("Comment", "FCRM Note", "Communication") for n in activity.get(dt, [])]
	if not docs:
		return

	def reindex():
		from crm.search_sqlite import CRMSearch

		search = CRMSearch()
		if not search.is_search_enabled() or not search.index_exists():
			return
		for doctype, name in docs:
			# Erased text is not worth indexing; dropping it keeps old words from matching.
			search.remove_doc(doctype, name)

	frappe.db.after_commit.add(reindex)


# Helpers --------------------------------------------------------------------------


def _set(doctype: str, names: list[str] | None, values: dict) -> None:
	if names:
		frappe.db.set_value(doctype, {"name": ("in", names)}, values, update_modified=False)


def _add(target: set[str], *values, lower: bool = False) -> None:
	for value in values:
		value = (value or "").strip()
		if value:
			target.add(value.lower() if lower else value)


def _join(*parts) -> str:
	return " ".join(p for p in parts if p)
