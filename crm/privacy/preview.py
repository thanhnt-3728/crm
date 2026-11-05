"""What an erasure request will erase and what it will leave alone (spec 5.6).

`collect_targets` is the one definition of "everything that will be erased". The approval
screen (`get_erasure_preview`) and the erasure job both build on it, so what Compliance
approves is what gets erased.
"""

from dataclasses import dataclass, field

import frappe
from frappe import _
from frappe.utils import strip_html_tags

from crm.privacy import personal_fields
from crm.privacy.matching import (
	active_identifiers,
	call_logs_matching,
	communications_matching,
	confirmed,
)

REQUEST = "CRM Erasure Request"

TWILIO_CHECKLIST_ITEM = "Delete recordings at provider (Twilio)"

# Custom field types that can hold personal data.
PERSONAL_FIELD_TYPES = ("Data", "Small Text", "Text", "Phone", "Attach Image")
CUSTOM_FIELD_DOCTYPES = ("CRM Lead", "CRM Deal", "Contact")


@dataclass
class Targets:
	"""Names of the documents an erasure request will erase, by kind. Every list is sorted
	and free of repeats.

	"Erased records" are `leads`, `contacts` and `deals_still_on`. `deals_removed_from` are
	confirmed deals she was taken off while the request was On Hold: only their emails and
	calls that name her are erased, nothing else on the deal."""

	leads: list[str] = field(default_factory=list)
	contacts: list[str] = field(default_factory=list)
	addresses: list[str] = field(default_factory=list)
	deals_still_on: list[str] = field(default_factory=list)
	deals_removed_from: list[str] = field(default_factory=list)
	communications: list[str] = field(default_factory=list)
	call_logs: list[str] = field(default_factory=list)
	notes: list[str] = field(default_factory=list)
	tasks: list[str] = field(default_factory=list)
	comments: list[str] = field(default_factory=list)
	files: list[str] = field(default_factory=list)
	wa_messages: list[str] = field(default_factory=list)
	recordings_present: bool = False

	def erased_records(self) -> dict[str, list[str]]:
		"""The leads, contacts and deals she is still on, by doctype."""
		return {"CRM Lead": self.leads, "Contact": self.contacts, "CRM Deal": self.deals_still_on}


# -- Collecting targets ------------------------------------------------------------------


def _sorted(names) -> list[str]:
	return sorted({name for name in names if name})


def _by_reference(doctype: str, doctype_field: str, name_field: str, records: dict) -> set[str]:
	"""Names of the `doctype` documents whose reference fields point at one of `records`
	(a {doctype: [names]} mapping)."""
	found = set()
	for reference_doctype, names in records.items():
		if not names:
			continue
		found.update(
			frappe.get_all(
				doctype,
				filters={doctype_field: reference_doctype, name_field: ["in", names]},
				pluck="name",
			)
		)
	return found


def _by_link_rows(child: str, parent_doctype: str, records: dict) -> set[str]:
	"""Names of the `parent_doctype` documents with a `child` link row (Communication Link or
	Dynamic Link) to one of `records`."""
	found = set()
	for link_doctype, names in records.items():
		if not names:
			continue
		found.update(
			frappe.get_all(
				child,
				filters={
					"parenttype": parent_doctype,
					"link_doctype": link_doctype,
					"link_name": ["in", names],
				},
				pluck="parent",
				parent_doctype=parent_doctype,
			)
		)
	return found


def _images(doctype: str, names: list[str]) -> set[str]:
	if not names:
		return set()
	return {url for url in frappe.get_all(doctype, filters={"name": ["in", names]}, pluck="image") if url}


def _has_recording(call_logs: list[str]) -> bool:
	if not call_logs:
		return False
	return bool(frappe.db.count("CRM Call Log", {"name": ["in", call_logs], "recording_url": ["is", "set"]}))


def collect_targets(request) -> Targets:
	"""Everything the request will erase, from its confirmed matches and active identifiers."""
	deals = [
		row
		for row in request.matches
		if row.confirmed and row.reference_doctype == "CRM Deal" and row.reference_name
	]
	targets = Targets(
		leads=_sorted(confirmed(request, "CRM Lead")),
		contacts=_sorted(confirmed(request, "Contact")),
		deals_still_on=_sorted(row.reference_name for row in deals if not row.removed_from_open_deal),
		deals_removed_from=_sorted(row.reference_name for row in deals if row.removed_from_open_deal),
	)
	erased = targets.erased_records()
	emails = active_identifiers(request, "Email")
	phones = active_identifiers(request, "Phone")

	# Emails: linked to an erased record, or naming an active identifier anywhere.
	communications = _by_reference("Communication", "reference_doctype", "reference_name", erased)
	communications |= _by_link_rows("Communication Link", "Communication", erased)
	communications |= communications_matching(emails, phones)
	targets.communications = _sorted(communications)

	# Calls: linked to an erased record, or from/to an active phone anywhere.
	call_logs = _by_reference("CRM Call Log", "reference_doctype", "reference_docname", erased)
	call_logs |= _by_link_rows("Dynamic Link", "CRM Call Log", erased)
	call_logs |= call_logs_matching(phones)
	targets.call_logs = _sorted(call_logs)
	targets.recordings_present = _has_recording(targets.call_logs)

	# Notes also come from the calls they were written on.
	notes = _by_reference("FCRM Note", "reference_doctype", "reference_docname", erased)
	if targets.call_logs:
		notes.update(
			frappe.get_all(
				"CRM Call Log",
				filters={"name": ["in", targets.call_logs], "note": ["is", "set"]},
				pluck="note",
			)
		)
	targets.notes = _sorted(notes)
	targets.tasks = _sorted(_by_reference("CRM Task", "reference_doctype", "reference_docname", erased))
	targets.comments = _sorted(_by_reference("Comment", "reference_doctype", "reference_name", erased))

	# Files attached to erased records or to their emails, and the photos on leads/contacts.
	attached_to = {**erased, "Communication": targets.communications}
	files = _by_reference("File", "attached_to_doctype", "attached_to_name", attached_to)
	images = _images("CRM Lead", targets.leads) | _images("Contact", targets.contacts)
	if images:
		files.update(frappe.get_all("File", filters={"file_url": ["in", list(images)]}, pluck="name"))
	targets.files = _sorted(files)

	if targets.contacts:
		targets.addresses = _sorted(_by_link_rows("Dynamic Link", "Address", {"Contact": targets.contacts}))

	if frappe.db.table_exists("WA Message"):
		targets.wa_messages = _sorted(
			_by_reference(
				"WA Message",
				"reference_doctype",
				"reference_docname",
				{"CRM Lead": targets.leads, "CRM Deal": targets.deals_still_on},
			)
		)

	return targets


# -- The approval screen -----------------------------------------------------------------

# kind -> (doctype, the Targets attribute holding the names, columns the label is built from)
KINDS = {
	"Lead": ("CRM Lead", "leads", ("lead_name",)),
	"Deal": ("CRM Deal", "deals_still_on", ("organization",)),
	"Contact": ("Contact", "contacts", ("full_name",)),
	"Address": ("Address", "addresses", ("address_title",)),
	"Email": ("Communication", "communications", ("subject",)),
	"Call": ("CRM Call Log", "call_logs", ("type", "from", "to")),
	"Note": ("FCRM Note", "notes", ("title",)),
	"Task": ("CRM Task", "tasks", ("title",)),
	"Comment": ("Comment", "comments", ("content",)),
	"File": ("File", "files", ("file_name",)),
	"WhatsApp": ("WA Message", "wa_messages", ()),
}


def _label(kind: str, name: str, row) -> str:
	"""A short line that tells Compliance which record this is."""
	if kind == "Call":
		return " ".join(part for part in (row.type, f"{row['from'] or '?'} → {row['to'] or '?'}") if part)
	if kind == "Comment":
		text = strip_html_tags(row.content or "").strip()
		return (text[:80] + "…") if len(text) > 80 else text or name
	if kind == "Deal":
		return f"{name} ({row.organization})" if row.organization else name
	if kind == "Email":
		return row.subject or name
	columns = KINDS[kind][2]
	return (row[columns[0]] if columns else None) or name


def _rows(doctype: str, names: list[str], columns) -> dict:
	table = frappe.qb.DocType(doctype)
	rows = (
		frappe.qb.from_(table)
		.select(table.name, *[table[column] for column in columns])
		.where(table.name.isin(names))
		.run(as_dict=True)
	)
	return {row.name: row for row in rows}


def _remove_list(targets: Targets) -> list[dict]:
	remove = []
	for kind, (doctype, attribute, columns) in KINDS.items():
		names = getattr(targets, attribute)
		if not names:
			continue
		rows = _rows(doctype, names, columns)
		for name in names:
			row = rows.get(name) or frappe._dict()
			remove.append({"kind": kind, "doctype": doctype, "name": name, "label": _label(kind, name, row)})
	return remove


def _organizations(targets: Targets) -> list[str]:
	"""Organizations named on the erased leads and on every confirmed deal."""
	names = set()
	for doctype, records in (
		("CRM Lead", targets.leads),
		("CRM Deal", targets.deals_still_on + targets.deals_removed_from),
	):
		if records:
			names.update(frappe.get_all(doctype, filters={"name": ["in", records]}, pluck="organization"))
	return _sorted(names)


def _kept_on_removed_deals(targets: Targets) -> list[dict]:
	"""For each open deal she was removed from: its notes, tasks, comments and files that are
	not being erased (notes of her calls and files of her emails are)."""
	erased = {
		"FCRM Note": set(targets.notes),
		"CRM Task": set(targets.tasks),
		"Comment": set(targets.comments),
		"File": set(targets.files),
	}
	kept = []
	for deal in targets.deals_removed_from:
		records = {"CRM Deal": [deal]}
		count = sum(
			len(found - erased[doctype])
			for doctype, found in (
				("FCRM Note", _by_reference("FCRM Note", "reference_doctype", "reference_docname", records)),
				("CRM Task", _by_reference("CRM Task", "reference_doctype", "reference_docname", records)),
				("Comment", _by_reference("Comment", "reference_doctype", "reference_name", records)),
				("File", _by_reference("File", "attached_to_doctype", "attached_to_name", records)),
			)
		)
		if count:
			kept.append(
				{
					"label": _("Notes, tasks, comments and files of {0} ({1})").format(deal, count),
					"reason": _(
						"She was removed from this open deal, so only her emails and calls are erased."
					),
				}
			)
	return kept


def _keep_list(request, targets: Targets) -> list[dict]:
	keep = []

	for organization in _organizations(targets):
		keep.append(
			{
				"label": _("Organization: {0}").format(organization),
				"reason": _("A business record, not personal data."),
			}
		)

	if targets.deals_still_on or targets.deals_removed_from:
		keep.append(
			{
				"label": _("Deal values, status and stage"),
				"reason": _(
					"Business figures; they don't identify her, and dashboard numbers must not change."
				),
			}
		)

	shells = []
	if targets.leads:
		shells.append(_("{0} lead(s)").format(len(targets.leads)))
	if targets.deals_still_on:
		shells.append(_("{0} deal(s)").format(len(targets.deals_still_on)))
	if shells:
		keep.append(
			{
				"label": _("Anonymized shells: {0}").format(", ".join(shells)),
				"reason": _("The records stay with their personal fields blanked, so pipeline counts hold."),
			}
		)
	if targets.contacts:
		keep.append(
			{
				"label": _("Anonymized contact(s): {0}").format(len(targets.contacts)),
				"reason": _("The records stay with their personal fields blanked, so deal links hold."),
			}
		)

	placeholders = []
	if targets.communications:
		placeholders.append(_("{0} email(s)").format(len(targets.communications)))
	if targets.call_logs:
		placeholders.append(_("{0} call(s)").format(len(targets.call_logs)))
	if targets.notes:
		placeholders.append(_("{0} note(s)").format(len(targets.notes)))
	if targets.tasks:
		placeholders.append(_("{0} task(s)").format(len(targets.tasks)))
	if targets.comments:
		placeholders.append(_("{0} comment(s)").format(len(targets.comments)))
	if placeholders:
		keep.append(
			{
				"label": _("Placeholder records: {0}").format(", ".join(placeholders)),
				"reason": _(
					"The records stay with their content replaced, so activity history keeps its shape."
				),
			}
		)

	keep.extend(_kept_on_removed_deals(targets))

	if (request.contract_references or "").strip():
		keep.append(
			{
				"label": _("Retained contract: name and reference {0}").format(
					request.contract_references.strip()
				),
				"reason": _("Signed contract or order exception; kept until the retention period ends."),
			}
		)

	return keep


def _open_checklist(request, targets: Targets) -> list[str]:
	items = [row.description for row in request.checklist if not row.done and row.description]
	if targets.recordings_present and TWILIO_CHECKLIST_ITEM not in items:
		# Erasure adds this item; show it now so approval is made knowing about it.
		items.append(TWILIO_CHECKLIST_ITEM)
	return items


def _unlisted_custom_fields() -> list[dict]:
	"""Custom fields on lead, deal and contact that could hold personal data but are not on
	the personal fields list, so erasure would leave them alone."""
	rows = frappe.get_all(
		"Custom Field",
		filters={"dt": ["in", CUSTOM_FIELD_DOCTYPES], "fieldtype": ["in", PERSONAL_FIELD_TYPES]},
		fields=["dt", "fieldname", "label"],
		order_by="dt, fieldname",
	)
	listed = {doctype: personal_fields(doctype) for doctype in CUSTOM_FIELD_DOCTYPES}
	return [
		{"doctype": row.dt, "fieldname": row.fieldname, "label": row.label or row.fieldname}
		for row in rows
		if row.fieldname not in listed[row.dt]
	]


def get_erasure_preview(request_name: str) -> dict:
	"""The approval screen: what will be removed, what will be kept, the open checklist
	items and the custom fields erasure doesn't know about."""
	request = frappe.get_doc(REQUEST, request_name)
	request.check_permission("read")

	targets = collect_targets(request)
	remove = _remove_list(targets)
	counts = {kind: 0 for kind in KINDS}
	for item in remove:
		counts[item["kind"]] += 1

	return {
		"remove": remove,
		"counts": counts,
		"keep": _keep_list(request, targets),
		"open_checklist": _open_checklist(request, targets),
		"unlisted_custom_fields": _unlisted_custom_fields(),
		"recordings_present": targets.recordings_present,
	}
