# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Preview of a request's matches (F4): grouped by doctype in registry order, with hidden-copy counts

A row is listed (name, title, key) only when the session user may read its record; every other
row is only counted per doctype (`unreadable`), so a preview never reveals which records exist.
`identifiers_not_on_subject` warns which identifiers are on none of her records (kind and
position only). Hidden-copy counts come from the last discovery run (cached per request version), because they
need text scans over large tables. Identifiers are never part of the payload.
"""

import frappe

from crm.erasure.discovery import hidden_counts
from crm.erasure.match_rows import format_key, match_row
from crm.erasure.registry import registry_position
from crm.erasure.source_identifiers import identifiers_not_on_subject

HIDDEN_CACHE_SECONDS = 15 * 60


def preview(request, hidden: dict[str, int] | None = None) -> dict:
	"""Payload for `request`; `hidden` = counts the caller just computed (stored for later previews)"""
	rows_by_doctype: dict[str, list[dict]] = {}
	for row in request.get("matches") or []:
		cleaned = match_row(row)
		rows_by_doctype.setdefault(cleaned["ref_doctype"], []).append(cleaned)

	groups = []
	for doctype in sorted(rows_by_doctype, key=registry_position):
		rows = rows_by_doctype[doctype]
		titles = readable_titles(doctype, [row["ref_name"] for row in rows])
		listed = [
			{"key": format_key(doctype, row["ref_name"]), "title": titles[row["ref_name"]], **row}
			for row in rows
			if row["ref_name"] in titles
		]
		groups.append(
			{
				"doctype": doctype,
				"count": len(rows),
				"excluded": sum(row["excluded"] for row in rows),
				"unreadable": len(rows) - len(listed),
				"rows": listed,
			}
		)
	return {
		"name": request.name,
		"status": request.status,
		"hold_reason": request.hold_reason,
		"ack_due": request.ack_due,
		"response_due": request.response_due,
		"groups": groups,
		"hidden": cached_hidden_counts(request, hidden),
		"identifiers_not_on_subject": identifiers_not_on_subject(request),
	}


def readable_keys(request) -> set[tuple[str, str]]:
	"""(ref_doctype, ref_name) of the matches the session user may read"""
	names: dict[str, list[str]] = {}
	for row in request.get("matches") or []:
		names.setdefault(row.get("ref_doctype"), []).append(row.get("ref_name"))
	return {(doctype, name) for doctype, batch in names.items() for name in readable_titles(doctype, batch)}


def readable_titles(doctype: str, names: list[str]) -> dict[str, str | None]:
	"""{name: title or None} for the existing records of `names` the session user may read

	A child row (a deal's CRM Contacts row) is readable when its parent record is.
	"""
	meta = frappe.get_meta(doctype)
	if meta.istable:
		rows = frappe.get_all(doctype, {"name": ["in", names]}, ["name", "parenttype", "parent"])
		return {
			row.name: None
			for row in rows
			if row.parenttype and frappe.has_permission(row.parenttype, "read", doc=row.parent)
		}
	title_field = meta.get_title_field()
	fields = ["name"] if title_field == "name" else ["name", title_field]
	rows = frappe.get_all(doctype, {"name": ["in", names]}, fields)
	return {
		str(row.name): (None if title_field == "name" else row.get(title_field))
		for row in rows
		if frappe.has_permission(doctype, "read", doc=row.name)
	}


def cached_hidden_counts(request, computed: dict[str, int] | None = None) -> dict[str, int]:
	"""Hidden counts for this version of `request`: `computed`, else the cache, else a fresh count"""
	key = f"crm:erasure:hidden:{request.name}:{request.modified}"
	if computed is None:
		computed = frappe.cache.get_value(key)
	if computed is None:
		computed = hidden_counts(request)
	frappe.cache.set_value(key, computed, expires_in_sec=HIDDEN_CACHE_SECONDS)
	return computed
