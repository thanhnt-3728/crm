# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fill a new CRM Erasure Request from what the logger typed and from the record it was started from."""

import frappe
from frappe import _

from crm.privacy.identifiers import normalize_identifier, validate_identifier

SOURCE_DOCTYPES = ("CRM Lead", "CRM Deal", "Contact")
KIND_LABEL = {"email": "Email", "phone": "Phone"}


def add_identifier(doc, kind: str, value: str | None, *, typed: bool, source=None) -> bool:
	"""Append an identifier unless the same one is already listed. Typed values must be valid (RT-4);
	values read from a record are skipped when they are not. Returns True when a row was added.
	`source` is a (doctype, name) pair for a value that came from a record."""
	value = str(value or "").strip()
	if not value:
		return False
	if typed:
		validate_identifier(kind, value)
	else:
		try:
			validate_identifier(kind, value)
		except frappe.ValidationError:
			frappe.clear_last_message()
			return False
	normalized = normalize_identifier(kind, value)
	if any(r.kind == KIND_LABEL[kind] and r.normalized == normalized for r in doc.get("identifiers")):
		return False
	source_doctype, source_name = source or (None, None)
	doc.append(
		"identifiers",
		{
			"kind": KIND_LABEL[kind],
			"value": value,
			"normalized": normalized,
			"source": "Typed" if typed else "Record",
			"source_doctype": source_doctype,
			"source_name": source_name,
		},
	)
	return True


def add_typed_identifiers(doc, emails, phones) -> None:
	for value in emails or []:
		add_identifier(doc, "email", value, typed=True)
	for value in phones or []:
		add_identifier(doc, "phone", value, typed=True)


def _add_source_match(doc, doctype: str, name: str, label: str | None, reason: str) -> None:
	doc.append(
		"matches",
		{
			"reference_doctype": doctype,
			"reference_name": name,
			"label": (label or name)[:140],
			"reason": reason,
			"confirmed": 1,
			"is_source": 1,
			"relation": "Direct",
		},
	)


def _add_contact(doc, contact: str, reason: str) -> str | None:
	"""Confirm a Contact and take every email and phone it holds. Returns its full name."""
	frappe.has_permission("Contact", "read", contact, throw=True)
	record = frappe.get_doc("Contact", contact)
	_add_source_match(doc, "Contact", contact, record.full_name, reason)
	source = ("Contact", contact)
	for row in record.email_ids:
		add_identifier(doc, "email", row.email_id, typed=False, source=source)
	for row in record.phone_nos:
		add_identifier(doc, "phone", row.phone, typed=False, source=source)
	return record.full_name


def _add_lead_or_deal_fields(doc, doctype: str, name: str, reason: str) -> str | None:
	fields = ["lead_name", "first_name", "last_name", "email", "mobile_no", "phone"]
	if doctype == "CRM Deal":
		fields.append("organization")
	record = frappe.db.get_value(doctype, name, fields, as_dict=True)
	person = record.lead_name or " ".join(filter(None, (record.first_name, record.last_name))) or None
	_add_source_match(doc, doctype, name, person or record.get("organization"), reason)
	source = (doctype, name)
	add_identifier(doc, "email", record.email, typed=False, source=source)
	add_identifier(doc, "phone", record.mobile_no, typed=False, source=source)
	add_identifier(doc, "phone", record.phone, typed=False, source=source)
	return person


def _deal_contact(deal: str, contact: str | None) -> str | None:
	listed = frappe.get_all(
		"CRM Contacts",
		filters={"parent": deal, "parenttype": "CRM Deal"},
		pluck="contact",
		order_by="idx",
	)
	listed = [c for c in listed if c]
	if contact:
		if contact not in listed:
			frappe.throw(_("{0} is not a contact of {1}").format(contact, deal))
		return contact
	if len(listed) > 1:
		frappe.throw(_("{0} has several contacts: choose the one the request is about").format(deal))
	return listed[0] if listed else None


def add_source(doc, doctype: str | None, name: str | None, contact: str | None) -> str | None:
	"""Pre-confirm the record the request was started from and seed identifiers from it.
	Returns the person's name when the record has one. Raises PermissionError when the user cannot read it."""
	if doctype not in SOURCE_DOCTYPES:
		frappe.throw(_("A request can only be started from a lead, a deal or a contact"))
	if not name:
		frappe.throw(_("Choose the {0} the request is about").format(_(doctype)))
	frappe.has_permission(doctype, "read", name, throw=True)  # RT-5: the logger must be able to open it
	reason = _("The request was started from this record")
	if doctype == "Contact":
		return _add_contact(doc, name, reason)
	if doctype == "CRM Lead":
		return _add_lead_or_deal_fields(doc, doctype, name, reason)
	chosen = _deal_contact(name, contact)
	if not chosen:
		return _add_lead_or_deal_fields(doc, doctype, name, reason)
	deal_label = frappe.db.get_value("CRM Deal", name, "organization")
	_add_source_match(doc, doctype, name, deal_label, reason)
	return _add_contact(doc, chosen, reason)
