"""Running an approved erasure request: one background job, all or nothing.

`run_erasure` works out the plan and runs each step in `STEPS` inside a savepoint. Any
error rolls the database back to that savepoint, drops what the failed attempt queued
for after the commit, and records the failure on the request, which stays Awaiting
Sign-off so it can be approved again.

Erasure writes never go through `doc.save()`, which would keep the old values in a
Version. They use `frappe.db.set_value(..., update_modified=False)`, `frappe.db.delete`
or `frappe.qb.update`. Lead and deal rows are never deleted, and their status, values,
owner, dates and organization are left alone.

Text written here (including the stored error) never carries the person's name, email
or phone; the request number identifies her.
"""

import re
from collections.abc import Callable
from contextlib import suppress
from functools import partial

import frappe
from frappe.desk.form.linked_with import capture_pending_side_effects, discard_side_effects_since
from frappe.model import no_value_fields, table_fields
from frappe.model.document import Document
from frappe.model.rename_doc import rename_doc
from frappe.utils import now

from crm.privacy.identifiers import normalize_identifier, personal_fields
from crm.privacy.matching import like_escape, phone_rows
from crm.privacy.plan import ErasurePlan, plan_erasure
from crm.privacy.rules import DEAL_FIELD_SOURCES, deal_fields_to_blank, erased_person, scrub_identifiers
from crm.privacy.sweep import sweep_activities

DOCTYPE = "CRM Erasure Request"
LEAD = "CRM Lead"
DEAL = "CRM Deal"
CONTACT = "Contact"
ADDRESS = "Address"
DEAL_CONTACT = "CRM Contacts"

# Mandatory names get the placeholder instead of a blank.
LEAD_NAME_FIELDS = ("first_name", "lead_name")
CONTACT_NAME_FIELDS = ("first_name", "full_name")
# Always blanked on her rows in a deal's contacts table, whatever the settings list.
DEAL_CONTACT_FIELDS = ("email", "mobile_no", "phone")
DEAL_IDENTIFIER_FIELDS = {"email": "Email", "mobile_no": "Phone", "phone": "Phone"}

ADDRESS_KEEP = ("address_type",)
ADDRESS_BLANK_TYPES = (
	"Data",
	"Small Text",
	"Text",
	"Long Text",
	"Text Editor",
	"Link",
	"Select",
	"Phone",
)
NUMBER_TYPES = ("Int", "Float", "Currency", "Percent", "Check", "Rating", "Duration")
DATE_TYPES = ("Date", "Datetime", "Time")
NAME_VALUE_KEYS = ("first_name", "middle_name", "last_name", "full_name", "lead_name")
FALLBACK_ERROR = "The erasure failed and its error could not be stored without personal data."
# Child tables whose link_title copies the linked record's title (her name).
LINK_TITLE_TABLES = ("Dynamic Link", "Communication Link")


def run_erasure(request: str, approver: str) -> None:
	"""Erase everything the request's plan lists, or nothing at all."""
	doc = frappe.get_doc(DOCTYPE, request)
	if doc.status != "Awaiting Sign-off":
		return
	frappe.db.savepoint("erasure")
	# Savepoint rollback leaves frappe's commit callbacks and realtime queue alone, so
	# what the attempt queued is dropped by hand on failure.
	pending = capture_pending_side_effects()
	after_commit: list[Callable] = []  # registered only on success
	plan = None
	error = None
	try:
		plan = plan_erasure(doc)
		for step in STEPS:
			step(plan, doc, after_commit)
		frappe.db.set_value(
			DOCTYPE,
			request,
			{
				"status": "Erased",
				"approved_by": approver,
				"approved_on": now(),
				"erased_on": now(),
				"erasure_status": "",
				"erasure_error": "",
			},
		)
	except Exception:
		try:
			error = _error_text(doc, plan)
		except Exception:
			error = FALLBACK_ERROR
	if error is not None:
		# Handled outside the except block: nothing below (log_error, the logger, Sentry, the
		# job runner) can pick up the original exception, whose text may hold personal data.
		_record_failure(request, error, pending)
		return
	for fn in after_commit:
		frappe.db.after_commit.add(fn)
	_commit()


class ErasureFailed(Exception):
	"""Raised, without the original exception attached, when even recording a failure fails."""


def _record_failure(request: str, error: str, pending: dict) -> None:
	"""Undo the attempt and mark the request Failed with the scrubbed `error`."""
	try:
		frappe.db.rollback(save_point="erasure")
	except Exception:
		# After a deadlock or a lost connection the server has already rolled back the whole
		# transaction and the savepoint is gone. Nothing before the savepoint needs keeping.
		with suppress(Exception):
			frappe.db.rollback()
	with suppress(Exception):
		discard_side_effects_since(pending)
	with suppress(Exception):
		# Caches filled during the attempt may hold rolled-back values (rename_doc also clears all).
		frappe.clear_cache()

	try:
		frappe.db.set_value(DOCTYPE, request, {"erasure_status": "Failed", "erasure_error": error})
		frappe.log_error(
			title=f"Erasure failed for {request}", message=error, reference_doctype=DOCTYPE, reference_name=request
		)
		_commit()
	except Exception:
		# `from None` keeps the original traceback, which may hold personal data, out of the job log.
		raise ErasureFailed(f"Erasure failed for {request} and the failure could not be recorded") from None


def _commit() -> None:
	# Tests keep their transaction and call frappe.db.after_commit.run() when they need to.
	if not (frappe.in_test or frappe.flags.in_test):
		frappe.db.commit()


def _error_text(doc: Document, plan: ErasurePlan | None) -> str:
	"""The current traceback, without the person's names, emails or phones, at most 2000 characters."""
	placeholder = erased_person(doc.name)
	text = frappe.get_traceback(with_context=False)

	emails, phones = set(), set()
	for row in doc.identifiers:
		value = normalize_identifier(row.kind, row.value)
		if value:
			(emails if row.kind == "Email" else phones).add(value)
	names = {doc.requester_name, *(doc.other_names or "").splitlines()}
	for match in doc.matches:
		if match.reference_doctype in (LEAD, CONTACT):
			names.add(match.title)
		if match.reference_doctype == CONTACT:
			names.add(match.reference_name)
	if plan:
		emails |= plan.emails
		phones |= plan.phones
		for key in NAME_VALUE_KEYS:
			names |= plan.her_values.get(key, set())

	text = scrub_identifiers(text, emails, phones, placeholder)
	words = {part for name in names if name for part in [name.strip(), *name.split()] if len(part.strip()) > 1}
	if words:
		# One pass, longest first, so a placeholder already written is never matched again.
		alternatives = "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))
		text = re.sub(rf"(?<!\w)(?:{alternatives})(?!\w)", placeholder, text, flags=re.IGNORECASE)
	return text[-2000:]


def _blank(df) -> object:
	"""The empty value a field of this type takes."""
	if df.fieldtype in NUMBER_TYPES:
		return 0
	if df.fieldtype in DATE_TYPES:
		return None
	return ""


def _value_fields(doctype: str, fieldnames) -> list:
	"""Docfields of `doctype` named in `fieldnames` that hold a value (no tables or layout)."""
	meta = frappe.get_meta(doctype)
	fields = []
	for fieldname in fieldnames:
		df = meta.get_field(fieldname)
		if df and df.fieldtype not in no_value_fields and df.fieldtype not in table_fields:
			fields.append(df)
	return fields


def _erase_fields(doctype: str, name: str, fields: list, named: tuple[str, ...], placeholder: str) -> None:
	"""Blank each set field in `fields` and put the placeholder in the `named` fields."""
	current = frappe.db.get_value(doctype, name, [df.fieldname for df in fields] or ["name"], as_dict=True) or {}
	values = {df.fieldname: _blank(df) for df in fields if current.get(df.fieldname)}
	values.update({fieldname: placeholder for fieldname in named if frappe.get_meta(doctype).has_field(fieldname)})
	if values:
		frappe.db.set_value(doctype, name, values, update_modified=False)


def _erase_leads(plan: ErasurePlan, listed: dict[str, set[str]], placeholder: str) -> None:
	fields = _value_fields(LEAD, sorted(listed.get(LEAD, set()) - set(LEAD_NAME_FIELDS)))
	for lead in plan.leads:
		_erase_fields(LEAD, lead, fields, LEAD_NAME_FIELDS, placeholder)


def _erase_deals_on(plan: ErasurePlan, listed: dict[str, set[str]]) -> None:
	"""On deals she is still on, blank the deal fields that hold her values.

	Name, title, social and identifier fields are blanked only where they hold her values
	(another person's may be there). Any other field listed for CRM Deal in the settings
	is blanked whenever it is set.
	"""
	compared = {*DEAL_IDENTIFIER_FIELDS, *DEAL_FIELD_SOURCES}
	fields = _value_fields(DEAL, sorted(compared))
	extra = _value_fields(DEAL, sorted(listed.get(DEAL, set()) - compared))
	by_name = {df.fieldname: df for df in [*fields, *extra]}
	for deal in plan.deals_on:
		row = frappe.db.get_value(DEAL, deal, list(by_name), as_dict=True) or {}
		blank = deal_fields_to_blank(row, plan.her_values, plan.emails, plan.phones)
		blank += [df.fieldname for df in extra if row.get(df.fieldname)]
		values = {fieldname: _blank(by_name[fieldname]) for fieldname in blank if fieldname in by_name}
		if values:
			frappe.db.set_value(DEAL, deal, values, update_modified=False)


def _erase_deal_contact_rows(plan: ErasurePlan, listed: dict[str, set[str]], placeholder: str) -> None:
	"""Her rows in any deal's contacts table, confirmed deal or not. The `contact` link stays."""
	if not plan.contacts:
		return
	fields = _value_fields(
		DEAL_CONTACT, sorted((listed.get(DEAL_CONTACT, set()) | set(DEAL_CONTACT_FIELDS)) - {"full_name", "contact"})
	)
	table = frappe.qb.DocType(DEAL_CONTACT)
	query = frappe.qb.update(table).set(table.full_name, placeholder)
	for df in fields:
		query = query.set(getattr(table, df.fieldname), _blank(df))
	query.where(table.contact.isin(plan.contacts)).run()


def _erase_deal_identifiers(plan: ErasurePlan) -> None:
	"""Deal email, mobile and phone that hold a confirmed identifier, on every deal.

	The deal copies them from its primary contact, so they are hers wherever they appear.
	"""
	table = frappe.qb.DocType(DEAL)
	meta = frappe.get_meta(DEAL)
	for fieldname, kind in DEAL_IDENTIFIER_FIELDS.items():
		if not meta.has_field(fieldname):
			continue
		found: list[str] = []
		if kind == "Email":
			column = getattr(table, fieldname)
			for email in sorted(plan.emails):
				rows = (
					frappe.qb.from_(table)
					.select(table.name, column)
					.where(column.like(f"%{like_escape(email)}%"))
					.run(as_dict=True)
				)
				found += [row.name for row in rows if normalize_identifier("Email", row.get(fieldname)) == email]
		else:
			for phone in sorted(plan.phones):
				found += [row.name for row in phone_rows(DEAL, [fieldname], phone)]
		for deal in dict.fromkeys(found):
			frappe.db.set_value(DEAL, deal, fieldname, "", update_modified=False)


def _erase_contacts(plan: ErasurePlan, listed: dict[str, set[str]], placeholder: str) -> None:
	fields = _value_fields(CONTACT, sorted(listed.get(CONTACT, set()) - set(CONTACT_NAME_FIELDS)))
	for contact in plan.contacts:
		_erase_fields(CONTACT, contact, fields, CONTACT_NAME_FIELDS, placeholder)
		for child in ("Contact Email", "Contact Phone"):
			frappe.db.delete(child, {"parenttype": CONTACT, "parent": contact})


def _erase_addresses(plan: ErasurePlan, placeholder: str) -> None:
	meta = frappe.get_meta(ADDRESS)
	named = ("address_title",)  # the title (and name source) gets the placeholder
	fields = [
		df
		for df in meta.fields
		if df.fieldtype in ADDRESS_BLANK_TYPES and df.fieldname not in ADDRESS_KEEP and df.fieldname not in named
	]
	for address in plan.addresses:
		_erase_fields(ADDRESS, address, fields, named, placeholder)


def _erase_link_titles(plan: ErasurePlan, placeholder: str) -> None:
	"""Put the placeholder in `link_title` of link rows pointing at her records.

	Address and Communication copy the linked record's title (her name) into these rows;
	rename_doc moves `link_name` but leaves `link_title`.
	"""
	targets = {LEAD: plan.leads, CONTACT: plan.contacts, ADDRESS: plan.addresses}
	for child in LINK_TITLE_TABLES:
		table = frappe.qb.DocType(child)
		for doctype, names in targets.items():
			if names:
				(
					frappe.qb.update(table)
					.set(table.link_title, placeholder)
					.where((table.link_doctype == doctype) & table.link_name.isin(names))
					.run()
				)


def _rename_all(doctype: str, names: list[str], base: str, after_commit: list[Callable]) -> list[str]:
	"""Rename each record to `base`, `base-2`, `base-3`… and return the new names in order."""
	renamed: list[str] = []
	suffix = 1
	for old in names:
		while True:
			new = base if suffix == 1 else f"{base}-{suffix}"
			suffix += 1
			if not frappe.db.exists(doctype, new):
				break
		_rename(doctype, old, new, after_commit)
		renamed.append(new)
	return renamed


def _edit_comments(doctype: str, name: str) -> list[str]:
	return frappe.get_all(
		"Comment",
		filters={"comment_type": "Edit", "reference_doctype": doctype, "reference_name": name},
		pluck="name",
	)


def _rename(doctype: str, old: str, new: str, after_commit: list[Callable]) -> None:
	"""Rename a record whose name is her name, keeping every link, and remove the traces of the old name.

	rename_doc moves Link and Dynamic Link values, child rows, attachments, Version rows
	and user settings to the new name. It also adds an Edit comment "renamed from <old>",
	which is deleted here. It does not update Notification Log `document_name` or Email
	Queue `reference_name` (Data fields) or the global search index, so those are handled
	here too.
	"""
	existing = set(_edit_comments(doctype, old))
	# The job has already checked the approver; rebuild_search would enqueue a job before the commit.
	rename_doc(
		doctype=doctype,
		old=old,
		new=new,
		force=True,
		ignore_permissions=True,
		show_alert=False,
		rebuild_search=False,
	)
	added = [name for name in _edit_comments(doctype, new) if name not in existing]
	if added:
		frappe.db.delete("Comment", {"name": ["in", added]})
	# Data fields that hold the record's name, which rename_doc leaves on the old name.
	for table, doctype_field, name_field in (
		("Notification Log", "document_type", "document_name"),
		("Email Queue", "reference_doctype", "reference_name"),
	):
		frappe.db.set_value(
			table,
			{doctype_field: doctype, name_field: old},
			name_field,
			new,
			update_modified=False,
		)
	# __global_search is MyISAM, outside the transaction, so it changes only after the commit.
	after_commit.append(partial(_replace_search_entry, doctype, old, new))


def _replace_search_entry(doctype: str, old: str, new: str) -> None:
	from frappe.utils.global_search import update_global_search

	frappe.db.delete("__global_search", {"doctype": doctype, "name": old})
	if frappe.db.exists(doctype, new):
		update_global_search(frappe.get_doc(doctype, new))


def erase_records(plan: ErasurePlan, doc: Document, after_commit: list[Callable]) -> None:
	"""Blank or replace her personal fields on leads, deals, contacts and addresses.

	Contacts and addresses are renamed to the placeholder (their names are her name).
	`plan.contacts` and `plan.addresses` are updated to the new names, so later steps
	find the renamed records.
	"""
	placeholder = erased_person(doc.name)
	listed = personal_fields()

	_erase_leads(plan, listed, placeholder)
	_erase_deals_on(plan, listed)
	_erase_deal_contact_rows(plan, listed, placeholder)
	_erase_deal_identifiers(plan)
	_erase_contacts(plan, listed, placeholder)
	_erase_addresses(plan, placeholder)

	plan.contacts[:] = _rename_all(CONTACT, plan.contacts, placeholder, after_commit)
	plan.addresses[:] = _rename_all(ADDRESS, plan.addresses, placeholder, after_commit)
	_erase_link_titles(plan, placeholder)


STEPS: list[Callable[[ErasurePlan, Document, list[Callable]], None]] = [erase_records, sweep_activities]
