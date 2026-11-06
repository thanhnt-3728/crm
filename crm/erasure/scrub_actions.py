# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Pure scrub helpers: the value a field treatment writes, address-list scrub, Version entry filter

No database access here: `record_writes` writes the values, `hidden_copies` the filtered Versions.
Every helper is idempotent, so a re-run computes the value already stored and writes nothing.
"""

import json
import re

from frappe.utils import parse_addr

from crm.erasure import registry_model as model

_LIST_SEPARATORS = re.compile(r"[,;\n]")
VERSION_KEYS = ("changed", "added", "removed", "row_changed")


def field_value(spec: tuple, row: dict, ids, request_name: str):
	"""New value of `spec`'s field given the row as stored (scalar treatments only)

	Markers replace present values only: an empty field stays empty, so nothing new is written.
	"""
	fieldname, treatment = spec[0], spec[1]
	current = row.get(fieldname)
	if treatment == model.CLEAR:
		return None
	if treatment in (model.MARKER, model.NAME_MARKER):
		if current in (None, ""):
			return current
		return (model.content_marker if treatment == model.MARKER else model.name_marker)(request_name)
	if treatment == model.REMOVE_ADDRESS:
		return scrub_address_list(current, ids)
	if treatment in (model.CLEAR_IF_HERS, model.MARKER_IF_HERS):
		if not is_hers(row.get(spec[2]), ids):
			return current
		return None if treatment == model.CLEAR_IF_HERS else model.name_marker(request_name)
	raise ValueError(f"not a scalar treatment: {treatment}")


def is_hers(value, ids) -> bool:
	"""True when a single-value column (an address, an address list or a phone) is one of hers"""
	return bool(value) and (ids.matches_email(str(value)) or ids.matches_phone(str(value)))


def scrub_address_list(value: str | None, ids) -> str | None:
	"""`value` without her addresses; other entries keep their spelling; None when none is left

	Returned unchanged when none of hers is in it (so a re-run writes nothing).
	"""
	if not value:
		return value
	parts = [part.strip() for part in _LIST_SEPARATORS.split(str(value)) if part.strip()]
	kept = [part for part in parts if (parse_addr(part)[1] or "").strip().lower() not in ids.emails]
	if len(kept) == len(parts):
		return value
	return ", ".join(kept) or None


def filter_version_data(data: dict, person_fields, ids, her_rows) -> dict:
	"""A copy of Version `data` without entries naming `person_fields`, her child rows or her identifiers

	changed [[field, old, new]]; added/removed [[table, row]]; row_changed [[table, idx, row, [[f, o, n]]]].
	Keys other than those four are kept as they are.
	"""
	kept = dict(data)
	if "changed" in data:
		kept["changed"] = [e for e in data["changed"] if not _personal_change(e, person_fields, ids)]
	for key in ("added", "removed"):
		if key in data:
			kept[key] = [e for e in data[key] if not _her_row_entry(e, her_rows, ids)]
	if "row_changed" in data:
		kept["row_changed"] = []
		for entry in data["row_changed"]:
			if len(entry) < 4 or entry[2] in her_rows:
				continue
			changes = [change for change in entry[3] or [] if not _mentions(change, ids)]
			if changes:
				kept["row_changed"].append([*entry[:3], changes])
	return kept


def version_is_empty(data: dict) -> bool:
	return not any(data.get(key) for key in VERSION_KEYS)


def _personal_change(entry, person_fields, ids) -> bool:
	return not entry or entry[0] in person_fields or _mentions(entry, ids)


def _her_row_entry(entry, her_rows, ids) -> bool:
	row = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
	return row.get("name") in her_rows or _mentions(entry, ids)


def _mentions(value, ids) -> bool:
	return ids.matches_text(json.dumps(value, default=str))
