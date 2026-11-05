"""Carrying out an approved erasure request (spec 5.6).

Records: the person's leads, contacts, addresses and the deals they are still on keep
existing as anonymized shells, so links and dashboard numbers hold. Their change history
and any Deleted Document copies that name the person are scrubbed too.

Nothing here calls `doc.save()` on an erased record: writes go through
`frappe.db.set_value(..., update_modified=False)` and `frappe.db.delete`, so no new
Version row, automation or notification captures the old values.
"""

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field

import frappe
from pypika.functions import Lower

from crm.privacy import personal_fields
from crm.privacy.identifiers import normalize, normalize_email, text_contains_email, text_contains_phone
from crm.privacy.matching import active_identifiers, confirmed
from crm.utils import normalize_phone, phone_search_digits

# Deleted copies of these doctypes are removed when they name the person.
DELETED_DOCTYPES = (
	"CRM Lead",
	"Contact",
	"CRM Deal",
	"Communication",
	"FCRM Note",
	"CRM Call Log",
	"Address",
)

# Fields that hold a person's name on each record, set to the placeholder (they are
# mandatory or shown as the record's title).
NAME_FIELDS = {
	"CRM Lead": ("first_name", "lead_name"),
	"Contact": ("first_name", "full_name"),
	"Address": ("address_title",),
}

# Personal child tables whose Version rows are scrubbed, per doctype: table fieldname ->
# the child doctype's personal fields (None means take them from the privacy settings).
VERSION_TABLES = {
	"CRM Deal": {"contacts": None},
	"Contact": {"email_ids": {"email_id"}, "phone_nos": {"phone"}},
}

# Field types blanked to NULL rather than "".
NULL_TYPES = {
	"Link",
	"Dynamic Link",
	"Attach",
	"Attach Image",
	"Date",
	"Datetime",
	"Time",
	"Int",
	"Float",
	"Currency",
	"Percent",
	"Duration",
}

# Deal fields compared only together with the deal's other personal fields.
GENERIC_TYPES = ("Link", "Select", "Check")

# A deal field's value is the person's when it equals one of these fields on the person's
# confirmed leads or contacts (default: the field of the same name).
SAME_VALUE_FIELDS = {"job_title": ("job_title", "designation")}

# A phone whose national number is shorter than this matches too much free text.
MIN_PHONE_DIGITS = 7

NAME_SEPARATORS = re.compile(r"[\n,;]+")


def placeholder_person(request_name: str) -> str:
	"""What a person's name (or address) is replaced with."""
	return f"Erased person {request_name}"


def placeholder_content(request_name: str) -> str:
	"""What erased text (subjects, message bodies, notes) is replaced with."""
	return f"Content erased {request_name}"


# -- What belongs to the person ----------------------------------------------------------


@dataclass
class _Person:
	"""The person's values, read before anything is erased."""

	emails: set[str] = field(default_factory=set)  # normalized
	phones: set[str] = field(default_factory=set)  # normalized E.164
	names: set[str] = field(default_factory=set)  # as typed, stripped
	# Other personal values on the confirmed leads/contacts, casefolded, by fieldname.
	values: dict[str, set[str]] = field(default_factory=dict)

	def folded_names(self) -> set[str]:
		return {name.casefold() for name in self.names}


def _excluded(request, kind: str) -> set[str]:
	return {
		normalize(kind, row.value)
		for row in request.identifiers
		if row.kind == kind and row.excluded and row.value
	}


def _person_names(request, records: list[dict]) -> set[str]:
	"""Name strings from the confirmed records and the request's requester names.
	Placeholders and single characters (initials) are left out."""
	names = set()
	for record in records:
		for fieldname in ("first_name", "middle_name", "last_name", "lead_name", "full_name"):
			names.add((record.get(fieldname) or "").strip())
	names.update(part.strip() for part in NAME_SEPARATORS.split(request.requester_names or ""))
	return {name for name in names if len(name) > 1 and not name.startswith("Erased person ")}


def _confirmed_records(request) -> list[dict]:
	"""The current values of the confirmed leads and contacts."""
	records = []
	for doctype in ("CRM Lead", "Contact"):
		names = confirmed(request, doctype)
		if not names:
			continue
		meta = frappe.get_meta(doctype)
		fields = ["name", *(f for f in personal_fields(doctype) if meta.has_field(f))]
		records += frappe.get_all(doctype, filters={"name": ["in", names]}, fields=fields)
	return records


def _read_person(request) -> _Person:
	records = _confirmed_records(request)
	person = _Person(
		emails=set(active_identifiers(request, "Email")),
		phones=set(active_identifiers(request, "Phone")),
		names=_person_names(request, records),
	)

	# Emails and phones on the confirmed records are the person's too, unless Compliance
	# excluded them (a shared office number, say).
	record_emails = {normalize_email(r.get(f)) for r in records for f in ("email", "email_id")}
	record_phones = {normalize_phone(r.get(f)) for r in records for f in ("mobile_no", "phone")}
	contacts = confirmed(request, "Contact")
	if contacts:
		for table, column, kind, found in (
			("Contact Email", "email_id", "Email", record_emails),
			("Contact Phone", "phone", "Phone", record_phones),
		):
			values = frappe.get_all(
				table,
				filters={"parenttype": "Contact", "parent": ["in", contacts]},
				pluck=column,
				parent_doctype="Contact",
			)
			found.update(normalize(kind, value) for value in values)
	person.emails |= record_emails - _excluded(request, "Email") - {""}
	person.phones |= record_phones - _excluded(request, "Phone") - {""}

	for record in records:
		for fieldname, value in record.items():
			if fieldname != "name" and isinstance(value, str) and value.strip():
				person.values.setdefault(fieldname, set()).add(value.strip().casefold())
	return person


def erase_person_values(request) -> set[str]:
	"""The person's normalized emails and phones, plus the name strings on the confirmed
	leads and contacts and in the requester names.

	Read this before `erase_records`: afterwards the records only hold placeholders, and
	only the emails, phones and requester names are left to find."""
	person = _read_person(request)
	return person.emails | person.phones | person.names


# -- Blanking records ----------------------------------------------------------------------


def _blank(fieldtype: str):
	if fieldtype == "Check":
		return 0
	return None if fieldtype in NULL_TYPES else ""


def _blanked_values(doctype: str, fields) -> dict:
	"""{fieldname: blank value} for the `fields` that exist on `doctype`."""
	meta = frappe.get_meta(doctype)
	values = {}
	for fieldname in fields:
		df = meta.get_field(fieldname)
		if df:
			values[fieldname] = _blank(df.fieldtype)
	return values


def _erase_record(doctype: str, name: str, placeholder: str) -> None:
	values = _blanked_values(doctype, personal_fields(doctype))
	meta = frappe.get_meta(doctype)
	for fieldname in NAME_FIELDS.get(doctype, ()):
		if meta.has_field(fieldname):
			values[fieldname] = placeholder
	if values:
		frappe.db.set_value(doctype, name, values, update_modified=False)


def _erase_contact(name: str, placeholder: str) -> None:
	_erase_record("Contact", name, placeholder)
	frappe.db.delete("Contact Email", {"parent": name, "parenttype": "Contact"})
	frappe.db.delete("Contact Phone", {"parent": name, "parenttype": "Contact"})


def _kind_of(df) -> str:
	"""How a deal field is compared with the person's values: Email, Phone or Text."""
	if df.options == "Email" or df.fieldname in ("email", "email_id"):
		return "Email"
	if df.fieldtype == "Phone" or df.options == "Phone" or df.fieldname in ("mobile_no", "phone"):
		return "Phone"
	return "Text"


def _holds_person_value(df, value, person: _Person) -> bool:
	if not isinstance(value, str) or not value.strip():
		return False
	kind = _kind_of(df)
	if kind == "Email":
		return normalize_email(value) in person.emails
	if kind == "Phone":
		return normalize_phone(value) in person.phones
	text = value.strip().casefold()
	if text in person.folded_names():
		return True
	return any(
		text in person.values.get(f, set()) for f in SAME_VALUE_FIELDS.get(df.fieldname, (df.fieldname,))
	)


def _is_person_row(row, contacts: set[str], person: _Person) -> bool:
	if row.contact and row.contact in contacts:
		return True
	return normalize_email(row.email) in person.emails or bool(
		{normalize_phone(row.mobile_no), normalize_phone(row.phone)} & person.phones
	)


def _erase_deal(name: str, contacts: set[str], person: _Person, placeholder: str) -> None:
	"""Anonymize the person's contacts rows on the deal, and blank the deal's own personal
	fields that hold the person's values. Values copied from another (primary) contact stay."""
	row_values = _blanked_values("CRM Contacts", personal_fields("CRM Contacts"))
	if frappe.get_meta("CRM Contacts").has_field("full_name"):
		row_values["full_name"] = placeholder
	rows = frappe.get_all(
		"CRM Contacts",
		filters={"parent": name, "parenttype": "CRM Deal"},
		fields=["name", "contact", "email", "mobile_no", "phone"],
		parent_doctype="CRM Deal",
	)
	for row in rows:
		if row_values and _is_person_row(row, contacts, person):
			frappe.db.set_value("CRM Contacts", row.name, row_values, update_modified=False)

	meta = frappe.get_meta("CRM Deal")
	fields = [f for f in personal_fields("CRM Deal") if meta.has_field(f)]
	if not fields:
		return
	current = frappe.db.get_value("CRM Deal", name, fields, as_dict=True) or {}
	# Generic values such as gender or salutation say nothing on their own and may well be
	# another person's: they are blanked only when the deal carries the person's details.
	generic = {f for f in fields if meta.get_field(f).fieldtype in GENERIC_TYPES}
	matched = {
		f
		for f in fields
		if f not in generic and _holds_person_value(meta.get_field(f), current.get(f), person)
	}
	if matched:
		matched |= {f for f in generic if current.get(f) not in (None, "")}
	values = {f: _blank(meta.get_field(f).fieldtype) for f in matched}
	if values:
		frappe.db.set_value("CRM Deal", name, values, update_modified=False)


# -- Change history ----------------------------------------------------------------------


def _scrub_changes(changes, fields: set[str], placeholder: str) -> list:
	"""[[fieldname, old, new], ...] with the old and new values of `fields` replaced. Empty
	values stay empty."""
	scrubbed = []
	for change in changes or []:
		if isinstance(change, list | tuple) and len(change) == 3 and change[0] in fields:
			fieldname, old, new = change
			change = [fieldname, placeholder if old else old, placeholder if new else new]
		scrubbed.append(change)
	return scrubbed


def scrub_version_data(
	data: dict, fields: set[str], placeholder: str, tables: dict[str, set[str]] | None = None
) -> dict:
	"""A copy of a Version's `data` with the values of personal `fields` replaced by
	`placeholder`. `tables` maps a child table fieldname to the personal fields of its rows,
	scrubbed in `added`, `removed` and `row_changed` entries. Other changes are kept."""
	tables = tables or {}
	out = deepcopy(data)
	if "changed" in out:
		out["changed"] = _scrub_changes(out["changed"], fields, placeholder)

	for key in ("added", "removed"):
		for entry in out.get(key) or []:
			# [table fieldname, row as dict]
			if len(entry) == 2 and entry[0] in tables and isinstance(entry[1], dict):
				row = entry[1]
				for fieldname in tables[entry[0]]:
					if row.get(fieldname):
						row[fieldname] = placeholder

	for entry in out.get("row_changed") or []:
		# [table fieldname, row index, row name, [[fieldname, old, new], ...]]
		if len(entry) == 4 and entry[0] in tables:
			entry[3] = _scrub_changes(entry[3], tables[entry[0]], placeholder)
	return out


def _version_tables(doctype: str) -> dict[str, set[str]]:
	tables = {}
	for table, fields in VERSION_TABLES.get(doctype, {}).items():
		tables[table] = personal_fields("CRM Contacts") if fields is None else fields
	return tables


def _scrub_versions(doctype: str, names: list[str], placeholder: str) -> None:
	if not names:
		return
	fields = personal_fields(doctype)
	tables = _version_tables(doctype)
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": doctype, "docname": ["in", names]},
		fields=["name", "data"],
	)
	for version in versions:
		try:
			data = json.loads(version.data or "{}")
		except ValueError:
			continue
		if not isinstance(data, dict):
			continue
		scrubbed = scrub_version_data(data, fields, placeholder, tables)
		if scrubbed != data:
			frappe.db.set_value(
				"Version",
				version.name,
				"data",
				frappe.as_json(scrubbed, indent=None, separators=(",", ":")),
				update_modified=False,
			)


# -- Deleted copies ----------------------------------------------------------------------


def _scannable_phones(phones) -> list[str]:
	"""Phones long enough to look for in free text without matching unrelated digits."""
	return [p for p in phones if len(phone_search_digits(p)) >= MIN_PHONE_DIGITS]


def _deleted_documents_naming(emails, phones) -> set[str]:
	"""Deleted Document copies (of DELETED_DOCTYPES) whose data names one of the emails or
	phones. Emails are prefiltered in SQL; phones can be typed any way, so every copy of the
	listed doctypes is checked."""
	table = frappe.qb.DocType("Deleted Document")

	def copies(*conditions):
		query = frappe.qb.from_(table).select(table.name, table.data)
		query = query.where(table.deleted_doctype.isin(DELETED_DOCTYPES))
		for condition in conditions:
			query = query.where(condition)
		return query.run(as_dict=True)

	found = set()
	for email in emails:
		for row in copies(Lower(table.data).like(f"%{email}%")):
			if text_contains_email(row.data, email):
				found.add(row.name)

	phones = _scannable_phones(phones)
	if phones:
		for row in copies():
			if row.name not in found and any(text_contains_phone(row.data, p) for p in phones):
				found.add(row.name)
	return found


# -- Entry point -------------------------------------------------------------------------


def erase_records(request, targets) -> None:
	"""Anonymize the leads, contacts, addresses and deals in `targets`, scrub their change
	history, and remove deleted copies that name the person. Statuses, values and stages are
	untouched; nothing is deleted except the contacts' email/phone rows and deleted copies."""
	placeholder = placeholder_person(request.name)
	# Read what is the person's before any of it is blanked.
	person = _read_person(request)
	contacts = set(targets.contacts)

	for deal in targets.deals_still_on:
		_erase_deal(deal, contacts, person, placeholder)
	for lead in targets.leads:
		_erase_record("CRM Lead", lead, placeholder)
	for contact in targets.contacts:
		_erase_contact(contact, placeholder)
	for address in targets.addresses:
		_erase_record("Address", address, placeholder)

	for doctype, names in (
		("CRM Lead", targets.leads),
		("Contact", targets.contacts),
		("CRM Deal", targets.deals_still_on),
		("Address", targets.addresses),
	):
		_scrub_versions(doctype, names, placeholder)

	deleted = _deleted_documents_naming(sorted(person.emails), sorted(person.phones))
	if deleted:
		frappe.db.delete("Deleted Document", {"name": ["in", sorted(deleted)]})
