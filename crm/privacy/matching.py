"""Find the CRM records that belong to the person an erasure request is about.

Matching works from the request's non-excluded identifiers (normalized emails and
phones). Confirmed leads and contacts feed their own identifiers back in, so a second
number on a contact is found too. Nothing here writes to the database: the callers
save the request.
"""

import re

import frappe
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Replace

from crm.integrations.api import _digits_only
from crm.privacy.identifiers import PHONE_REGION, normalize_identifier
from crm.utils import phone_search_digits

MAX_ROUNDS = 3
EMAIL_REASON = "Email matches"
PHONE_REASON = "Phone matches"
CONVERTED_REASON = "Converted from lead"
CONTACT_LISTED_REASON = "Lists confirmed contact"

LEAD, CONTACT, DEAL = "CRM Lead", "Contact", "CRM Deal"

_EMAIL_IN_TEXT = re.compile(r"[^\s,;<>\"']+@[^\s,;<>\"']+")


def _digits(column):
	"""`_digits_only` plus dots, so "530.555.0142" is searchable like "(530) 555-0142"."""
	return Replace(_digits_only(column), ".", "")


def _phone_rows(doctype: str, columns: list[str], phone: str) -> list[dict]:
	"""Rows of `doctype` whose `columns` hold `phone`, in any formatting."""
	digits = phone_search_digits(phone, PHONE_REGION)
	if not digits:
		return []
	table = frappe.qb.DocType(doctype)
	conditions = [_digits(getattr(table, column)).like(f"%{digits}%") for column in columns]
	rows = (
		frappe.qb.from_(table)
		.select(table.name, *[getattr(table, column) for column in columns])
		.where(Criterion.any(conditions))
		.run(as_dict=True)
	)
	return [row for row in rows if any(normalize_identifier("Phone", row.get(c)) == phone for c in columns)]


def record_title(doctype: str, name: str) -> str:
	if doctype == LEAD:
		return frappe.db.get_value(LEAD, name, "lead_name") or name
	if doctype == CONTACT:
		return frappe.db.get_value(CONTACT, name, "full_name") or name
	organization, status = frappe.db.get_value(DEAL, name, ["organization", "status"]) or (None, None)
	return f"{organization} - {status}" if organization and status else organization or name


def _records_for_identifier(kind: str, value: str) -> dict[tuple[str, str], str]:
	"""(doctype, name) -> reason for every lead, contact and deal holding the identifier."""
	found: dict[tuple[str, str], str] = {}
	if kind == "Email":
		reason = EMAIL_REASON
		for doctype in (LEAD, DEAL):
			rows = frappe.get_all(doctype, filters={"email": value}, fields=["name", "email"])
			for row in rows:
				if normalize_identifier("Email", row.email) == value:
					found.setdefault((doctype, row.name), reason)
		child = frappe.qb.DocType("Contact Email")
		rows = (
			frappe.qb.from_(child)
			.select(child.parent, child.email_id)
			.where(child.parenttype == CONTACT)
			.where(child.email_id == value)
			.run(as_dict=True)
		)
		for row in rows:
			if normalize_identifier("Email", row.email_id) == value:
				found.setdefault((CONTACT, row.parent), reason)
		return found

	reason = PHONE_REASON
	for doctype in (LEAD, DEAL):
		for row in _phone_rows(doctype, ["mobile_no", "phone"], value):
			found.setdefault((doctype, row.name), reason)
	for row in _phone_rows(CONTACT, ["mobile_no"], value):
		found.setdefault((CONTACT, row.name), reason)
	child = frappe.qb.DocType("Contact Phone")
	digits = phone_search_digits(value, PHONE_REGION)
	if digits:
		rows = (
			frappe.qb.from_(child)
			.select(child.parent, child.phone)
			.where(child.parenttype == CONTACT)
			.where(_digits(child.phone).like(f"%{digits}%"))
			.run(as_dict=True)
		)
		for row in rows:
			if normalize_identifier("Phone", row.phone) == value:
				found.setdefault((CONTACT, row.parent), reason)
	return found


def _identifier_values(request) -> list[tuple[str, str]]:
	seen: list[tuple[str, str]] = []
	for row in request.identifiers:
		if row.excluded:
			continue
		value = normalize_identifier(row.kind, row.value)
		if value and (row.kind, value) not in seen:
			seen.append((row.kind, value))
	return seen


def _confirmed(request, doctype: str) -> list[str]:
	return [m.reference_name for m in request.matches if m.confirmed and m.reference_doctype == doctype]


def contact_identifiers(contact: str) -> list[tuple[str, str]]:
	emails = frappe.get_all(
		"Contact Email", filters={"parent": contact, "parenttype": CONTACT}, pluck="email_id", parent_doctype=CONTACT
	)
	phones = frappe.get_all(
		"Contact Phone", filters={"parent": contact, "parenttype": CONTACT}, pluck="phone", parent_doctype=CONTACT
	)
	phones.append(frappe.db.get_value(CONTACT, contact, "mobile_no"))
	return [("Email", e) for e in emails] + [("Phone", p) for p in phones]


def lead_identifiers(lead: str) -> list[tuple[str, str]]:
	email, mobile_no, phone = frappe.db.get_value(LEAD, lead, ["email", "mobile_no", "phone"]) or (None,) * 3
	return [("Email", email), ("Phone", mobile_no), ("Phone", phone)]


def sync_identifiers(request) -> None:
	"""Add `Record` identifiers for every email and phone on confirmed leads and contacts.

	Never removes a row and never touches `excluded`.
	"""
	have = {(row.kind, normalize_identifier(row.kind, row.value)) for row in request.identifiers}
	candidates = []
	for lead in _confirmed(request, LEAD):
		candidates += lead_identifiers(lead)
	for contact in _confirmed(request, CONTACT):
		candidates += contact_identifiers(contact)
	for kind, raw in candidates:
		value = normalize_identifier(kind, raw)
		if not value or (kind, value) in have:
			continue
		have.add((kind, value))
		request.append("identifiers", {"kind": kind, "value": value, "source": "Record", "excluded": 0})


def find_matches(request) -> list[dict]:
	"""Records that match the request's non-excluded identifiers, plus their linked deals."""
	found: dict[tuple[str, str], str] = {}
	for kind, value in _identifier_values(request):
		for key, reason in _records_for_identifier(kind, value).items():
			found.setdefault(key, reason)

	leads = _confirmed(request, LEAD)
	contacts = _confirmed(request, CONTACT)
	if leads:
		for name in frappe.get_all(DEAL, filters={"lead": ["in", leads]}, pluck="name"):
			found.setdefault((DEAL, name), CONVERTED_REASON)
	if contacts:
		deals = frappe.get_all(
			"CRM Contacts",
			filters={"contact": ["in", contacts], "parenttype": DEAL},
			pluck="parent",
			parent_doctype=DEAL,
		)
		for name in deals:
			found.setdefault((DEAL, name), CONTACT_LISTED_REASON)

	return [
		{"reference_doctype": doctype, "reference_name": name, "title": record_title(doctype, name), "reason": reason}
		for (doctype, name), reason in found.items()
	]


def refresh_matches(request) -> None:
	"""Pull identifiers from confirmed records, then (re)suggest matches, at most 3 rounds.

	New suggestions are appended unconfirmed, unconfirmed rows that are no longer
	suggested are dropped, confirmed rows stay. Does not save.
	"""
	suggestions: list[dict] = []
	for _round in range(MAX_ROUNDS):
		before = len(request.identifiers)
		sync_identifiers(request)
		suggestions = find_matches(request)
		if len(request.identifiers) == before:
			break

	suggested = {(s["reference_doctype"], s["reference_name"]) for s in suggestions}
	for row in list(request.matches):
		if not row.confirmed and (row.reference_doctype, row.reference_name) not in suggested:
			request.remove(row)
	have = {(row.reference_doctype, row.reference_name) for row in request.matches}
	for suggestion in suggestions:
		if (suggestion["reference_doctype"], suggestion["reference_name"]) not in have:
			request.append("matches", {**suggestion, "confirmed": 0})
	for idx, row in enumerate(request.matches, start=1):
		row.idx = idx


def _addresses(*texts: str | None) -> set[str]:
	found = set()
	for text in texts:
		for match in _EMAIL_IN_TEXT.findall(text or ""):
			found.add(match.strip().lower())
	return found


def _count_emails(value: str) -> int:
	table = frappe.qb.DocType("Communication")
	columns = ("sender", "recipients", "cc", "bcc")
	rows = (
		frappe.qb.from_(table)
		.select(*[getattr(table, c) for c in columns])
		.where(Criterion.any([getattr(table, c).like(f"%{value}%") for c in columns]))
		.run(as_dict=True)
	)
	return sum(1 for row in rows if value in _addresses(*[row.get(c) for c in columns]))


def identifier_usage(request) -> list[dict]:
	"""How widely each identifier appears: records, email threads and call logs."""
	usage = []
	for row in request.identifiers:
		value = normalize_identifier(row.kind, row.value)
		records = emails = calls = 0
		if value:
			records = len(_records_for_identifier(row.kind, value))
			if row.kind == "Email":
				emails = _count_emails(value)
			else:
				calls = len(_phone_rows("CRM Call Log", ["from", "to"], value))
		usage.append(
			{
				"kind": row.kind,
				"value": row.value,
				"excluded": int(row.excluded or 0),
				"records": records,
				"emails": emails,
				"calls": calls,
			}
		)
	return usage
