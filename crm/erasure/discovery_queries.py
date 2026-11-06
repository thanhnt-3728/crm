# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""One read-only query per finder kind (see registry_model)

Identifier columns are prefiltered in SQL (LIKE on the address; LIKE on the digits-only value
for phone columns, on the last four digits for free text) and then compared exactly in Python
with `Identifiers`, so the prefilter may be loose but a match never is. Every function returns the matching row keys (doc names).
"""

import operator
from functools import reduce

import frappe
from frappe.query_builder import CustomFunction

from crm.erasure import registry_model as model
from crm.erasure.identifiers import Identifiers

RegexpReplace = CustomFunction("REGEXP_REPLACE", ["value", "pattern", "replacement"])
# Raw tables have no `name` primary key: a row is keyed by the record it indexes
TABLE_KEYS = {"__global_search": ("doctype", "name")}

Matched = dict[str, dict[str, str]]  # doctype -> {name: reason}


def find(entry: model.Entry, finder, matched: Matched, ids: Identifiers) -> set[str]:
	"""Row keys of `entry` that `finder` selects, given the matches found so far"""
	handler = _HANDLERS[type(finder)]
	return handler(entry, finder, matched, ids)


def _ref(entry, finder: model.Ref, matched, ids):
	table = _table(entry)
	conditions = [
		(table[finder.doctype_column] == doctype) & table[finder.name_column].isin(names)
		for doctype, names in _targets(finder.targets, matched)
	]
	return _keys(entry, table, conditions)


def _link(entry, finder: model.Link, matched, ids):
	names = sorted(matched.get(finder.target, ()))
	table = _table(entry)
	return _keys(entry, table, [table[finder.column].isin(names)] if names else [])


def _child_link(entry, finder: model.ChildLink, matched, ids):
	child = frappe.qb.DocType(finder.child_doctype)
	conditions = [
		(child.link_doctype == doctype) & child.link_name.isin(names)
		for doctype, names in _targets(finder.targets, matched)
	]
	if not conditions:
		return set()
	query = frappe.qb.from_(child).select(child.parent).distinct().where(child.parenttype == entry.doctype)
	return set(query.where(_any(conditions)).run(pluck=True))


def _backref(entry, finder: model.Backref, matched, ids):
	sources = sorted(matched.get(finder.source, ()))
	if not sources:
		return set()
	values = {v for v in frappe.get_all(finder.source, {"name": ["in", sources]}, pluck=finder.column) if v}
	table = _table(entry)
	return _keys(entry, table, [table[finder.by].isin(sorted(values))] if values else [])


def _child_backref(entry, finder: model.ChildBackref, matched, ids):
	sources = sorted(matched.get(finder.source, ()))
	if not sources:
		return set()
	child = frappe.qb.DocType(finder.child_doctype)
	names = (
		frappe.qb.from_(child)
		.select(child.link_name)
		.where(child.parenttype == finder.source)
		.where(child.parent.isin(sources))
		.where(child.link_doctype == entry.doctype)
	).run(pluck=True)
	table = _table(entry)
	return _keys(entry, table, [table.name.isin(sorted(set(names)))] if names else [])


def _emails(entry, finder: model.Emails, matched, ids):
	return _scan(
		entry, finder, [_contains(email) for email in sorted(ids.emails)], ids.matches_email, digits=False
	)


def _phones(entry, finder: model.Phones, matched, ids):
	return _scan(entry, finder, [_contains(d) for d in ids.search_digits], ids.matches_phone, digits=True)


def _text(entry, finder: model.Text, matched, ids):
	# Large text/JSON columns: REGEXP_REPLACE over every row is too slow there (~1 ms per traceback),
	# so phones are prefiltered on their last four digits, which every common spelling keeps together
	patterns = [_contains(email) for email in sorted(ids.emails)] + [
		_contains(d[-4:]) for d in ids.search_digits
	]
	return _scan(entry, finder, patterns, ids.matches_text, digits=False)


def _scan(entry, finder, patterns: list[str], confirm, digits: bool) -> set[str]:
	"""Prefilter `finder.columns` with LIKE `patterns`, then keep rows `confirm` accepts"""
	if not patterns:
		return set()
	child_doctype = getattr(finder, "child_doctype", None)
	table = frappe.qb.DocType(child_doctype) if child_doctype else _table(entry)
	columns = [table[column] for column in finder.columns]
	conditions = [
		(RegexpReplace(column, "[^0-9]", "") if digits else column).like(pattern)
		for column in columns
		for pattern in patterns
	]
	if child_doctype:
		key_columns = [table.parent.as_("_key")]
		query = frappe.qb.from_(table).select(*key_columns, *columns).where(table.parenttype == entry.doctype)
	else:
		query = frappe.qb.from_(table).select(*_key_columns(entry, table), *columns)
	rows = query.where(_any(conditions)).run(as_dict=True)
	return {
		_row_key(entry, row, child_doctype)
		for row in rows
		if any(confirm(row.get(column)) for column in finder.columns)
	}


def _contains(value: str) -> str:
	"""LIKE pattern for "contains `value`", with LIKE wildcards in the value escaped"""
	escaped = value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
	return f"%{escaped}%"


def _keys(entry, table, conditions) -> set[str]:
	if not conditions:
		return set()
	rows = (
		frappe.qb.from_(table).select(*_key_columns(entry, table)).where(_any(conditions)).run(as_dict=True)
	)
	return {_row_key(entry, row) for row in rows}


def _key_columns(entry, table) -> list:
	columns = TABLE_KEYS.get(entry.table, ("name",))
	return [table[column].as_(f"_key{index}") for index, column in enumerate(columns)]


def _row_key(entry, row, child_doctype=None) -> str:
	if child_doctype:
		return row["_key"]
	parts = [row[f"_key{index}"] for index in range(len(TABLE_KEYS.get(entry.table, ("name",))))]
	return "::".join(str(part) for part in parts)


def _table(entry):
	return frappe.qb.Table(entry.table) if entry.table else frappe.qb.DocType(entry.doctype)


def _targets(targets: tuple[str, ...], matched) -> list[tuple[str, list[str]]]:
	doctypes = sorted(matched) if targets == model.ANY_MATCH else targets
	return [(doctype, sorted(matched[doctype])) for doctype in doctypes if matched.get(doctype)]


def _any(conditions):
	return reduce(operator.or_, conditions)


_HANDLERS = {
	model.Ref: _ref,
	model.Link: _link,
	model.ChildLink: _child_link,
	model.Backref: _backref,
	model.ChildBackref: _child_backref,
	model.Emails: _emails,
	model.Phones: _phones,
	model.Text: _text,
}
