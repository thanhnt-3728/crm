# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Refuse a lead, deal or contact that would carry the email or phone of an erased person (design 5.9).

One `validate` hook, so manual entry, Data Import, conversion and the API are all covered at once. Only
what is new is checked: a new document, or a value not already on the saved version. An existing record
that holds a shared value stays savable as long as that value is not (re)entered.
"""

import sys

import frappe
from frappe import _

from crm.fcrm.doctype.crm_privacy_settings.crm_privacy_settings import DncSecretUnavailableError
from crm.privacy.do_not_contact import (
	BLOCKING_ERRORS,
	ErasedPersonBlockedError,
	PrivacySettingsIncompleteError,
	blocked_values,
)
from crm.privacy.identifiers import normalize_identifier

LEAD_FIELDS = (("email", "email"), ("mobile_no", "phone"), ("phone", "phone"))
# doctype -> (scalar fields, {child table: fields}), each field as (fieldname, kind)
CHECKED = {
	"CRM Lead": (LEAD_FIELDS, {}),
	"CRM Deal": (LEAD_FIELDS, {"contacts": LEAD_FIELDS}),
	"Contact": (
		(("email_id", "email"), ("mobile_no", "phone"), ("phone", "phone")),
		{"email_ids": (("email_id", "email"),), "phone_nos": (("phone", "phone"),)},
	),
}


def _clean(value) -> str:
	return value.strip() if isinstance(value, str) else ""


def _scalars(doc) -> dict[str, tuple[str, str]]:
	"""`{fieldname: (kind, value)}` for the document's own email and phone fields that hold something."""
	scalars = CHECKED.get(doc.doctype, ((), {}))[0]
	return {f: (kind, _clean(doc.get(f))) for f, kind in scalars if _clean(doc.get(f))}


def _rows(doc) -> dict[str, list[tuple[str, str]]]:
	"""`{table: [(kind, value), ...]}` for the child rows."""
	tables = CHECKED.get(doc.doctype, ((), {}))[1]
	return {
		table: [(kind, _clean(r.get(f))) for r in doc.get(table) or [] for f, kind in fields if _clean(r.get(f))]
		for table, fields in tables.items()
	}


def _key(kind: str, value: str) -> tuple[str, str]:
	return kind, normalize_identifier(kind, value)


def new_values(doc) -> list[tuple[str, str]]:
	"""The values to check: all of a new document's. Of a saved one, a scalar field whose value changed, and a
	child row whose value is not among those the table held (a new row, or a row that was edited). A value moved
	from one scalar field to another counts as changed; one swapped between rows of a table does not."""
	scalars, rows = _scalars(doc), _rows(doc)
	before = None if doc.is_new() else doc.get_doc_before_save()
	if before is None:
		return [*scalars.values(), *(pair for pairs in rows.values() for pair in pairs)]
	saved_scalars, saved_rows = _scalars(before), _rows(before)
	found = [
		pair
		for field, pair in scalars.items()
		if field not in saved_scalars or _key(*pair) != _key(*saved_scalars[field])
	]
	for table, pairs in rows.items():
		held = {_key(*pair) for pair in saved_rows.get(table, [])}
		found += [pair for pair in pairs if _key(*pair) not in held]
	return found


def check_document(doc) -> None:
	"""Raise ErasedPersonBlockedError if a new value is on the list, or PrivacySettingsIncompleteError if the
	list cannot be read (RT-15: a manual save fails closed). Neither message echoes the value."""
	values = new_values(doc)
	if not values:
		return
	try:
		blocked = blocked_values(values)
	except DncSecretUnavailableError:
		frappe.throw(
			_("Privacy settings are incomplete. Ask your administrator."), PrivacySettingsIncompleteError
		)
	if blocked:
		frappe.throw(
			_("This person asked to be erased. Their email or phone can't be added to the CRM."),
			ErasedPersonBlockedError,
		)


def _chain(error: BaseException | None) -> list[BaseException]:
	"""`error` and every exception it was raised from or while handling."""
	found = []
	while error is not None and error not in found:
		found.append(error)
		error = error.__cause__ or error.__context__
	return found


def scrub_block_error_log(doc, method=None) -> None:
	"""`before_insert` hook for Error Log. Frappe's mail sync tries to create a Contact for every address on a
	mail; when the block refuses, it catches that and logs a traceback (with the locals) and a contact name made
	from the address. Decided by the exception being handled while the log is written, never by a word in its
	text (V1):
	* the block error itself: only its class name is kept;
	* another error raised while handling one: the real `Class: message` is kept, the traceback and locals go;
	* anything else is left alone, as is a log that holds no traceback (it was written by hand, like our own
	  class-name-only entries, which are made while a block error is still being handled)."""
	handled = sys.exc_info()[1]
	ours = any(isinstance(error, BLOCKING_ERRORS) for error in _chain(handled))
	if not ours or "Traceback" not in (doc.error or ""):
		return
	if isinstance(handled, BLOCKING_ERRORS):
		doc.error = type(handled).__name__
	else:
		doc.error = f"{type(handled).__name__}: {handled}"
	doc.reference_name = None


def validate_not_blocked(doc, method=None) -> None:
	"""`validate` hook for CRM Lead, CRM Deal and Contact. The erasure engine writes straight to the
	database; the flag is belt and braces for anything it saves."""
	if frappe.flags.in_erasure:
		return
	check_document(doc)
