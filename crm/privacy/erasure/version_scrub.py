# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Change history (Version `data`) without damaging anyone else's (design 5.6; review H1, H2).

A Version records what changed on a document in `changed`, `added`, `removed` and `row_changed`. What is hers depends
on whose document it is, so the caller states the rules:
- her own records (lead, contact, address) and the activities she is the subject of: `field_wise` fields are wiped
  whatever they hold;
- everything else (deals, emails with other people on them, events): only values that are hers are replaced: her
  identifiers (an address inside a list is replaced alone), her full names, her name parts in name fields, and a text
  that mentions her when `mentions` is set. In a child table only her rows count (`her_rows`), and in those the
  `row_fields` are wiped. Categorical words (gender, salutation, job title) are never matched by value.
Pure: no database.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

import frappe

from crm.privacy.erasure.text_mentions import mentions_identifier
from crm.privacy.erasure.value_matcher import Identifiers, has_address, holds_her_value, replace_addresses

NAME_FIELDS = frozenset({"first_name", "middle_name", "last_name", "lead_name", "full_name"})


@dataclass(frozen=True)
class VersionRules:
	identifiers: Identifiers
	placeholder: str
	field_wise: frozenset = frozenset()  # wiped wholesale, in the document and in its child rows
	row_fields: frozenset = frozenset()  # wiped in a child row that is hers
	names: frozenset = frozenset()  # her full names: a whole value in any field
	name_parts: frozenset = frozenset()  # her first, middle and last names: a whole value in a name field
	her_rows: Callable[[str, dict], bool] | None = None  # is this child row hers? (table, row)
	mentions: bool = False  # a text that names her is replaced whole

	def names_for(self, field: str) -> frozenset:
		return self.names | self.name_parts if field in NAME_FIELDS else self.names

	def names_in(self, text: str) -> bool:
		return any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.IGNORECASE) for n in self.names)


def _clean(rules: VersionRules, field: str, value, hers_row: bool = False):
	if not isinstance(value, str) or not value.strip():
		return value
	if field in rules.field_wise or (hers_row and field in rules.row_fields):
		return rules.placeholder
	if has_address(value, rules.identifiers.emails):
		return replace_addresses(value, rules.identifiers.emails, rules.placeholder)
	if holds_her_value(value, rules.identifiers, rules.names_for(field)):
		return rules.placeholder
	if rules.mentions and (mentions_identifier(value, rules.identifiers) or rules.names_in(value)):
		return rules.placeholder
	return value


def _row_is_hers(rules: VersionRules, table: str, row: dict) -> bool:
	if rules.her_rows and rules.her_rows(table, row):
		return True
	return any(holds_her_value(v, rules.identifiers) for v in row.values() if isinstance(v, str))


def scrub_version(data: str, rules: VersionRules, placeholder: str | None = None) -> tuple[str, bool]:
	"""Version `data` with what is hers replaced by the placeholder. Returns (data, whether anything changed);
	data that is not JSON, or has nothing of hers, comes back as it was."""
	try:
		document = frappe.parse_json(data)
	except Exception:
		return data, False
	if not isinstance(document, dict):
		return data, False
	changed = False

	def clean(field, value, hers_row=False):
		nonlocal changed
		new = _clean(rules, field, value, hers_row)
		changed = changed or new != value
		return new

	def clean_changes(entries, hers_row=False):
		return [
			[field, clean(field, old, hers_row), clean(field, new, hers_row)] for field, old, new in entries
		]

	def clean_row(table, row):
		hers = _row_is_hers(rules, table, row)
		return {field: clean(field, value, hers) for field, value in row.items()}

	if document.get("changed"):
		document["changed"] = clean_changes(document["changed"])
	for key in ("added", "removed"):
		if document.get(key):
			document[key] = [[table, clean_row(table, row)] for table, row in document[key]]
	if document.get("row_changed"):
		rows = []
		for table, index, name, entries in document["row_changed"]:
			shown = {"name": name, **{field: new for field, _old, new in entries}}
			rows.append([table, index, name, clean_changes(entries, _row_is_hers(rules, table, shown))])
		document["row_changed"] = rows
	return (frappe.as_json(document), True) if changed else (data, False)
