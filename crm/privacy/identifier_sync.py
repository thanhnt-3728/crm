# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Confirming matches, the confirmed-identifier list and what each identifier would reach (design 5.3).

These functions change the request document in memory only; the API function saves it inside `server_write()`.
"""

from email.utils import getaddresses

import frappe
from frappe import _
from frappe.utils import cint

from crm.privacy.identifiers import PHONE_REGION, normalize_email, validate_identifier
from crm.privacy.matching import (
	CONTACT,
	LEAD,
	add_linked_suggestions,
	can_read,
	digits_only,
	find_by_email,
	find_by_phone,
	same_number,
)
from crm.privacy.request_intake import add_identifier
from crm.privacy.request_visibility import is_compliance
from crm.utils import normalize_phone, phone_search_digits

# Rows of Communication read per email identifier. A shared inbox could match thousands; past this the count is
# a floor and the impact says so (`capped`).
COMMUNICATION_SCAN_LIMIT = 5000


def _stored_values(doctype: str, name: str) -> list[tuple[str, str, str]]:
	"""(kind, field, value) for every email and phone the record holds."""
	if doctype == LEAD:
		lead = frappe.db.get_value(LEAD, name, ["email", "mobile_no", "phone"], as_dict=True) or {}
		return [
			("email", "email", lead.get("email")),
			*[("phone", f, lead.get(f)) for f in ("mobile_no", "phone")],
		]
	Email, Phone = frappe.qb.DocType("Contact Email"), frappe.qb.DocType("Contact Phone")
	emails = (
		frappe.qb.from_(Email)
		.select(Email.email_id)
		.where((Email.parent == name) & (Email.parenttype == CONTACT))
	)
	phones = (
		frappe.qb.from_(Phone)
		.select(Phone.phone)
		.where((Phone.parent == name) & (Phone.parenttype == CONTACT))
	)
	return [("email", "email_id", v) for v in emails.run(pluck=True)] + [
		("phone", "phone", v) for v in phones.run(pluck=True)
	]


def pull_identifiers(doc, doctype: str, name: str) -> list[dict]:
	"""Add every usable email and phone of a confirmed lead or contact as a Record identifier.
	Returns the stored values that are not usable (RT-4) as `{doctype, name, field, value}`."""
	skipped = []
	for kind, field, value in _stored_values(doctype, name):
		value = (value or "").strip()
		if not value:
			continue
		try:
			validate_identifier(kind, value)
		except frappe.ValidationError:
			frappe.clear_last_message()
			skipped.append({"doctype": doctype, "name": name, "field": field, "value": value})
			continue
		add_identifier(doc, kind, value, typed=False, source=(doctype, name))
	return skipped


def _row_named(rows, name: str, what: str):
	row = next((r for r in rows if r.name == name), None)
	if not row:
		frappe.throw(_("No such {0} on this request").format(what))
	return row


def apply_confirmation(doc, row_name: str, confirmed, user: str) -> list[dict]:
	"""Confirm or unconfirm a match row. Returns the skipped identifiers (see `pull_identifiers`).
	Refuses the starting record, a record the user cannot read (RT-5) and confirming one that is gone."""
	row = _row_named(doc.matches, row_name, _("match"))
	if row.is_source:
		frappe.throw(_("The record the request was started from cannot be changed"))
	if not can_read(user, row.reference_doctype, row.reference_name) and not is_compliance(user):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	row.confirmed = cint(confirmed)
	if not row.confirmed:
		return []
	if not frappe.db.exists(row.reference_doctype, row.reference_name):
		frappe.throw(_("{0} no longer exists").format(row.reference_name))
	skipped = []
	if row.reference_doctype in (LEAD, CONTACT):
		skipped = pull_identifiers(doc, row.reference_doctype, row.reference_name)
	add_linked_suggestions(doc, user)
	return skipped


def set_excluded(doc, row_name: str, excluded) -> None:
	_row_named(doc.identifiers, row_name, _("identifier")).excluded = cint(excluded)


def _like_literal(value: str) -> str:
	return value.replace("%", r"\%").replace("_", r"\_")


def _communications(email: str) -> tuple[int, bool]:
	"""(emails that name `email` as sender, recipient, cc or bcc, whether the scan hit its limit). The SQL
	prefilters and reads at most `COMMUNICATION_SCAN_LIMIT` rows; the address lists decide."""
	email = normalize_email(email)
	Mail = frappe.qb.DocType("Communication")
	pattern = f"%{_like_literal(email)}%"
	query = (
		frappe.qb.from_(Mail)
		.select(Mail.sender, Mail.recipients, Mail.cc, Mail.bcc)
		.where(
			Mail.sender.like(pattern)
			| Mail.recipients.like(pattern)
			| Mail.cc.like(pattern)
			| Mail.bcc.like(pattern)
		)
		.limit(COMMUNICATION_SCAN_LIMIT + 1)
	)
	rows = query.run()
	count = sum(
		1
		for fields in rows[:COMMUNICATION_SCAN_LIMIT]
		if email in {a.lower() for f in fields if f for _n, a in getaddresses([f])}
	)
	return count, len(rows) > COMMUNICATION_SCAN_LIMIT


def _call_logs(phone: str) -> int:
	target = normalize_phone(phone, region=PHONE_REGION)
	digits = phone_search_digits(phone, region=PHONE_REGION)
	if not (target and digits):
		return 0
	Call = frappe.qb.DocType("CRM Call Log")
	pattern = f"%{digits}%"
	query = (
		frappe.qb.from_(Call)
		.select(Call["from"], Call["to"])
		.where(digits_only(Call["from"]).like(pattern) | digits_only(Call["to"]).like(pattern))
	)
	return sum(1 for numbers in query.run() if any(same_number(n, target) for n in numbers))


def identifier_impact(doc, user: str) -> list[dict]:
	"""Per identifier, what it reaches. `records` counts only what `user` can read; the email and call counts and
	`capped` (the email scan hit its limit, so `communications` is a floor) are Compliance's alone and are None for
	everyone else (RT-5)."""
	full = is_compliance(user)
	impact = []
	for identifier in doc.identifiers:
		is_email = identifier.kind == "Email"
		hits = (find_by_email if is_email else find_by_phone)(identifier.value)
		communications, capped = _communications(identifier.value) if is_email and full else (0, False)
		impact.append(
			{
				"row": identifier.name,
				"kind": identifier.kind,
				"value": identifier.value,
				"excluded": identifier.excluded,
				"records": sum(1 for h in hits if can_read(user, h["doctype"], h["name"])),
				"communications": communications if full else None,
				"call_logs": (0 if is_email else _call_logs(identifier.value)) if full else None,
				"capped": capped if full else None,
			}
		)
	return impact
