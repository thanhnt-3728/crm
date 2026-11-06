# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Residual check: an independent raw-SQL oracle for "none of her identifiers is left" (F7)

It shares no query code with discovery: every text column of a table is searched in SQL, emails
with LOWER(col) LIKE plus a REGEXP with address boundaries (`ann@x.com` never hits
`joann@x.com`), phones by their national digits inside the digits-only column
(REGEXP_REPLACE). Rows of excluded matches (the row itself, its parent, the record a Version or
search row belongs to) do not count. Results are table names only, never values.

- `residual_hits(ids)`: registry tables only; run by the job before it commits.
- `full_scan(ids)`: every table but the request's own; slow, for tests and the runbook:
  `bench --site <site> execute crm.erasure.verify.full_scan_request --kwargs "{'name': 'CRM-ERQ-...'}"`
"""

import re
from collections.abc import Iterable

import frappe

from crm.erasure import registry_model as model
from crm.erasure.discovery import installed
from crm.erasure.identifiers import _AFTER, _BEFORE, Identifiers
from crm.erasure.registry import REGISTRY

REQUEST = "CRM Erasure Request"
REQUEST_TABLES = ("tabCRM Erasure Request", "tabCRM Erasure Identifier", "tabCRM Erasure Match")
TEXT_TYPES = ("char", "varchar", "tinytext", "text", "mediumtext", "longtext", "json")
TEXT_TYPES += ("character", "character varying", "jsonb")  # Postgres spellings
# (doctype column, name column) naming the record a row belongs to
OWNER_COLUMNS = (("parenttype", "parent"), ("ref_doctype", "docname"))
RAW_TABLE_OWNER = {"__global_search": ("doctype", "name")}
# "@" as URL-encoded (webhook payloads, logged URLs) and as an HTML entity. Before an encoded
# address, "=" and "&" are separators ("email=ann%40x.com"), not address characters.
EMAIL_ENCODINGS = ("%40", "&#64;")
ENCODED_BEFORE = r"(?<![\w.%+'-])"


def residual_hits(
	ids: Identifiers, tables: Iterable[str] | None = None, excluded=frozenset(), tokens: tuple[str, ...] = ()
) -> list[str]:
	"""Sorted names of `tables` (default: the registry's) holding one of her identifiers

	`tokens`: extra literal strings searched case-insensitively (tests: her full name).
	"""
	tables = registry_tables() if tables is None else tables
	tokens = tuple(token.lower() for token in tokens if token)
	return sorted(table for table in set(tables) if _table_hits(table, ids, set(excluded), tokens))


def full_scan(ids: Identifiers, excluded=frozenset()) -> list[str]:
	"""`residual_hits` over every table of the site except the request's own"""
	tables = frappe.db.sql(
		f"select table_name from information_schema.tables where {_dialect()['schema']} "
		"and table_type = 'BASE TABLE'",
		pluck=True,
	)
	return residual_hits(ids, [t for t in tables if t not in REQUEST_TABLES], excluded)


def full_scan_request(name: str) -> list[str]:
	"""`full_scan` with a request's identifiers and exclusions (bench execute / runbook)"""
	request = frappe.get_doc(REQUEST, name)
	excluded = {(row.ref_doctype, row.ref_name) for row in request.matches if row.excluded}
	return full_scan(Identifiers.from_rows(request.identifiers), excluded)


def registry_tables() -> list[str]:
	"""Tables of the installed registry entries, with the child tables they read or empty"""
	tables = set()
	for entry in REGISTRY:
		if not installed(entry) or entry.doctype == "_comments":  # `_comments` is a column, not a table
			continue
		tables.add(entry.table or f"tab{entry.doctype}")
		tables.update(f"tab{f.child_doctype}" for f in entry.finders if getattr(f, "child_doctype", None))
		for spec in entry.fields:
			if spec[1] in (model.DELETE_ROWS, model.DROP_HER_LINKS):
				tables.add(f"tab{frappe.get_meta(entry.doctype).get_field(spec[0]).options}")
	return sorted(tables)


def _table_hits(table: str, ids: Identifiers, excluded: set, tokens: tuple[str, ...] = ()) -> bool:
	if not ids and not tokens:
		return False
	dialect = _dialect()
	columns = dict(
		frappe.db.sql(
			f"select column_name, data_type from information_schema.columns where {dialect['schema']} "
			"and table_name = %s",
			table,
		)
	)
	text = [column for column, data_type in columns.items() if data_type.lower() in TEXT_TYPES]
	if not text:
		return False
	conditions, values = [], []
	for column in text:
		fragment, fragment_values = column_conditions(dialect["quote"].format(column), ids, tokens)
		conditions.append(fragment)
		values += fragment_values
	owners = _owner_columns(table, columns)
	select = ", ".join(dialect["quote"].format(c) for c in sorted({c for pair in owners for c in pair if c})) or "1"
	rows = frappe.db.sql(
		f"select {select} from {dialect['quote'].format(table)} where {' or '.join(conditions)}",
		values,
		as_dict=True,
	)
	own_doctype = table[3:] if table.startswith("tab") else None
	return any(not _excluded_row(row, owners, own_doctype, excluded) for row in rows)


def column_conditions(
	quoted_column: str, ids: Identifiers, tokens: tuple[str, ...] = ()
) -> tuple[str, list[str]]:
	"""WHERE fragment "(... or ...)" true when one text column holds an identifier (or a token)

	`quoted_column` is already quoted for the database (e.g. `content` in backticks). Values are positional
	(`%s`), in order. Emails (also with "@" as %40 or &#64;): LOWER LIKE prefilter plus a boundary
	REGEXP; phones: national digits
	inside the digits-only value; tokens (lower-cased by the caller): LOWER LIKE. ("", []) when
	there is nothing to search for. Shared with the runbook's generated SQL.
	"""
	dialect = _dialect()
	conditions, values = [], []
	for email in sorted(ids.emails):
		for spelling, pattern in ((email, _BEFORE + re.escape(email) + _AFTER), *encoded_email_patterns(email)):
			conditions.append(f"(lower({quoted_column}) like %s and lower({quoted_column}) {dialect['regexp']} %s)")
			values += [f"%{_like_escape(spelling)}%", pattern]
	for token in tokens:
		conditions.append(f"lower({quoted_column}) like %s")
		values.append(f"%{_like_escape(token)}%")
	for digits in ids.search_digits:
		conditions.append(f"{dialect['digits'].format(quoted_column)} like %s")
		values.append(f"%{digits}%")
	return (f"({' or '.join(conditions)})", values) if conditions else ("", [])


def encoded_email_patterns(email: str) -> list[tuple[str, str]]:
	"""[(encoded spelling, boundary regex)] of `email` with "@" encoded (EMAIL_ENCODINGS)"""
	spellings = [email.replace("@", encoding) for encoding in EMAIL_ENCODINGS]
	return [(spelling, ENCODED_BEFORE + re.escape(spelling) + _AFTER) for spelling in spellings]


def _owner_columns(table: str, columns: dict) -> list[tuple[str, str]]:
	"""(doctype column, name column) pairs of `table`; "" as doctype column = the table's own doctype"""
	if table in RAW_TABLE_OWNER:
		return [RAW_TABLE_OWNER[table]]
	pairs = [("", "name")] if "name" in columns else []
	return pairs + [pair for pair in OWNER_COLUMNS if set(pair) <= set(columns)]


def _excluded_row(row: dict, owners, own_doctype: str | None, excluded: set) -> bool:
	"""True when the row, its parent, or the record it copies is excluded (or is the request)"""
	for doctype_column, name_column in owners:
		doctype = row.get(doctype_column) if doctype_column else own_doctype
		if doctype == REQUEST or (doctype, str(row.get(name_column))) in excluded:
			return True
	return False


def _like_escape(value: str) -> str:
	return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _dialect() -> dict:
	if frappe.db.db_type == "postgres":
		return {
			"schema": "table_schema = 'public'",
			"quote": '"{}"',
			"regexp": "~",
			"digits": "regexp_replace({}::text, '[^0-9]', '', 'g')",
		}
	return {
		"schema": "table_schema = database()",
		"quote": "`{}`",
		"regexp": "regexp",
		"digits": "regexp_replace({}, '[^0-9]', '')",
	}
