# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Look up erasure requests that point at a document, as their source or a non-excluded match"""

from collections.abc import Iterable

import frappe

REQUEST = "CRM Erasure Request"
MATCH = "CRM Erasure Match"
# The person records whose open deals hold a request
SUBJECT_DOCTYPES = ("CRM Lead", "CRM Deal", "Contact")


def requests_referencing(
	doctype: str, names: Iterable[str], states: Iterable[str], skip_existence_check: bool = False
) -> list[str]:
	"""Names of requests in `states` whose source or a non-excluded match is one of `names`

	`skip_existence_check`: the caller already ran `has_requests_in(states)`.
	"""
	names, states = sorted({n for n in names if n}), list(states)
	if not names or not (skip_existence_check or has_requests_in(states)):
		return []

	found = set(
		frappe.get_all(
			REQUEST,
			filters={"source_doctype": doctype, "source_docname": ["in", names], "status": ["in", states]},
			pluck="name",
		)
	)
	request, match = frappe.qb.DocType(REQUEST), frappe.qb.DocType(MATCH)
	rows = (
		frappe.qb.from_(match)
		.join(request)
		.on(request.name == match.parent)
		.select(request.name)
		.where(match.parenttype == REQUEST)
		.where(match.parentfield == "matches")
		.where(match.ref_doctype == doctype)
		.where(match.ref_name.isin(names))
		.where(match.excluded == 0)
		.where(request.status.isin(states))
	).run(pluck=True)
	return sorted(found.union(rows))


def has_requests_in(states: list[str]) -> bool:
	"""Cheap early exit for hooks; False while the table does not exist yet (install, pre-sync patches)"""
	try:
		return bool(frappe.db.exists(REQUEST, {"status": ["in", states]}))
	except Exception as e:
		if frappe.db.is_table_missing(e):
			return False
		raise


def rewrite_references(doctype: str, old: str, new: str) -> None:
	"""Point sources and matches at a renamed record, so the request's audit trail follows it"""
	request, match = frappe.qb.DocType(REQUEST), frappe.qb.DocType(MATCH)
	(
		frappe.qb.update(request)
		.set(request.source_docname, new)
		.where(request.source_doctype == doctype)
		.where(request.source_docname == old)
	).run()
	(
		frappe.qb.update(match)
		.set(match.ref_name, new)
		.where(match.parenttype == REQUEST)
		.where(match.ref_doctype == doctype)
		.where(match.ref_name == old)
	).run()


def subject_refs(request) -> dict[str, set[str]]:
	"""{doctype: names} of the person records that identify the request's subject"""
	refs = {doctype: set() for doctype in SUBJECT_DOCTYPES}
	if request.source_doctype in refs and request.source_docname:
		refs[request.source_doctype].add(request.source_docname)
	for row in request.get("matches") or []:
		if row.ref_doctype in refs and row.ref_name and not row.excluded:
			refs[row.ref_doctype].add(row.ref_name)
	return refs
