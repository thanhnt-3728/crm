# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Pure helpers over match rows: keys, the API key format, and the re-discovery diff (F6)

API key format (phase 04 sends these to `crm.api.erasure.set_exclusions`):
    "<ref_doctype>::<ref_name>"   e.g. "CRM Lead::CRM-LEAD-2026-00012"
The doctype part never contains "::", so the key splits on its first "::".
"""

from collections.abc import Iterable

from frappe.utils import cint

KEY_SEPARATOR = "::"
MATCH_FIELDS = ("ref_doctype", "ref_name", "reason", "action", "excluded", "new_since_logging")


def match_key(row) -> tuple[str, str]:
	return (row.get("ref_doctype"), row.get("ref_name"))


def format_key(ref_doctype: str, ref_name: str) -> str:
	return f"{ref_doctype}{KEY_SEPARATOR}{ref_name}"


def parse_key(key: str) -> tuple[str, str]:
	"""(ref_doctype, ref_name) of an API key; ValueError when it is not one"""
	ref_doctype, separator, ref_name = (key or "").partition(KEY_SEPARATOR)
	if not separator or not ref_doctype or not ref_name:
		raise ValueError("a match key looks like '<doctype>::<name>'")
	return ref_doctype, ref_name


def match_row(row) -> dict:
	"""A plain dict with exactly the CRM Erasure Match fields, flags as 0/1"""
	cleaned = {field: row.get(field) for field in MATCH_FIELDS}
	cleaned["excluded"] = 1 if cint(cleaned["excluded"]) else 0
	cleaned["new_since_logging"] = 1 if cint(cleaned["new_since_logging"]) else 0
	return cleaned


def diff_matches(stored: Iterable, current: Iterable, keep_missing: bool = True) -> list[dict]:
	"""Rows for the request after re-discovery, de-duplicated on (ref_doctype, ref_name)

	A row discovery still finds takes `reason` and `action` from discovery and keeps the stored
	`excluded` / `new_since_logging` flags; a row found for the first time is flagged
	`new_since_logging`. Stored rows discovery no longer finds are kept (`keep_missing`: once
	listed, a record stays until someone excludes it) or dropped (after an exclusion change, rows
	that were reachable only through the now-excluded record).
	"""
	found = {}
	for row in current or []:
		found.setdefault(match_key(row), match_row(row))
	rows, seen = [], set()
	for row in stored or []:
		key = match_key(row)
		if key in seen or (key not in found and not keep_missing):
			continue
		seen.add(key)
		kept = match_row(row)
		if key in found:
			kept.update(reason=found[key]["reason"], action=found[key]["action"])
		rows.append(kept)
	for key, row in found.items():
		if key not in seen:
			seen.add(key)
			rows.append({**row, "excluded": 0, "new_since_logging": 1})
	return rows


# Reason of a row excluded only because every way to reach it runs through an excluded match.
# Rows the rep excluded by hand keep their discovery reason, so the two stay apart without a field.
VIA_EXCLUDED = "via_excluded"


def hand_excluded(stored: Iterable) -> set[tuple[str, str]]:
	"""Keys of stored rows excluded by someone's choice (not merely through an excluded parent)"""
	return {
		match_key(row)
		for row in stored or []
		if cint(row.get("excluded")) and row.get("reason") != VIA_EXCLUDED
	}


def plan_exclusions(stored: Iterable, hand: set, reachable: Iterable, aware: Iterable) -> list[dict]:
	"""Rows after an exclusion change or a refresh; a stored row is never dropped

	`hand`: keys excluded by choice. `reachable`: discovery ignoring exclusions; `aware`: discovery
	honouring `hand`. A row `reachable` finds but `aware` does not is excluded as VIA_EXCLUDED;
	when its parent is included again it returns to its own state (excluded only if in `hand`).
	Rows found for the first time are appended, flagged `new_since_logging`.
	"""
	found = {match_key(row): match_row(row) for row in reachable or []}
	found.update({match_key(row): match_row(row) for row in aware or []})
	aware_keys = {match_key(row) for row in aware or []}
	rows, seen = [], set()
	for row in stored or []:
		key = match_key(row)
		if key in seen:
			continue
		seen.add(key)
		kept = match_row(row)
		if key in found:
			kept.update(reason=found[key]["reason"], action=found[key]["action"])
		if key in hand:
			kept["excluded"] = 1
		elif key in found and key not in aware_keys:
			kept.update(excluded=1, reason=VIA_EXCLUDED)
		elif kept["reason"] == VIA_EXCLUDED and key not in found:
			pass  # reachable no more at all: stays excluded where it was
		else:
			kept["excluded"] = 0
		rows.append(kept)
	for row in aware or []:
		key = match_key(row)
		if key not in seen:
			seen.add(key)
			rows.append({**match_row(row), "excluded": 0, "new_since_logging": 1})
	return rows
