# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The history part of the plan: change history (Version) and Frappe's deleted copies (Deleted Document).

Read-only. Every Version of an affected record is a target (the scrub decides value by value what to replace). A
Deleted Document is a target when its deleted name is an affected record, or when its data holds one of her
identifiers as a whole field value (RT-4).
"""

import frappe

from crm.privacy.erasure.plan_queries import like_candidates
from crm.privacy.erasure.text_mentions import prefilter_terms
from crm.privacy.erasure.value_matcher import Identifiers, holds_identifier

DELETED_DOCTYPES = ("CRM Lead", "CRM Deal", "Contact", "Address", "Communication")
# Deleted activities of hers carry no identifier, only the record they were about: doctype -> reference fields.
REFERENCING = {
	"FCRM Note": ("reference_doctype", "reference_docname"),
	"CRM Task": ("reference_doctype", "reference_docname"),
	"Comment": ("reference_doctype", "reference_name"),
	"ToDo": ("reference_type", "reference_name"),
}


def _by_doctype(docs: list[tuple[str, str]]) -> dict[str, list[str]]:
	grouped = {}
	for doctype, name in docs:
		grouped.setdefault(doctype, []).append(name)
	return grouped


def versions(docs: list[tuple[str, str]]) -> list[str]:
	"""Version rows of the affected records."""
	found = []
	for doctype, names in _by_doctype(docs).items():
		found += frappe.get_all("Version", {"ref_doctype": doctype, "docname": ["in", names]}, pluck="name")
	return sorted(found)


def about_her(scope: dict) -> list[str]:
	"""Deleted notes, tasks, comments and to-dos whose data points at one of her records (M4)."""
	names = sorted({name for names in scope.values() for name in names})
	found = []
	for doctype, (type_field, name_field) in REFERENCING.items():
		for row in like_candidates("Deleted Document", ["data"], names, deleted_doctype=doctype):
			data = _parse(row.data)
			if isinstance(data, dict) and data.get(name_field) in scope.get(data.get(type_field), []):
				found.append(row.name)
	return found


def deleted_documents(
	ids: Identifiers, docs: list[tuple[str, str]], gone: list[tuple[str, str]], scope: dict | None = None
) -> list[str]:
	"""Deleted copies of affected or already-deleted confirmed records, and of any record of the CRM kinds whose
	data holds one of her identifiers as a whole value."""
	found = set(about_her(scope or {}))
	for doctype, names in _by_doctype([*docs, *gone]).items():
		found |= set(
			frappe.get_all(
				"Deleted Document", {"deleted_doctype": doctype, "deleted_name": ["in", names]}, pluck="name"
			)
		)
	for doctype in DELETED_DOCTYPES:
		for row in like_candidates(
			"Deleted Document", ["data"], prefilter_terms(ids), deleted_doctype=doctype
		):
			if row.name not in found and holds_identifier(_parse(row.data), ids):
				found.add(row.name)
	return sorted(found)


def _parse(data: str | None):
	try:
		return frappe.parse_json(data or "")
	except Exception:
		return None
