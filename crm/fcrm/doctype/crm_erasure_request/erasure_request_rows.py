# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Check the child rows the controller's seams write (matches, identifiers)

The erasure registry (`crm.erasure`) is imported inside the functions: this module loads with the
doctype, which must work before the registry package is importable (install, early migrate).
"""

from collections.abc import Iterable

import frappe
from frappe import _
from frappe.utils import cint

MATCH_KEYS = frozenset({"ref_doctype", "ref_name", "reason", "action", "excluded", "new_since_logging"})
# `normalized` is accepted so callers may pass `identifier_rows()` output, but it is recomputed
IDENTIFIER_KEYS = frozenset({"kind", "value", "normalized"})


def clean_match_rows(rows: Iterable[dict], stored_keys: Iterable[tuple[str, str]] = ()) -> list[dict]:
	"""Rows for `matches`: a registry match-source doctype and, for rows new to the request, a record
	that exists. Rows already stored were checked when added, so a record deleted since then does
	not block a refresh. Flags are coerced to 0/1; unknown keys raise ValueError.
	"""
	allowed, stored = match_row_doctypes(), set(stored_keys)
	cleaned = []
	for row in rows:
		_reject_unknown_keys(row, MATCH_KEYS)
		ref_doctype, ref_name = row.get("ref_doctype"), row.get("ref_name")
		if not ref_doctype or not ref_name:
			raise ValueError("a match needs ref_doctype and ref_name")
		if ref_doctype not in allowed:
			frappe.throw(_("{0} records cannot be erasure matches").format(ref_doctype))
		if (ref_doctype, ref_name) not in stored and not frappe.db.exists(ref_doctype, ref_name):
			frappe.throw(_("{0} {1} not found").format(_(ref_doctype), ref_name))
		cleaned.append(
			{
				**row,
				"excluded": 1 if cint(row.get("excluded")) else 0,
				"new_since_logging": 1 if cint(row.get("new_since_logging")) else 0,
			}
		)
	return cleaned


def match_row_doctypes() -> set[str]:
	"""Doctypes discovery emits as match rows: installed registry entries that are not hidden copies"""
	from crm.erasure import registry_model
	from crm.erasure.discovery import installed
	from crm.erasure.registry import REGISTRY

	return {
		entry.doctype
		for entry in REGISTRY
		if entry.match_rows and entry.kind != registry_model.HIDDEN and installed(entry)
	}


def clean_identifier_rows(rows: Iterable[dict], region: str | None = None) -> list[dict]:
	"""Rows for `identifiers` with `normalized` computed here, never taken from the caller

	Phones typed without a country code parse in `region` (the site default when None).
	Errors name the kind and position of a bad value, never the value (it may be personal data).
	"""
	from crm.erasure.identifiers import normalize_email, normalize_phone_identifier

	normalizers = {"Email": normalize_email, "Phone": lambda v: normalize_phone_identifier(v, region)}
	cleaned, positions = [], dict.fromkeys(normalizers, 0)
	for row in rows:
		_reject_unknown_keys(row, IDENTIFIER_KEYS)
		kind, value = row.get("kind"), row.get("value")
		if kind not in normalizers or not value:
			raise ValueError("an identifier needs kind Email or Phone and a value")
		positions[kind] += 1
		try:
			normalized = normalizers[kind](value)
		except ValueError as e:
			frappe.throw(_("Check the identifiers: {0} {1}: {2}").format(_(kind), positions[kind], str(e)))
		cleaned.append({"kind": kind, "value": value, "normalized": normalized})
	return cleaned


def apply_exclusions(matches, excluded: Iterable[tuple[str, str]]) -> None:
	"""Set `excluded` on each match row from (ref_doctype, ref_name) keys; unknown keys raise"""
	keys = {tuple(key) for key in excluded}
	unknown = keys - {(row.ref_doctype, row.ref_name) for row in matches}
	if unknown:
		raise ValueError(f"not a match of this request: {sorted(unknown)}")
	for row in matches:
		row.excluded = 1 if (row.ref_doctype, row.ref_name) in keys else 0


def _reject_unknown_keys(row: dict, allowed: frozenset) -> None:
	unknown = set(row) - allowed
	if unknown:
		raise ValueError(f"unexpected keys {sorted(unknown)}")
