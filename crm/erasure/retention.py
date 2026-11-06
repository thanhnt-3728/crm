# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""What a request keeps once it is Closed (plan open item 1; this is the one place to change it)

Default (proposed to Dana, CCPA 24-month record keeping): masked emails and phones, the request
number and every date are kept; the subject's name is dropped (replaced by the name marker).
Identifiers stay in full until Close because the runbook's final `full_scan` needs them.
"""

import re

from crm.erasure.registry_model import name_marker

MASK = "***"


def mask_email(value: str | None) -> str:
	"""`marisol.reyes@example.net` -> `m***@example.net`"""
	local, _at, domain = (value or "").strip().lower().partition("@")
	return f"{local[:1]}{MASK}@{domain}" if local and domain else MASK


def mask_phone(value: str | None) -> str:
	"""`+14155550123;ext=12` -> `***0123`"""
	digits = re.sub(r"\D", "", (value or "").partition(";ext=")[0])
	return MASK + digits[-4:] if len(digits) >= 4 else MASK


def retention_rows(request) -> list[dict]:
	"""Identifier rows as kept after Close: masked value in both `value` and `normalized`"""
	rows = []
	for row in request.get("identifiers") or []:
		source = row.get("normalized") or row.get("value")
		masked = mask_email(source) if row.get("kind") == "Email" else mask_phone(source)
		rows.append({"kind": row.get("kind"), "value": masked, "normalized": masked})
	return rows


def apply_retention(request) -> None:
	"""Reduce a just-Closed request to what is retained (phase-1 seam `apply_retention_rows`)"""
	request.apply_retention_rows(retention_rows(request), subject_name=name_marker(request.name))
