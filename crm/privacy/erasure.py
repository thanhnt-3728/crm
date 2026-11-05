"""Carrying out an approved erasure request (spec 5.6).

Records: the person's leads, contacts, addresses and the deals they are still on keep
existing as anonymized shells, so links and dashboard numbers hold. Contacts and addresses,
whose names are built from the person's name, are renamed to the placeholder. Their change
history and any Deleted Document copies that name the person are scrubbed too.

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

# Deal fields that identify the person when they equal the person's value: a full name, or
# a social profile equal to the same field on the person's confirmed leads/contacts. Email
# and phone fields identify too. Every other personal field on a deal (first or last name
# alone, job title, gender, salutation) could just as well be another person's, so it is
# blanked only once the deal is shown to be about the person.
FULL_NAME_FIELDS = ("lead_name",)
PROFILE_FIELDS = ("linkedin", "twitter", "facebook")

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
	full_names: set[str] = field(default_factory=set)  # casefolded
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


def _full_names(request, records: list[dict]) -> set[str]:
	"""The person's full names, casefolded: lead/full names, first + last name on the
	confirmed records, and each requester name."""
	names = set()
	for record in records:
		names.add(record.get("lead_name") or "")
		names.add(record.get("full_name") or "")
		names.add(_join_name(record.get("first_name"), record.get("middle_name"), record.get("last_name")))
		names.add(_join_name(record.get("first_name"), record.get("last_name")))
	names.update(NAME_SEPARATORS.split(request.requester_names or ""))
	return {
		name.strip().casefold()
		for name in names
		if len(name.strip()) > 1 and not name.strip().startswith("Erased person ")
	}


def _join_name(*parts) -> str:
	return " ".join(part.strip() for part in parts if part and part.strip())


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
		full_names=_full_names(request, records),
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


def _kind_of(fieldname: str, df=None) -> str:
	"""How a field is compared with the person's values: Email, Phone or Text."""
	if fieldname in ("email", "email_id") or (df and df.options == "Email"):
		return "Email"
	if fieldname in ("mobile_no", "phone") or (df and (df.fieldtype == "Phone" or df.options == "Phone")):
		return "Phone"
	return "Text"


def _is_person_row(row, contacts: set[str], person: _Person) -> bool:
	if row.get("contact") and row.get("contact") in contacts:
		return True
	return normalize_email(row.get("email")) in person.emails or bool(
		{normalize_phone(row.get("mobile_no")), normalize_phone(row.get("phone"))} & person.phones
	)


def _deal_identifies_person(current: dict, person: _Person) -> bool:
	"""Whether the deal's own fields carry the person's full name or social profile."""
	for fieldname in FULL_NAME_FIELDS:
		if (current.get(fieldname) or "").strip().casefold() in person.full_names - {""}:
			return True
	if _join_name(current.get("first_name"), current.get("last_name")).casefold() in person.full_names - {""}:
		return True
	for fieldname in PROFILE_FIELDS:
		value = (current.get(fieldname) or "").strip().casefold()
		if value and value in person.values.get(fieldname, set()):
			return True
	return False


def _erase_deal(name: str, contacts: set[str], person: _Person, placeholder: str) -> set[str]:
	"""Anonymize the person's contacts rows on the deal and blank the deal's own personal
	fields that are the person's. Returns the names of the person's contacts rows.

	A deal's email and phones are copied from its primary contact, so each is blanked only
	when it holds the person's value. The deal's other personal fields (names, job title,
	gender, social profiles...) are blanked only when the deal is about the person: the
	person is its primary contact, or its email, phone, full name or social profile is the
	person's. Otherwise they may belong to someone else and are left alone."""
	row_values = _blanked_values("CRM Contacts", personal_fields("CRM Contacts"))
	if frappe.get_meta("CRM Contacts").has_field("full_name"):
		row_values["full_name"] = placeholder
	rows = frappe.get_all(
		"CRM Contacts",
		filters={"parent": name, "parenttype": "CRM Deal"},
		fields=["name", "contact", "email", "mobile_no", "phone", "is_primary"],
		parent_doctype="CRM Deal",
	)
	hers = [row for row in rows if _is_person_row(row, contacts, person)]
	for row in hers:
		if row_values:
			frappe.db.set_value("CRM Contacts", row.name, row_values, update_modified=False)

	meta = frappe.get_meta("CRM Deal")
	fields = [f for f in personal_fields("CRM Deal") if meta.has_field(f)]
	if not fields:
		return {row.name for row in hers}
	current = frappe.db.get_value("CRM Deal", name, fields, as_dict=True) or {}

	contact_fields = {f for f in fields if _kind_of(f, meta.get_field(f)) != "Text"}
	matched = {
		f
		for f in contact_fields
		if isinstance(current.get(f), str)
		and _value_is_persons(_kind_of(f, meta.get_field(f)), current.get(f), person)
	}
	if matched or any(row.is_primary for row in hers) or _deal_identifies_person(current, person):
		matched |= {f for f in fields if f not in contact_fields and current.get(f) not in (None, "", 0)}

	values = {f: _blank(meta.get_field(f).fieldtype) for f in matched}
	if values:
		frappe.db.set_value("CRM Deal", name, values, update_modified=False)
	return {row.name for row in hers}


def _value_is_persons(kind: str, value, person: _Person) -> bool:
	"""Whether a single value is the person's email, phone or one of the person's names."""
	if not isinstance(value, str) or not value.strip():
		return False
	if kind == "Email":
		return normalize_email(value) in person.emails
	if kind == "Phone":
		return normalize_phone(value) in person.phones
	return value.strip().casefold() in person.folded_names()


# -- Change history ----------------------------------------------------------------------


def _scrub_value(fieldname: str, value, placeholder: str, is_hers=None):
	if not value or (is_hers is not None and not is_hers(fieldname, value)):
		return value
	return placeholder


def _scrub_changes(changes, fields: set[str], placeholder: str, is_hers=None) -> list:
	"""[[fieldname, old, new], ...] with the old and new values of `fields` replaced: all of
	them, or with `is_hers(fieldname, value)` only those it accepts. Empty values stay
	empty."""
	scrubbed = []
	for change in changes or []:
		if isinstance(change, list | tuple) and len(change) == 3 and change[0] in fields:
			fieldname, old, new = change
			change = [
				fieldname,
				_scrub_value(fieldname, old, placeholder, is_hers),
				_scrub_value(fieldname, new, placeholder, is_hers),
			]
		scrubbed.append(change)
	return scrubbed


def _rename_values(value, renames: dict[str, str]):
	"""`value` (parsed JSON) with every string exactly equal to a key of `renames` replaced
	by its value, at any depth."""
	if isinstance(value, str):
		return renames.get(value, value)
	if isinstance(value, list | tuple):
		return [_rename_values(item, renames) for item in value]
	if isinstance(value, dict):
		return {key: _rename_values(item, renames) for key, item in value.items()}
	return value


def scrub_version_data(
	data: dict,
	fields: set[str],
	placeholder: str,
	tables: dict[str, set[str]] | None = None,
	renames: dict[str, str] | None = None,
	matcher=None,
) -> dict:
	"""A copy of a Version's `data` with the values of personal `fields` replaced by
	`placeholder`. `tables` maps a child table fieldname to the personal fields of its rows,
	scrubbed in `added`, `removed` and `row_changed` entries. `renames` maps old record names
	to new ones: any value exactly equal to an old name (a link to a renamed contact, say)
	becomes the new name. Other changes are kept.

	Without `matcher` every personal value is replaced (the history of the person's own
	records). With one, only the person's data is (a record shared with others): a value
	when `matcher.value(fieldname, value)`, a whole table row when `matcher.row(row_dict)`
	or, for `row_changed`, `matcher.row_name(row_name)`; in other rows only the values
	`matcher.value` accepts."""
	tables = tables or {}
	is_hers = matcher.value if matcher else None
	out = _rename_values(data, renames) if renames else deepcopy(data)
	if "changed" in out:
		out["changed"] = _scrub_changes(out["changed"], fields, placeholder, is_hers)

	for key in ("added", "removed"):
		for entry in out.get(key) or []:
			# [table fieldname, row as dict]
			if len(entry) == 2 and entry[0] in tables and isinstance(entry[1], dict):
				row = entry[1]
				whole_row = matcher is None or matcher.row(row)
				for fieldname in tables[entry[0]]:
					if row.get(fieldname) and (whole_row or is_hers(fieldname, row[fieldname])):
						row[fieldname] = placeholder

	for entry in out.get("row_changed") or []:
		# [table fieldname, row index, row name, [[fieldname, old, new], ...]]
		if len(entry) == 4 and entry[0] in tables:
			whole_row = matcher is None or matcher.row_name(entry[2])
			entry[3] = _scrub_changes(entry[3], tables[entry[0]], placeholder, None if whole_row else is_hers)
	return out


def _version_tables(doctype: str) -> dict[str, set[str]]:
	tables = {}
	for table, fields in VERSION_TABLES.get(doctype, {}).items():
		tables[table] = personal_fields("CRM Contacts") if fields is None else fields
	return tables


class _DealVersionMatcher:
	"""Tells the person's data apart from other people's in a shared deal's history."""

	def __init__(self, person: _Person, contacts: set[str], rows: set[str]):
		self.person = person
		self.contacts = contacts  # the person's contact names, old and new
		self.rows = rows  # names of the person's contacts rows on the deal

	def value(self, fieldname: str, value) -> bool:
		return _value_is_persons(_kind_of(fieldname), value, self.person)

	def row(self, row: dict) -> bool:
		return row.get("name") in self.rows or _is_person_row(row, self.contacts, self.person)

	def row_name(self, name) -> bool:
		return name in self.rows


def _scrub_versions(
	doctype: str, names: list[str], placeholder: str, renames: dict[str, str], matcher_for=None
) -> None:
	"""Scrub the Versions of `names`. `matcher_for(docname)`, when given, returns the matcher
	that limits scrubbing to the person's data on that record."""
	if not names:
		return
	fields = personal_fields(doctype)
	tables = _version_tables(doctype)
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": doctype, "docname": ["in", names]},
		fields=["name", "docname", "data"],
	)
	for version in versions:
		try:
			data = json.loads(version.data or "{}")
		except ValueError:
			continue
		if not isinstance(data, dict):
			continue
		matcher = matcher_for(version.docname) if matcher_for else None
		scrubbed = scrub_version_data(data, fields, placeholder, tables, renames, matcher)
		if scrubbed != data:
			frappe.db.set_value(
				"Version",
				version.name,
				"data",
				frappe.as_json(scrubbed, indent=None, separators=(",", ":")),
				update_modified=False,
			)


# -- Renaming records named after the person ---------------------------------------------


def _new_names(names: list[str], base: str) -> dict[str, str]:
	"""{old name: new name}: `base` for the first of the sorted `names`, then `base-2`, ..."""
	return {old: base if i == 1 else f"{base}-{i}" for i, old in enumerate(sorted(names), start=1)}


def _rename(doctype: str, names: list[str], base: str) -> dict[str, str]:
	"""Rename `doctype` records whose names identify the person (Contact and Address names
	are built from the person's name) and return {old: new}. `rename_doc` carries the new
	name into every Link and Dynamic Link, Version.docname included; the "renamed from"
	comment it adds names the person, so it is deleted."""

	def edit_comments(name):
		return set(
			frappe.get_all(
				"Comment",
				filters={"reference_doctype": doctype, "reference_name": name, "comment_type": "Edit"},
				pluck="name",
			)
		)

	renames = {}
	for old, new in _new_names(names, base).items():
		if old == new:
			continue
		existing = edit_comments(old)
		frappe.rename_doc(
			doctype,
			old,
			new,
			force=True,
			ignore_permissions=True,
			show_alert=False,
			rebuild_search=False,
		)
		renames[old] = new
		# The comment the rename added (its text may HTML-escape the old name, so it is
		# found as the one that was not there before).
		added = edit_comments(new) - existing
		if added:
			frappe.db.delete("Comment", {"name": ["in", sorted(added)]})
	return renames


def _apply_renames(request, targets, renames: dict[str, str]) -> None:
	"""Point the in-memory request and targets at the new names, so later steps (and a later
	save of the request) do not bring the old ones back."""
	for row in request.matches:
		if row.reference_doctype in ("Contact", "Address") and row.reference_name in renames:
			row.reference_name = renames[row.reference_name]
	targets.contacts = sorted(renames.get(name, name) for name in targets.contacts)
	targets.addresses = sorted(renames.get(name, name) for name in targets.addresses)


def _retitle_contact_links(names, placeholder: str) -> None:
	"""Dynamic Link rows to the renamed contacts, under any parent, keep the contact's old
	title (its name) in `link_title`; replace it."""
	if not names:
		return
	link = frappe.qb.DocType("Dynamic Link")
	(
		frappe.qb.update(link)
		.set(link.link_title, placeholder)
		.where((link.link_doctype == "Contact") & link.link_name.isin(list(names)))
	).run()


# -- Addresses ---------------------------------------------------------------------------


def split_addresses(addresses: list[str], contacts) -> tuple[list[str], list[str]]:
	"""(own, shared): addresses linked only to the person's `contacts`, and addresses also
	linked to anyone or anything else."""
	if not addresses:
		return [], []
	contacts = set(contacts)
	links = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "parent": ["in", addresses]},
		fields=["parent", "link_doctype", "link_name"],
		parent_doctype="Address",
	)
	shared = {
		link.parent for link in links if not (link.link_doctype == "Contact" and link.link_name in contacts)
	}
	return sorted(set(addresses) - shared), sorted(shared & set(addresses))


def _unlink_shared_addresses(addresses: list[str], contacts) -> None:
	"""Take the person's contacts off addresses others use too; the address itself stays."""
	if not addresses or not contacts:
		return
	frappe.db.delete(
		"Dynamic Link",
		{
			"parenttype": "Address",
			"parent": ["in", addresses],
			"link_doctype": "Contact",
			"link_name": ["in", sorted(contacts)],
		},
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
	"""Anonymize the leads, contacts, addresses and deals in `targets`, rename the contacts
	and addresses (their names are the person's name), scrub the records' change history,
	and remove deleted copies that name the person. Statuses, values and stages are
	untouched; nothing is deleted except the contacts' email/phone rows, the person's links
	on shared addresses, and deleted copies.

	An address also linked to someone or something else is not erased: only the person's
	link to it is removed, and it is dropped from `targets.addresses`. `request.matches`,
	`targets.contacts` and `targets.addresses` are updated in place to the new names."""
	placeholder = placeholder_person(request.name)
	# Read what is the person's before any of it is blanked.
	person = _read_person(request)
	old_contacts = set(targets.contacts)
	own_addresses, shared_addresses = split_addresses(targets.addresses, old_contacts)

	her_rows = {deal: _erase_deal(deal, old_contacts, person, placeholder) for deal in targets.deals_still_on}
	for lead in targets.leads:
		_erase_record("CRM Lead", lead, placeholder)
	for contact in targets.contacts:
		_erase_contact(contact, placeholder)
	for address in own_addresses:
		_erase_record("Address", address, placeholder)
	_unlink_shared_addresses(shared_addresses, old_contacts)
	targets.addresses = own_addresses

	renames = _rename("Contact", targets.contacts, placeholder)
	renames |= _rename("Address", targets.addresses, f"{placeholder}-Address")
	_apply_renames(request, targets, renames)
	_retitle_contact_links(targets.contacts, placeholder)

	all_contacts = old_contacts | set(targets.contacts)

	def deal_matcher(deal):
		# Deals are shared with other contacts: only the person's data goes.
		return _DealVersionMatcher(person, all_contacts, her_rows.get(deal, set()))

	for doctype, names, matcher_for in (
		("CRM Lead", targets.leads, None),
		("Contact", targets.contacts, None),
		("CRM Deal", targets.deals_still_on, deal_matcher),
		("Address", targets.addresses, None),
	):
		_scrub_versions(doctype, names, placeholder, renames, matcher_for)

	deleted = _deleted_documents_naming(sorted(person.emails), sorted(person.phones))
	if deleted:
		frappe.db.delete("Deleted Document", {"name": ["in", sorted(deleted)]})
