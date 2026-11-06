# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt
"""Checks for the Close-time retention seam (`CRMErasureRequest.apply_retention_rows`)

The rows come from `crm.erasure.retention.retention_rows` and are already masked, so they are
stored verbatim (never normalized again: a masked value is not a valid identifier).
"""

import frappe
from frappe import _

from crm.fcrm.doctype.crm_erasure_request.erasure_states import CLOSED, PRIVACY_OFFICER_ROLE, REJECTED

RETAINED_KEYS = frozenset({"kind", "value", "normalized"})
KINDS = ("Email", "Phone")


def assert_can_apply_retention(request, subject_name: str) -> None:
	"""Only on a request stored as Closed or Rejected, only by a Privacy Officer, with a subject name"""
	if frappe.db.get_value(request.doctype, request.name, "status") not in (CLOSED, REJECTED):
		frappe.throw(_("Retention applies to {0} only once it is Closed or Rejected").format(request.name))
	if PRIVACY_OFFICER_ROLE not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("Only a Privacy Officer can close {0}").format(request.name), frappe.PermissionError)
	if not (subject_name or "").strip():
		raise ValueError("a retained subject name is required")


def retained_identifier_rows(rows: list[dict]) -> list[dict]:
	"""`rows` as identifier child rows; ValueError on unknown keys, kinds or empty values"""
	cleaned = []
	for row in rows:
		if set(row) - RETAINED_KEYS or row.get("kind") not in KINDS or not row.get("value"):
			raise ValueError("a retained identifier is {kind: Email|Phone, value, normalized}")
		cleaned.append({key: row.get(key) for key in RETAINED_KEYS})
	return cleaned
