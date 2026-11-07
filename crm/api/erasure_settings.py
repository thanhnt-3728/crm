# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Endpoints of the Privacy settings page (System Manager only): head of compliance, contract retention, the
personal-fields list, members and the do-not-contact secret's health. Writes go through the settings document, so
its own validation (never-personal fields, duplicates, unknown fields) still applies. The hash secret never leaves."""

import frappe
from frappe import _
from frappe.model import no_value_fields, table_fields

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import NEVER_PERSONAL_FIELDS, SETTINGS
from crm.privacy.compliance_members import list_members, require_system_manager
from crm.privacy.do_not_contact import secret_available


def _allowed_doctypes() -> list[str]:
	options = frappe.get_meta("CRM Personal Field").get_field("document_type").options
	return [name for name in (options or "").split("\n") if name]


def _settings_response(doc) -> dict:
	return {
		"head_of_compliance": doc.head_of_compliance,
		"contract_retention_months": doc.contract_retention_months or 0,
		"personal_fields": [
			{"name": row.name, "document_type": row.document_type, "fieldname": row.fieldname}
			for row in doc.personal_fields
		],
		"document_types": _allowed_doctypes(),
		"secret_available": secret_available(),
		"members": list_members(),
	}


@frappe.whitelist()
def get_privacy_settings() -> dict:
	"""`{head_of_compliance, contract_retention_months, personal_fields: [{name, document_type, fieldname}],
	document_types, secret_available, members: [{user, full_name, enabled}]}`. System Manager only."""
	require_system_manager(frappe.session.user)
	return _settings_response(frappe.get_doc(SETTINGS))


def _clean_rows(personal_fields) -> list[dict]:
	"""The rows as `{document_type, fieldname}` pairs; anything else is refused before it reaches the document."""
	if not isinstance(personal_fields, list):
		frappe.throw(_("Personal fields must be a list"))
	rows = []
	for row in personal_fields:
		document_type = row.get("document_type") if isinstance(row, dict) else None
		fieldname = row.get("fieldname") if isinstance(row, dict) else None
		if not (isinstance(document_type, str) and isinstance(fieldname, str) and fieldname.strip()):
			frappe.throw(_("Each personal field needs a document type and a field name"))
		rows.append({"document_type": document_type, "fieldname": fieldname.strip()})
	return rows


def _field_keys(rows) -> set[str]:
	return {f"{row.document_type}.{row.fieldname}" for row in rows}


def _audit_fields(doc, before: set[str], after: set[str]) -> None:
	"""A removed row means that field is no longer erased, so who changed the list is on record: a Comment naming the
	user and the `doctype.field` rows added and removed (field names, no personal data). Nothing when it did not change."""
	changes = []
	if added := sorted(after - before):
		changes.append(_("added {0}").format(", ".join(added)))
	if removed := sorted(before - after):
		changes.append(_("removed {0}").format(", ".join(removed)))
	if changes:
		doc.add_comment(
			"Info", _("{0} changed the personal fields: {1}").format(frappe.session.user, "; ".join(changes))
		)


@frappe.whitelist()
def save_privacy_settings(
	head_of_compliance: str | None, contract_retention_months: int | None, personal_fields: list
) -> dict:
	"""Replace the head of compliance, the contract retention period and the whole personal-fields list.
	Returns what `get_privacy_settings` does. System Manager only."""
	require_system_manager(frappe.session.user)
	rows = _clean_rows(personal_fields)
	doc = frappe.get_doc(SETTINGS)
	before = _field_keys(doc.personal_fields)
	doc.head_of_compliance = head_of_compliance or None
	doc.contract_retention_months = contract_retention_months or 0
	doc.set("personal_fields", rows)
	doc.save()
	_audit_fields(doc, before, _field_keys(doc.personal_fields))
	return _settings_response(doc)


@frappe.whitelist()
def get_personal_field_choices(document_type: str) -> list[dict]:
	"""The fields of one listed doctype that can hold personal data: `{fieldname, label, fieldtype}`, with
	layout and table fields and the fields reports group by left out. Custom fields are included. System Manager only."""
	require_system_manager(frappe.session.user)
	if document_type not in _allowed_doctypes():
		frappe.throw(_("{0} cannot be listed as a personal-fields document type").format(document_type))
	return [
		{
			"fieldname": field.fieldname,
			"label": _(field.label or field.fieldname),
			"fieldtype": field.fieldtype,
		}
		for field in frappe.get_meta(document_type).fields
		if field.fieldtype not in no_value_fields
		and field.fieldtype not in table_fields
		and field.fieldname not in NEVER_PERSONAL_FIELDS
	]
