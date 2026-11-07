# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Scan every text-like column of every table for a person's values (phase 08).

A list of tables someone remembered cannot catch the table nobody thought of (a new custom field, a log another app
added). `scan(patterns)` asks the database itself: one query per table, one regular expression per column.
`patterns` is {label: regex}; the result is {(table, column): {label: rows}} for the columns that hold any of them.

`__global_search` is MyISAM: rows that earlier test runs left behind (46k of them, thousands naming the same fixture
person) outlive every rollback. `known_rows` ({table: {row key}}) lists the rows to ignore; keys are `(doctype, name)`.
"""

import re

import frappe

TEXT_TYPES = ("char", "varchar", "tinytext", "text", "mediumtext", "longtext", "json")
NOT_DIGIT = "[^0-9]"


def email_pattern(email: str) -> str:
	"""The address, not a longer one that ends with it (`adam.vega@x` holds `m.vega@x`)."""
	return rf"(^|[^a-z0-9._%+-]){re.escape(email.lower())}($|[^a-z0-9_-])"


def phone_pattern(number: str) -> str:
	"""The number in any common layout (`+1 530 555 0101`, `(530) 555-0101`, `530.555.0101`) and nothing longer."""
	d = "".join(c for c in number if c.isdigit())[-10:]
	return rf"(^|{NOT_DIGIT})(1{NOT_DIGIT}{{0,3}})?{d[:3]}{NOT_DIGIT}{{0,3}}{d[3:6]}{NOT_DIGIT}{{0,3}}{d[6:]}($|{NOT_DIGIT})"


def name_pattern(first: str, last: str) -> str:
	sep = "[^a-z0-9]{1,3}"
	return rf"{first.lower()}{sep}{last.lower()}|{last.lower()}{sep}{first.lower()}"


def text_columns() -> dict[str, list[str]]:
	"""{table: [text-like columns]} of the current database's base tables."""
	types = ", ".join(f"'{t}'" for t in TEXT_TYPES)
	rows = frappe.db.sql(
		f"""select c.table_name, c.column_name from information_schema.columns c
		join information_schema.tables t on t.table_schema = c.table_schema and t.table_name = c.table_name
		where c.table_schema = database() and t.table_type = 'BASE TABLE' and c.data_type in ({types})
		order by c.table_name, c.ordinal_position""",
		as_list=True,
	)
	out: dict[str, list[str]] = {}
	for table, column in rows:
		out.setdefault(table, []).append(column)
	return out


def search_keys() -> set[tuple[str, str]]:
	"""The `(doctype, name)` of every row in Frappe's global search."""
	return {tuple(row) for row in frappe.db.sql("select doctype, name from `__global_search`")}


def count(table: str, column: str, regex: str, known: set | None = None) -> int:
	"""Rows of `table` whose `column` matches `regex`, not counting the `known` ones."""
	query = f"from `{table}` where `{column}` regexp %(p)s"
	values = {"p": f"(?i){regex}"}
	if known is None:
		return frappe.db.sql(f"select count(*) {query}", values)[0][0]
	return sum(1 for row in frappe.db.sql(f"select doctype, name {query}", values) if tuple(row) not in known)


def scan(
	patterns: dict[str, str], known_rows: dict[str, set] | None = None
) -> dict[tuple[str, str], dict[str, int]]:
	"""Columns holding any pattern, with the number of rows per pattern."""
	known_rows = known_rows or {}
	combined = "(?i)(" + "|".join(f"(?:{regex})" for regex in patterns.values()) + ")"
	hits = {}
	for table, columns in text_columns().items():
		flags = ", ".join(f"max(`{c}` regexp %(p)s)" for c in columns)
		found = frappe.db.sql(f"select {flags} from `{table}`", {"p": combined}, as_list=True)[0]
		for column, flag in zip(columns, found, strict=True):
			if flag:
				known = known_rows.get(table)
				found_in = {
					label: n for label, regex in patterns.items() if (n := count(table, column, regex, known))
				}
				if found_in:
					hits[(table, column)] = found_in
	return hits
