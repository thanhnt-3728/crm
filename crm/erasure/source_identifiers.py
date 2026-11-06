# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Does the person behind the source record own at least one of the identifiers the rep typed?

Logging a request with someone else's email would turn discovery into a lookup of who else uses
that address, so `log_request` requires one identifier to be on the source record itself. The
columns are the source entry's own Emails / Phones finders in the registry (Lead and Deal:
email, mobile_no, phone; Contact: email_id, phone, mobile_no and its Contact Email / Phone rows).
"""

import frappe

from crm.erasure import registry_model as model
from crm.erasure.identifiers import Identifiers
from crm.erasure.registry import entry_for

SUBJECT_DOCTYPES = ("CRM Lead", "CRM Deal", "Contact")


def identifiers_match_source(doctype: str, name: str, ids: Identifiers) -> bool:
	emails, phones = _contact_values([(doctype, name)])
	return any(ids.matches_email(v) for v in emails) or any(ids.matches_phone(v) for v in phones)


def identifiers_not_on_subject(request) -> list[dict]:
	"""[{"kind", "position"}] of the request's identifiers found on none of her person records

	Her records: the source and the non-excluded CRM Lead / CRM Deal / Contact matches. A rep must
	put one identifier from the source on the request, but the others could be a stranger's: the
	approver sees which ones are unconfirmed. Kinds and positions only (1-based per kind), never values.
	"""
	records = {(request.source_doctype, request.source_docname)}
	for row in request.get("matches") or []:
		if row.get("ref_doctype") in SUBJECT_DOCTYPES and not row.get("excluded"):
			records.add((row.get("ref_doctype"), row.get("ref_name")))
	emails, phones = _contact_values(sorted(records))
	unconfirmed, positions = [], {}
	for row in request.get("identifiers") or []:
		kind = row.get("kind")
		positions[kind] = positions.get(kind, 0) + 1
		try:
			ids = Identifiers.from_rows([row])
		except ValueError:
			ids = Identifiers()  # cannot be confirmed either
		values, matches = (emails, ids.matches_email) if kind == "Email" else (phones, ids.matches_phone)
		if not any(matches(value) for value in values):
			unconfirmed.append({"kind": kind, "position": positions[kind]})
	return unconfirmed


def _contact_values(records) -> tuple[list, list]:
	"""(emails, phones) stored on `records` [(doctype, name)], read through the registry finders"""
	emails, phones = [], []
	for doctype, name in records:
		if doctype not in SUBJECT_DOCTYPES or not name:
			continue
		for finder in entry_for(doctype).finders:
			if isinstance(finder, model.Emails):
				emails += _values(doctype, name, finder)
			elif isinstance(finder, model.Phones):
				phones += _values(doctype, name, finder)
	return emails, phones


def _values(doctype: str, name: str, finder) -> list:
	columns = list(finder.columns)
	if finder.child_doctype:
		rows = frappe.get_all(
			finder.child_doctype, {"parenttype": doctype, "parent": name}, columns, ignore_permissions=True
		)
	else:
		rows = frappe.get_all(doctype, {"name": name}, columns, ignore_permissions=True)
	return [row.get(column) for row in rows for column in columns if row.get(column)]
