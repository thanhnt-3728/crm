# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Runbook: one parameterised MariaDB `select` per registry entry, built from its finders

The SQL never holds an identifier: `%(email)s` (one address, lower-case) and `%(phone_digits)s`
(one number's national digits) are filled by the runbook's console helper `find`, once per
identifier, the other one empty. Earlier results are passed as `%(<doctype>_names)s` (names) or
`%(..._keys)s` ("<doctype>::<name>" keys). Like discovery's prefilter, a hit is loose (a longer
address that contains hers also hits), so every row is checked by eye before it is changed.
"""

import re

from crm.erasure import registry_model as model
from crm.erasure.discovery_queries import TABLE_KEYS


def entry_select(entry: model.Entry) -> tuple[str, dict[str, str]] | None:
	"""(SQL, {placeholder: console expression}) finding `entry`'s rows; None without finders"""
	params: dict[str, str] = {}
	conditions = [_condition(entry, finder, params) for finder in entry.finders]
	if not conditions:
		return None
	where = "\n   or ".join(conditions)
	return f"select {_key(entry)} from {_quote(_table(entry))}\nwhere {where}", params


def keys_placeholder(targets: tuple[str, ...], params: dict[str, str]) -> str:
	"""Placeholder for "<doctype>::<name>" keys of matches of `targets`, registered in `params`"""
	if targets == model.ANY_MATCH:
		name, expression = "match_keys", "keys()"
	else:
		name = "subject_keys" if targets == model.SUBJECTS else "_".join(map(_slug, targets)) + "_keys"
		expression = f"keys({', '.join(map(repr, targets))})"
	params[name] = expression
	return f"%({name})s"


def _condition(entry, finder, params) -> str:
	if isinstance(finder, model.Ref):
		pair = f"concat({_quote(finder.doctype_column)}, '::', {_quote(finder.name_column)})"
		return f"{pair} in {keys_placeholder(finder.targets, params)}"
	if isinstance(finder, model.Link):
		return f"{_quote(finder.column)} in {_names(finder.target, params)}"
	if isinstance(finder, model.ChildLink):
		keys = keys_placeholder(finder.targets, params)
		return _in_child(entry, finder.child_doctype, f"concat(`link_doctype`, '::', `link_name`) in {keys}")
	if isinstance(finder, model.Backref):
		source = f"select {_quote(finder.column)} from {_quote('tab' + finder.source)} where `name` in {_names(finder.source, params)}"
		return f"{_quote(finder.by)} in ({source})"
	if isinstance(finder, model.ChildBackref):
		source = (
			f"select `link_name` from {_quote('tab' + finder.child_doctype)} "
			f"where `parenttype` = '{finder.source}' and `parent` in {_names(finder.source, params)} "
			f"and `link_doctype` = '{entry.doctype}'"
		)
		return f"`name` in ({source})"
	if isinstance(finder, model.Emails | model.Phones | model.Text):
		return _identifier_condition(entry, finder)
	raise TypeError(f"no runbook SQL for {type(finder).__name__}")


def _identifier_condition(entry, finder) -> str:
	parts = []
	if not isinstance(finder, model.Phones):
		parts.append(_guarded("email", [email_hit(column) for column in finder.columns]))
	if not isinstance(finder, model.Emails):
		parts.append(_guarded("phone_digits", [digits_hit(column) for column in finder.columns]))
	condition = " or ".join(parts)
	child = getattr(finder, "child_doctype", None)
	return _in_child(entry, child, condition) if child else condition


def email_hit(column: str) -> str:
	return f"locate(%(email)s, lower({_quote(column)})) > 0"


def digits_hit(column: str) -> str:
	return f"locate(%(phone_digits)s, regexp_replace({_quote(column)}, '[^0-9]', '')) > 0"


def _guarded(placeholder: str, hits: list[str]) -> str:
	"""An empty identifier would hit every row: the condition only applies when it is set"""
	return f"(%({placeholder})s <> '' and ({' or '.join(hits)}))"


def _in_child(entry, child_doctype: str, condition: str) -> str:
	return (
		f"`name` in (select `parent` from {_quote('tab' + child_doctype)} "
		f"where `parenttype` = '{entry.doctype}' and ({condition}))"
	)


def _names(doctype: str, params: dict[str, str]) -> str:
	name = f"{_slug(doctype)}_names"
	params[name] = f"names({doctype!r})"
	return f"%({name})s"


def _key(entry) -> str:
	columns = TABLE_KEYS.get(entry.table, ("name",))
	if len(columns) == 1:
		return _quote(columns[0])
	return "concat(" + ", '::', ".join(map(_quote, columns)) + ")"


def _table(entry) -> str:
	return entry.table or f"tab{entry.doctype}"


def _slug(doctype: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", doctype.lower()).strip("_")


def _quote(identifier: str) -> str:
	return f"`{identifier}`"
