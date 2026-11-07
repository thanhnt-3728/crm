# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Small read-only queries the plan builder shares. SQL only prefilters; callers confirm every candidate with
`value_matcher` / `text_mentions` (RT-4)."""

import frappe

from crm.privacy.erasure.value_matcher import like_literal

# doctype -> names. The records whose own notes, mail, calls and files are hers: her leads, contacts, and the
# deals she is on.
Scope = dict


def by_reference(doctype: str, type_field: str, name_field: str, scope: Scope, **filters) -> list[str]:
	"""Names of `doctype` rows that point at one of the scope's records through a (doctype, name) field pair."""
	found = []
	for target, names in scope.items():
		if names:
			rows = frappe.get_all(
				doctype, {type_field: target, name_field: ["in", names], **filters}, pluck="name"
			)
			found += rows
	return found


def child_parents(child: str, parent_type: str, scope: Scope) -> list[str]:
	"""Parents of child rows (Dynamic Link / Communication Link style) that link to one of the scope's records."""
	Row = frappe.qb.DocType(child)
	found = []
	for target, names in scope.items():
		if names:
			query = frappe.qb.from_(Row).select(Row.parent)
			found += query.where(
				(Row.parenttype == parent_type) & (Row.link_doctype == target) & Row.link_name.isin(names)
			).run(pluck=True)
	return found


def like_candidates(doctype: str, fields: list[str], terms: list[str], **filters) -> list[frappe._dict]:
	"""Rows of `doctype` (name and `fields`) where any of the fields contains any of the terms. A superset."""
	if not terms:
		return []
	Table = frappe.qb.DocType(doctype)
	condition = None
	for field in fields:
		for term in terms:
			clause = Table[field].like(f"%{like_literal(term)}%")
			condition = clause if condition is None else condition | clause
	query = frappe.qb.from_(Table).select(Table.name, *[Table[f] for f in fields]).where(condition)
	for key, value in filters.items():
		query = query.where(Table[key] == value)
	return [frappe._dict(zip(["name", *fields], row, strict=True)) for row in query.run()]


def present(doctype: str) -> bool:
	"""The doctype's table exists (an app that ships it may not be installed)."""
	return frappe.db.table_exists(doctype)
