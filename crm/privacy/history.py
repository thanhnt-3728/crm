"""The last erasure step: her change history, deleted copies, do-not-contact entries and the
retained-contract entry.

Runs inside `run_erasure` after `erase_records` (which renamed her contacts and addresses,
keeping the old names in `plan.former_names`) and `sweep_activities`. Being last, it also
catches any Version written while the earlier steps ran. Writes go through
`frappe.db.set_value(..., update_modified=False)` and `frappe.db.delete`; the only inserts
are new CRM Do Not Contact and CRM Retained Contract rows, neither of which tracks changes.
"""

import json
from collections.abc import Callable, Iterable
from typing import Any

import frappe
from frappe.model.document import Document
from frappe.query_builder import Criterion
from frappe.utils import add_months, cint, today

from crm.privacy.identifiers import (
	PHONE_REGION,
	add_do_not_contact,
	normalize_email,
	normalize_identifier,
	personal_fields,
)
from crm.privacy.matching import _digits, like_escape
from crm.privacy.plan import ErasurePlan
from crm.privacy.rules import erased_person, scrub_version_data
from crm.privacy.sweep import _holds_identifier
from crm.utils import phone_search_digits

SETTINGS = "CRM Privacy Settings"
LEAD, DEAL, CONTACT, ADDRESS = "CRM Lead", "CRM Deal", "Contact", "Address"
NOTE, TASK, CALL_LOG = "FCRM Note", "CRM Task", "CRM Call Log"
# Child tables of a contact or a deal whose fields count as hers in a lead's or contact's history.
PERSONAL_CHILD_TABLES = ("Contact Email", "Contact Phone", "CRM Contacts")
# Her values that are categories rather than identifying text: matched only in the same field.
CATEGORY_KEYS = ("salutation", "gender")
# Deleted copies of these doctypes are purged when they hold her email or phone.
DELETED_DOCTYPES = (LEAD, CONTACT, DEAL, "Communication", ADDRESS, NOTE, TASK, "Comment", CALL_LOG)
CHUNK = 500

Predicate = Callable[[str, Any], bool]


def _chunks(names: Iterable[str]) -> Iterable[list[str]]:
	names = list(dict.fromkeys(name for name in names if name))
	for start in range(0, len(names), CHUNK):
		yield names[start : start + CHUNK]


# --- whose value is it -------------------------------------------------------------------


def _is_hers(plan: ErasurePlan) -> Predicate:
	"""`(field, value) -> bool`: the value is one of hers.

	Her names, titles and social handles compare stripped and case-folded (salutation and
	gender only in the field of that name); the old names of her renamed contacts and
	addresses count too. Emails and phones compare normalized, and text that quotes one of
	them counts as hers. Empty values never match.
	"""
	words = {value for key, values in plan.her_values.items() if key not in CATEGORY_KEYS for value in values}
	words |= {name.strip().casefold() for names in plan.former_names.values() for name in names if name}
	categories = {key: plan.her_values.get(key, set()) for key in CATEGORY_KEYS}

	def check(field: str, value: Any) -> bool:
		if not isinstance(value, str) or not value.strip():
			return False
		text = value.strip()
		folded = text.casefold()
		if folded in words or folded in categories.get(field, ()):
			return True
		if "@" in text and normalize_email(text) in plan.emails:
			return True
		if (
			plan.phones
			and any(ch.isdigit() for ch in text)
			and normalize_identifier("Phone", text) in plan.phones
		):
			return True
		# Text quoting her email or phone (a note field, a header) is replaced whole.
		return _holds_identifier(text, plan)

	return check


def _personal_or_hers(doctype: str, listed: dict[str, set[str]], hers: Predicate) -> Predicate:
	"""For her own leads and contacts: every set personal field, and any value that is hers."""
	fields = set(listed.get(doctype, set()))
	for child in PERSONAL_CHILD_TABLES:
		fields |= listed.get(child, set())

	def check(field: str, value: Any) -> bool:
		if field in fields and value:  # empty values stay, so a blank is still visibly blank
			return True
		return hers(field, value)

	return check


# --- Version -----------------------------------------------------------------------------


def _scrub_rows(
	doctype: str, names: Iterable[str], should_scrub: Predicate, placeholder: str, plan: ErasurePlan
) -> None:
	"""Rewrite the `data` of each Version of the named records.

	A row whose data cannot be parsed as a JSON object, or that still holds her email or
	phone after scrubbing (in a part of unexpected shape), is deleted: it is history of her
	record that cannot be cleaned field by field.
	"""
	for chunk in _chunks(names):
		rows = frappe.get_all(
			"Version", filters={"ref_doctype": doctype, "docname": ["in", chunk]}, fields=["name", "data"]
		)
		doomed: list[str] = []
		for row in rows:
			if not row.data:
				continue
			try:
				data = json.loads(row.data)
			except (TypeError, ValueError):
				doomed.append(row.name)
				continue
			if not isinstance(data, dict):
				doomed.append(row.name)
				continue
			scrubbed = scrub_version_data(data, should_scrub, placeholder)
			text = frappe.as_json(scrubbed, indent=None, separators=(",", ":"))
			if _holds_identifier(text, plan):
				doomed.append(row.name)
			elif scrubbed != data:
				frappe.db.set_value("Version", row.name, "data", text, update_modified=False)
		if doomed:
			frappe.db.delete("Version", {"name": ["in", doomed]})


def _delete_versions(doctype: str, names: Iterable[str]) -> None:
	for chunk in _chunks(names):
		frappe.db.delete("Version", {"ref_doctype": doctype, "docname": ["in", chunk]})


def scrub_versions(plan: ErasurePlan) -> None:
	"""Her values out of the change history of her records.

	Leads and contacts: every personal field and every value of hers. Deals she is or was
	on, and her call logs: only values that are hers, so other people's details and the
	deal's own history stay. Notes, tasks, addresses, emails and comments were wiped as a
	whole, so their history goes.
	"""
	placeholder = erased_person(plan.request)
	listed = personal_fields()
	hers = _is_hers(plan)
	contacts = [*plan.contacts, *plan.former_names.get(CONTACT, [])]
	addresses = [*plan.addresses, *plan.former_names.get(ADDRESS, [])]

	_scrub_rows(LEAD, plan.leads, _personal_or_hers(LEAD, listed, hers), placeholder, plan)
	_scrub_rows(CONTACT, contacts, _personal_or_hers(CONTACT, listed, hers), placeholder, plan)
	_scrub_rows(DEAL, [*plan.deals_on, *plan.deals_removed], hers, placeholder, plan)
	_scrub_rows(CALL_LOG, plan.call_logs, hers, placeholder, plan)

	for doctype, names in (
		(NOTE, plan.notes),
		(TASK, plan.tasks),
		(ADDRESS, addresses),
		("Communication", plan.communications),
		("Comment", plan.comments),
	):
		_delete_versions(doctype, names)


# --- Deleted Document ----------------------------------------------------------------------


def purge_deleted_documents(plan: ErasurePlan) -> None:
	"""Delete the kept copies of deleted records that hold her details.

	A copy goes when it holds a confirmed email or one of her phones (any formatting), or
	when it is a deleted copy of one of her records or activities.
	"""
	table = frappe.qb.DocType("Deleted Document")
	conditions = [table.data.like(f"%{like_escape(email)}%") for email in sorted(plan.emails) if email]
	for phone in sorted(plan.phones):
		digits = phone_search_digits(phone, PHONE_REGION)
		if digits:
			conditions.append(_digits(table.data).like(f"%{like_escape(digits)}%"))
	doomed: list[str] = []
	if conditions:
		rows = (
			frappe.qb.from_(table)
			.select(table.name, table.data)
			.where(table.deleted_doctype.isin(DELETED_DOCTYPES) & Criterion.any(conditions))
			.run(as_dict=True)
		)
		doomed = [row.name for row in rows if _holds_identifier(row.data, plan)]
	for chunk in _chunks(doomed):
		frappe.db.delete("Deleted Document", {"name": ["in", chunk]})

	for doctype, names in (
		(LEAD, plan.leads),
		(CONTACT, [*plan.contacts, *plan.former_names.get(CONTACT, [])]),
		(DEAL, [*plan.deals_on, *plan.deals_removed]),
		(ADDRESS, [*plan.addresses, *plan.former_names.get(ADDRESS, [])]),
		("Communication", plan.communications),
		(NOTE, plan.notes),
		(TASK, plan.tasks),
		("Comment", plan.comments),
		(CALL_LOG, plan.call_logs),
	):
		for chunk in _chunks(names):
			frappe.db.delete("Deleted Document", {"deleted_doctype": doctype, "deleted_name": ["in", chunk]})


# --- ledgers -----------------------------------------------------------------------------


def create_do_not_contact(plan: ErasurePlan) -> None:
	"""A do-not-contact entry (a keyed hash, never the value) for each of her emails and phones."""
	for email in sorted(plan.emails):
		add_do_not_contact("Email", email, plan.request)
	for phone in sorted(plan.phones):
		add_do_not_contact("Phone", phone, plan.request)


def create_retained_contract(doc: Document) -> None:
	"""Keep her name and the contract references for the retention period, when there are any."""
	references = doc.contract_references
	if not (references or "").strip():
		return
	if frappe.db.exists("CRM Retained Contract", {"request": doc.name}):
		return
	months = cint(frappe.db.get_single_value(SETTINGS, "contract_retention_months"))
	frappe.get_doc(
		{
			"doctype": "CRM Retained Contract",
			"person_name": doc.requester_name,
			"contract_references": references,
			"request": doc.name,
			"delete_after": add_months(today(), months),
		}
	).insert(ignore_permissions=True)


# --- the step ------------------------------------------------------------------------------


def finish(plan: ErasurePlan, doc: Document, after_commit: list[Callable]) -> None:
	"""Scrub her history and deleted copies, then record do-not-contact and the retained contract."""
	scrub_versions(plan)
	purge_deleted_documents(plan)
	create_do_not_contact(plan)
	create_retained_contract(doc)
